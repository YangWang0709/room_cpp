from pathlib import Path

import numpy as np
import pytest

from infinigen.core.util import stable_pose


DIRECT_STABLE_POSE_CALL = "trimesh.poses.compute_stable_poses"
SCAN_ROOTS = ("infinigen", "scripts", "tests")
ALLOWED_DIRECT_CALL_PATHS = {
    Path("infinigen/core/util/stable_pose.py"),
    Path("tests/test_stable_pose_wrapper.py"),
}
SKIPPED_PATH_PARTS = {
    ".git",
    ".pytest_cache",
    "__pycache__",
    "audit_logs",
    "docs",
}
SKIPPED_SUFFIXES = {
    ".so",
    ".pyd",
    ".png",
    ".jpg",
    ".jpeg",
    ".blend",
    ".usd",
    ".usdc",
    ".zip",
    ".prof",
}


def _stable_pose_result(rotation=None, translation=None, probs=None):
    if probs is None:
        probs = np.array([1.0])
    poses = np.repeat(np.eye(4)[np.newaxis, :, :], len(probs), axis=0)
    if rotation is not None:
        poses[:, :3, :3] = rotation
    if translation is not None:
        poses[:, :3, 3] = translation
    return poses, probs


def _rng_state_equal(left, right):
    return (
        left[0] == right[0]
        and np.array_equal(left[1], right[1])
        and left[2:] == right[2:]
    )


def _install_fake_trimesh(monkeypatch, expected, *, consume_random=False):
    calls = []

    def fake_compute_stable_poses(
        mesh_arg,
        *,
        center_mass=None,
        sigma=0.0,
        n_samples=1,
        threshold=0.0,
    ):
        calls.append(
            {
                "mesh": mesh_arg,
                "center_mass": center_mass,
                "sigma": sigma,
                "n_samples": n_samples,
                "threshold": threshold,
            }
        )
        if consume_random:
            np.random.random()
        return expected

    monkeypatch.setattr(
        stable_pose.trimesh.poses,
        "compute_stable_poses",
        fake_compute_stable_poses,
    )
    return calls


def _install_fake_cpp(
    monkeypatch,
    *,
    result=None,
    exception=None,
    consume_random=False,
):
    calls = []

    def fake_compute_stable_poses_cpp(
        mesh_arg,
        center_mass=None,
        sigma=0.0,
        n_samples=1,
        threshold=0.0,
        *,
        context=None,
    ):
        calls.append(
            {
                "mesh": mesh_arg,
                "center_mass": center_mass,
                "sigma": sigma,
                "n_samples": n_samples,
                "threshold": threshold,
                "context": context,
            }
        )
        if consume_random:
            np.random.random()
        if exception is not None:
            raise exception
        return result

    monkeypatch.setattr(
        stable_pose,
        "_compute_stable_poses_cpp",
        fake_compute_stable_poses_cpp,
    )
    return calls


def test_compute_stable_poses_defaults_to_trimesh(monkeypatch):
    monkeypatch.delenv(stable_pose.STABLE_POSE_BACKEND_ENV_VAR, raising=False)
    monkeypatch.delenv(stable_pose.DISABLE_CPP_STABLE_POSE_ENV_VAR, raising=False)
    monkeypatch.delenv(stable_pose.VALIDATE_CPP_STABLE_POSE_ENV_VAR, raising=False)

    mesh = object()
    center_mass = [1.0, 2.0, 3.0]
    expected = ("poses", "probabilities")
    calls = _install_fake_trimesh(monkeypatch, expected)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("default stable pose backend should not call C++")

    monkeypatch.setattr(stable_pose, "_compute_stable_poses_cpp", fail_if_called)

    result = stable_pose.compute_stable_poses(
        mesh,
        center_mass=center_mass,
        sigma=0.25,
        n_samples=7,
        threshold=0.5,
        context="unit-test",
    )

    assert result == expected
    assert calls == [
        {
            "mesh": mesh,
            "center_mass": center_mass,
            "sigma": 0.25,
            "n_samples": 7,
            "threshold": 0.5,
        }
    ]


def test_default_backend_propagates_trimesh_exceptions(monkeypatch):
    monkeypatch.delenv(stable_pose.STABLE_POSE_BACKEND_ENV_VAR, raising=False)
    monkeypatch.delenv(stable_pose.DISABLE_CPP_STABLE_POSE_ENV_VAR, raising=False)
    monkeypatch.delenv(stable_pose.VALIDATE_CPP_STABLE_POSE_ENV_VAR, raising=False)

    def raise_from_trimesh(*args, **kwargs):
        raise RuntimeError("trimesh failed")

    monkeypatch.setattr(
        stable_pose.trimesh.poses,
        "compute_stable_poses",
        raise_from_trimesh,
    )

    with pytest.raises(RuntimeError, match="trimesh failed"):
        stable_pose.compute_stable_poses(object())


def test_cpp_backend_skeleton_falls_back_to_trimesh(monkeypatch):
    monkeypatch.setenv(stable_pose.STABLE_POSE_BACKEND_ENV_VAR, "cpp")
    monkeypatch.delenv(stable_pose.DISABLE_CPP_STABLE_POSE_ENV_VAR, raising=False)
    monkeypatch.delenv(stable_pose.VALIDATE_CPP_STABLE_POSE_ENV_VAR, raising=False)

    mesh = object()
    expected = ("trimesh-poses", "trimesh-probs")
    trimesh_calls = _install_fake_trimesh(monkeypatch, expected)
    cpp_calls = _install_fake_cpp(
        monkeypatch,
        exception=NotImplementedError(
            "C++ stable pose backend skeleton is not implemented"
        ),
    )

    result = stable_pose.compute_stable_poses(
        mesh,
        center_mass=[0.0, 0.0, 0.0],
        sigma=0.1,
        n_samples=3,
        threshold=0.2,
        context="cpp-test",
    )

    assert result == expected
    assert cpp_calls == [
        {
            "mesh": mesh,
            "center_mass": [0.0, 0.0, 0.0],
            "sigma": 0.1,
            "n_samples": 3,
            "threshold": 0.2,
            "context": "cpp-test",
        }
    ]
    assert len(trimesh_calls) == 1


def test_auto_backend_falls_back_to_trimesh(monkeypatch):
    monkeypatch.setenv(stable_pose.STABLE_POSE_BACKEND_ENV_VAR, "auto")
    monkeypatch.delenv(stable_pose.DISABLE_CPP_STABLE_POSE_ENV_VAR, raising=False)
    monkeypatch.delenv(stable_pose.VALIDATE_CPP_STABLE_POSE_ENV_VAR, raising=False)

    expected = ("trimesh-poses", "trimesh-probs")
    _install_fake_trimesh(monkeypatch, expected)
    _install_fake_cpp(monkeypatch, exception=RuntimeError("extension unavailable"))

    result = stable_pose.compute_stable_poses(object(), context="auto-test")

    assert result == expected


def test_disable_cpp_stable_pose_skips_cpp_backend(monkeypatch):
    monkeypatch.setenv(stable_pose.STABLE_POSE_BACKEND_ENV_VAR, "cpp")
    monkeypatch.setenv(stable_pose.DISABLE_CPP_STABLE_POSE_ENV_VAR, "1")
    monkeypatch.delenv(stable_pose.VALIDATE_CPP_STABLE_POSE_ENV_VAR, raising=False)

    expected = ("trimesh-poses", "trimesh-probs")
    trimesh_calls = _install_fake_trimesh(monkeypatch, expected)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("C++ stable pose backend should be disabled")

    monkeypatch.setattr(stable_pose, "_compute_stable_poses_cpp", fail_if_called)

    result = stable_pose.compute_stable_poses(object(), context="disabled-test")

    assert result == expected
    assert len(trimesh_calls) == 1


def test_canary_success_returns_cpp_result(monkeypatch):
    monkeypatch.setenv(stable_pose.STABLE_POSE_BACKEND_ENV_VAR, "cpp")
    monkeypatch.setenv(stable_pose.VALIDATE_CPP_STABLE_POSE_ENV_VAR, "1")
    monkeypatch.delenv(stable_pose.DISABLE_CPP_STABLE_POSE_ENV_VAR, raising=False)

    cpp_result = _stable_pose_result()
    trimesh_result = _stable_pose_result()
    trimesh_calls = _install_fake_trimesh(monkeypatch, trimesh_result)
    cpp_calls = _install_fake_cpp(monkeypatch, result=cpp_result)

    result = stable_pose.compute_stable_poses(object(), context="canary-success")

    assert result is cpp_result
    assert len(cpp_calls) == 1
    assert len(trimesh_calls) == 1


def test_canary_failure_falls_back_to_trimesh_result(monkeypatch):
    monkeypatch.setenv(stable_pose.STABLE_POSE_BACKEND_ENV_VAR, "cpp")
    monkeypatch.setenv(stable_pose.VALIDATE_CPP_STABLE_POSE_ENV_VAR, "1")
    monkeypatch.delenv(stable_pose.DISABLE_CPP_STABLE_POSE_ENV_VAR, raising=False)

    cpp_result = _stable_pose_result()
    rotation = np.array(
        [
            [0.0, -1.0, 0.0],
            [1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0],
        ]
    )
    trimesh_result = _stable_pose_result(rotation=rotation)
    trimesh_calls = _install_fake_trimesh(monkeypatch, trimesh_result)
    _install_fake_cpp(monkeypatch, result=cpp_result)

    result = stable_pose.compute_stable_poses(object(), context="canary-fail")

    assert result is trimesh_result
    assert len(trimesh_calls) == 1


@pytest.mark.parametrize(
    "cpp_result",
    [
        (np.array([np.full((4, 4), np.nan)]), np.array([1.0])),
        (np.array([np.eye(3)]), np.array([1.0])),
        (np.empty((0, 4, 4)), np.array([])),
        (
            np.array(
                [
                    [
                        [2.0, 0.0, 0.0, 0.0],
                        [0.0, 1.0, 0.0, 0.0],
                        [0.0, 0.0, 1.0, 0.0],
                        [0.0, 0.0, 0.0, 1.0],
                    ]
                ]
            ),
            np.array([1.0]),
        ),
    ],
)
def test_invalid_cpp_result_falls_back_to_trimesh(monkeypatch, cpp_result):
    monkeypatch.setenv(stable_pose.STABLE_POSE_BACKEND_ENV_VAR, "cpp")
    monkeypatch.delenv(stable_pose.VALIDATE_CPP_STABLE_POSE_ENV_VAR, raising=False)
    monkeypatch.delenv(stable_pose.DISABLE_CPP_STABLE_POSE_ENV_VAR, raising=False)

    trimesh_result = _stable_pose_result()
    _install_fake_cpp(monkeypatch, result=cpp_result)
    trimesh_calls = _install_fake_trimesh(monkeypatch, trimesh_result)

    result = stable_pose.compute_stable_poses(object(), context="invalid-cpp")

    assert result is trimesh_result
    assert len(trimesh_calls) == 1


def test_canary_success_rng_state_matches_one_trimesh_run(monkeypatch):
    monkeypatch.setenv(stable_pose.STABLE_POSE_BACKEND_ENV_VAR, "cpp")
    monkeypatch.setenv(stable_pose.VALIDATE_CPP_STABLE_POSE_ENV_VAR, "1")
    monkeypatch.delenv(stable_pose.DISABLE_CPP_STABLE_POSE_ENV_VAR, raising=False)

    cpp_result = _stable_pose_result()
    trimesh_result = _stable_pose_result()
    _install_fake_cpp(monkeypatch, result=cpp_result)
    _install_fake_trimesh(monkeypatch, trimesh_result, consume_random=True)

    np.random.seed(1234)
    state_before = np.random.get_state()
    stable_pose.compute_stable_poses(object(), context="rng-canary-success")
    actual_state = np.random.get_state()

    np.random.set_state(state_before)
    np.random.random()
    expected_one_trimesh_state = np.random.get_state()

    np.random.set_state(state_before)
    np.random.random()
    np.random.random()
    unexpected_two_trimesh_state = np.random.get_state()

    assert _rng_state_equal(actual_state, expected_one_trimesh_state)
    assert not _rng_state_equal(actual_state, unexpected_two_trimesh_state)


def test_cpp_failure_rng_state_matches_one_trimesh_run(monkeypatch):
    monkeypatch.setenv(stable_pose.STABLE_POSE_BACKEND_ENV_VAR, "cpp")
    monkeypatch.delenv(stable_pose.VALIDATE_CPP_STABLE_POSE_ENV_VAR, raising=False)
    monkeypatch.delenv(stable_pose.DISABLE_CPP_STABLE_POSE_ENV_VAR, raising=False)

    trimesh_result = _stable_pose_result()
    _install_fake_cpp(
        monkeypatch,
        exception=stable_pose.StablePoseBackendError("backend failed"),
        consume_random=True,
    )
    _install_fake_trimesh(monkeypatch, trimesh_result, consume_random=True)

    np.random.seed(4321)
    state_before = np.random.get_state()
    stable_pose.compute_stable_poses(object(), context="rng-cpp-fail")
    actual_state = np.random.get_state()

    np.random.set_state(state_before)
    np.random.random()
    expected_one_trimesh_state = np.random.get_state()

    np.random.set_state(state_before)
    np.random.random()
    np.random.random()
    unexpected_two_trimesh_state = np.random.get_state()

    assert _rng_state_equal(actual_state, expected_one_trimesh_state)
    assert not _rng_state_equal(actual_state, unexpected_two_trimesh_state)


def test_no_direct_trimesh_stable_pose_calls_outside_wrapper():
    repo_root = Path(__file__).resolve().parents[1]
    offenders = []

    for root_name in SCAN_ROOTS:
        for path in (repo_root / root_name).rglob("*"):
            relative_path = path.relative_to(repo_root)
            if not path.is_file():
                continue
            if any(part in SKIPPED_PATH_PARTS for part in relative_path.parts):
                continue
            if path.suffix.lower() in SKIPPED_SUFFIXES:
                continue
            if relative_path in ALLOWED_DIRECT_CALL_PATHS:
                continue

            text = path.read_text(encoding="utf-8", errors="ignore")
            if DIRECT_STABLE_POSE_CALL in text:
                offenders.append(str(relative_path))

    assert offenders == []
