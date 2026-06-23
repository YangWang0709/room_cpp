"""Global stable pose entry point for Infinigen.

The default backend is trimesh. Optional C++/auto backends are opt-in skeletons
that currently fall back to trimesh without changing stable pose output.
"""

from __future__ import annotations

import logging
import os

import trimesh

logger = logging.getLogger(__name__)

STABLE_POSE_BACKEND_ENV_VAR = "INFINIGEN_STABLE_POSE_BACKEND"
DISABLE_CPP_STABLE_POSE_ENV_VAR = "INFINIGEN_DISABLE_CPP_STABLE_POSE"
PROFILE_STABLE_POSE_ENV_VAR = "INFINIGEN_PROFILE_STABLE_POSE"
_CPP_BACKENDS = {"cpp", "auto"}


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


def _compute_stable_poses_cpp(
    mesh,
    center_mass=None,
    sigma=0.0,
    n_samples=1,
    threshold=0.0,
    *,
    context=None,
):
    from infinigen.core.constraints.cpp import stable_pose_kernels

    return stable_pose_kernels.compute_stable_poses_cpp(
        mesh,
        center_mass=center_mass,
        sigma=sigma,
        n_samples=n_samples,
        threshold=threshold,
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

    try:
        return _compute_stable_poses_cpp(
            mesh,
            center_mass=center_mass,
            sigma=sigma,
            n_samples=n_samples,
            threshold=threshold,
            context=context,
        )
    except (ImportError, NotImplementedError, RuntimeError) as exc:
        _debug_fallback(backend, context, exc)
        return _compute_stable_poses_trimesh(
            mesh,
            center_mass=center_mass,
            sigma=sigma,
            n_samples=n_samples,
            threshold=threshold,
        )
