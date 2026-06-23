"""Global stable pose entry point for Infinigen.

The default backend is trimesh. Optional C++/auto backends are opt-in skeletons
that currently fall back to trimesh without changing stable pose output.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import logging
import os

import numpy as np
import trimesh

logger = logging.getLogger(__name__)

STABLE_POSE_BACKEND_ENV_VAR = "INFINIGEN_STABLE_POSE_BACKEND"
DISABLE_CPP_STABLE_POSE_ENV_VAR = "INFINIGEN_DISABLE_CPP_STABLE_POSE"
PROFILE_STABLE_POSE_ENV_VAR = "INFINIGEN_PROFILE_STABLE_POSE"
VALIDATE_CPP_STABLE_POSE_ENV_VAR = "INFINIGEN_VALIDATE_CPP_STABLE_POSE"
_CPP_BACKENDS = {"cpp", "auto"}


@dataclass(frozen=True)
class StablePoseInputs:
    cvh: object
    center_mass: np.ndarray
    sample_coms: np.ndarray
    vertices: np.ndarray
    triangles: np.ndarray
    face_normals: np.ndarray
    triangles_center: np.ndarray
    face_adjacency: np.ndarray
    face_adjacency_edges: np.ndarray
    threshold: float


class StablePoseBackendError(RuntimeError):
    pass


class StablePoseValidationError(RuntimeError):
    pass


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _stable_pose_backend() -> str:
    backend = os.environ.get(STABLE_POSE_BACKEND_ENV_VAR, "trimesh")
    return backend.strip().lower() or "trimesh"


def _compute_stable_poses_trimesh(
    mesh,
    center_mass=None,
    sigma=0.0,
    n_samples=1,
    threshold=0.0,
):
    return trimesh.poses.compute_stable_poses(
        mesh,
        center_mass=center_mass,
        sigma=sigma,
        n_samples=n_samples,
        threshold=threshold,
    )


def _prepare_stable_pose_inputs(mesh, center_mass=None, sigma=0.0, n_samples=1):
    cvh = mesh.convex_hull
    if center_mass is None:
        center_mass = mesh.center_mass
    center_mass = np.asarray(center_mass, dtype=np.float64)

    sample_coms = []
    while len(sample_coms) < n_samples:
        remaining = n_samples - len(sample_coms)
        coms = np.random.multivariate_normal(
            center_mass,
            sigma * np.eye(3),
            remaining,
        )
        for c in coms:
            dots = np.einsum("ij,ij->i", c - cvh.triangles_center, cvh.face_normals)
            if np.all(dots < 0):
                sample_coms.append(c)

    sample_coms = np.ascontiguousarray(sample_coms, dtype=np.float64).reshape(
        len(sample_coms), 3
    )

    return StablePoseInputs(
        cvh=cvh,
        center_mass=center_mass,
        sample_coms=sample_coms,
        vertices=np.ascontiguousarray(cvh.vertices, dtype=np.float64),
        triangles=np.ascontiguousarray(cvh.triangles, dtype=np.float64),
        face_normals=np.ascontiguousarray(cvh.face_normals, dtype=np.float64),
        triangles_center=np.ascontiguousarray(cvh.triangles_center, dtype=np.float64),
        face_adjacency=np.ascontiguousarray(cvh.face_adjacency, dtype=np.int64),
        face_adjacency_edges=np.ascontiguousarray(
            cvh.face_adjacency_edges, dtype=np.int64
        ),
        threshold=0.0,
    )


def _compute_stable_poses_cpp_from_inputs(inputs, *, context=None):
    from infinigen.core.constraints.cpp import stable_pose_kernels

    return stable_pose_kernels.compute_stable_poses_cpp_from_inputs(
        vertices=inputs.vertices,
        triangles=inputs.triangles,
        face_normals=inputs.face_normals,
        triangles_center=inputs.triangles_center,
        face_adjacency=inputs.face_adjacency,
        face_adjacency_edges=inputs.face_adjacency_edges,
        sample_coms=inputs.sample_coms,
        threshold=inputs.threshold,
        context=context,
    )


def _debug_fallback(backend: str, context, exc: BaseException | None = None) -> None:
    if not _env_truthy(PROFILE_STABLE_POSE_ENV_VAR):
        return
    logger.debug(
        "stable pose backend %s fell back to trimesh; context=%r; reason=%r",
        backend,
        context,
        exc,
    )


def _validate_stable_pose_result(stable_poses, probs):
    if not isinstance(stable_poses, np.ndarray):
        raise StablePoseValidationError("stable_poses must be a numpy array")
    if not isinstance(probs, np.ndarray):
        raise StablePoseValidationError("probs must be a numpy array")
    if stable_poses.ndim != 3:
        raise StablePoseValidationError(
            f"stable_poses must have ndim 3, got {stable_poses.ndim}"
        )
    if stable_poses.shape[1:] != (4, 4):
        raise StablePoseValidationError(
            f"stable_poses must have shape [N, 4, 4], got {stable_poses.shape}"
        )
    if probs.ndim != 1:
        raise StablePoseValidationError(f"probs must have ndim 1, got {probs.ndim}")
    if len(stable_poses) != len(probs):
        raise StablePoseValidationError(
            "stable_poses and probs must have matching lengths, got "
            f"{len(stable_poses)} and {len(probs)}"
        )
    if len(probs) == 0:
        raise StablePoseValidationError("stable pose result must not be empty")
    if not np.all(np.isfinite(stable_poses)):
        raise StablePoseValidationError("stable_poses contains NaN or inf")
    if not np.all(np.isfinite(probs)):
        raise StablePoseValidationError("probs contains NaN or inf")
    if np.all(probs < 0):
        raise StablePoseValidationError("probs must not be all negative")

    rotations = stable_poses[:, :3, :3]
    if rotations.shape[1:] != (3, 3):
        raise StablePoseValidationError(
            f"rotation blocks must have shape [N, 3, 3], got {rotations.shape}"
        )
    dets = np.linalg.det(rotations)
    if not np.all(np.isfinite(dets)):
        raise StablePoseValidationError("rotation determinants contain NaN or inf")
    if np.any(np.abs(dets - 1.0) >= 1e-3):
        raise StablePoseValidationError(
            "rotation determinants must be close to 1, got "
            f"{dets.tolist()}"
        )


def _comparison_metrics(cpp_result, trimesh_result):
    cpp_stable_poses, cpp_probs = cpp_result
    tri_stable_poses, tri_probs = trimesh_result
    cpp_top_idx = int(np.argmax(cpp_probs))
    tri_top_idx = int(np.argmax(tri_probs))
    cpp_top_pose = cpp_stable_poses[cpp_top_idx]
    tri_top_pose = tri_stable_poses[tri_top_idx]

    return {
        "pose_count": (len(cpp_stable_poses), len(tri_stable_poses)),
        "prob_count": (len(cpp_probs), len(tri_probs)),
        "top1_prob_diff": float(abs(cpp_probs[cpp_top_idx] - tri_probs[tri_top_idx])),
        "top1_rotation_diff": float(
            np.max(np.abs(cpp_top_pose[:3, :3] - tri_top_pose[:3, :3]))
        ),
        "top1_translation_diff": float(
            np.max(np.abs(cpp_top_pose[:3, 3] - tri_top_pose[:3, 3]))
        ),
        "prob_sum_diff": float(abs(np.sum(cpp_probs) - np.sum(tri_probs))),
        "has_nan": bool(
            np.isnan(cpp_stable_poses).any()
            or np.isnan(cpp_probs).any()
            or np.isnan(tri_stable_poses).any()
            or np.isnan(tri_probs).any()
        ),
        "has_inf": bool(
            np.isinf(cpp_stable_poses).any()
            or np.isinf(cpp_probs).any()
            or np.isinf(tri_stable_poses).any()
            or np.isinf(tri_probs).any()
        ),
        "rotation_det": (
            float(np.linalg.det(cpp_top_pose[:3, :3])),
            float(np.linalg.det(tri_top_pose[:3, :3])),
        ),
    }


def _compare_stable_pose_results(
    cpp_result,
    trimesh_result,
    *,
    top1_prob_atol=1e-5,
    top1_rotation_atol=1e-5,
    top1_translation_atol=1e-5,
):
    cpp_stable_poses, cpp_probs = cpp_result
    tri_stable_poses, tri_probs = trimesh_result
    _validate_stable_pose_result(cpp_stable_poses, cpp_probs)
    _validate_stable_pose_result(tri_stable_poses, tri_probs)

    metrics = _comparison_metrics(cpp_result, trimesh_result)
    failures = []
    if metrics["pose_count"][0] != metrics["pose_count"][1]:
        failures.append("pose_count")
    if metrics["prob_count"][0] != metrics["prob_count"][1]:
        failures.append("prob_count")
    if metrics["top1_prob_diff"] > top1_prob_atol:
        failures.append("top1_prob")
    if metrics["top1_rotation_diff"] > top1_rotation_atol:
        failures.append("top1_rotation")
    if metrics["top1_translation_diff"] > top1_translation_atol:
        failures.append("top1_translation")
    if metrics["has_nan"]:
        failures.append("has_nan")
    if metrics["has_inf"]:
        failures.append("has_inf")

    if failures:
        raise StablePoseValidationError(
            "stable pose canary comparison failed: "
            f"{', '.join(failures)}; metrics={metrics}"
        )

    return metrics


def compute_stable_poses(
    mesh,
    center_mass=None,
    sigma=0.0,
    n_samples=1,
    threshold=0.0,
    *,
    context=None,
):
    """Compute stable poses through the selected global backend."""
    backend = _stable_pose_backend()

    if backend == "trimesh":
        return _compute_stable_poses_trimesh(
            mesh,
            center_mass=center_mass,
            sigma=sigma,
            n_samples=n_samples,
            threshold=threshold,
        )

    if backend not in _CPP_BACKENDS:
        raise ValueError(
            f"Unsupported stable pose backend {backend!r}; "
            "expected 'trimesh', 'cpp', or 'auto'"
        )

    if _env_truthy(DISABLE_CPP_STABLE_POSE_ENV_VAR):
        _debug_fallback(backend, context)
        return _compute_stable_poses_trimesh(
            mesh,
            center_mass=center_mass,
            sigma=sigma,
            n_samples=n_samples,
            threshold=threshold,
        )

    rng_state_before = np.random.get_state()
    trimesh_result = None

    try:
        inputs = _prepare_stable_pose_inputs(
            mesh,
            center_mass=center_mass,
            sigma=sigma,
            n_samples=n_samples,
        )
        inputs = replace(inputs, threshold=float(threshold))
        cpp_result = _compute_stable_poses_cpp_from_inputs(
            inputs,
            context=context,
        )
        _validate_stable_pose_result(*cpp_result)

        if _env_truthy(VALIDATE_CPP_STABLE_POSE_ENV_VAR):
            np.random.set_state(rng_state_before)
            trimesh_result = _compute_stable_poses_trimesh(
                mesh,
                center_mass=center_mass,
                sigma=sigma,
                n_samples=n_samples,
                threshold=threshold,
            )
            _compare_stable_pose_results(cpp_result, trimesh_result)

        return cpp_result
    except Exception as exc:
        _debug_fallback(backend, context, exc)
        if trimesh_result is not None:
            return trimesh_result
        np.random.set_state(rng_state_before)
        return _compute_stable_poses_trimesh(
            mesh,
            center_mass=center_mass,
            sigma=sigma,
            n_samples=n_samples,
            threshold=threshold,
        )
