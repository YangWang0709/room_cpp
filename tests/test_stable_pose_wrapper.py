from pathlib import Path

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


def _install_fake_trimesh(monkeypatch, expected):
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
        return expected

    monkeypatch.setattr(
        stable_pose.trimesh.poses,
        "compute_stable_poses",
        fake_compute_stable_poses,
    )
    return calls


def _install_fake_cpp(monkeypatch, exception):
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
        raise exception

    monkeypatch.setattr(
        stable_pose,
        "_compute_stable_poses_cpp",
        fake_compute_stable_poses_cpp,
    )
    return calls


def test_compute_stable_poses_defaults_to_trimesh(monkeypatch):
    monkeypatch.delenv(stable_pose.STABLE_POSE_BACKEND_ENV_VAR, raising=False)
    monkeypatch.delenv(stable_pose.DISABLE_CPP_STABLE_POSE_ENV_VAR, raising=False)

    mesh = object()
    center_mass = [1.0, 2.0, 3.0]
    expected = ("poses", "probabilities")
    calls = _install_fake_trimesh(monkeypatch, expected)

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


def test_cpp_backend_skeleton_falls_back_to_trimesh(monkeypatch):
    monkeypatch.setenv(stable_pose.STABLE_POSE_BACKEND_ENV_VAR, "cpp")
    monkeypatch.delenv(stable_pose.DISABLE_CPP_STABLE_POSE_ENV_VAR, raising=False)

    mesh = object()
    expected = ("trimesh-poses", "trimesh-probs")
    trimesh_calls = _install_fake_trimesh(monkeypatch, expected)
    cpp_calls = _install_fake_cpp(
        monkeypatch,
        NotImplementedError("C++ stable pose backend skeleton is not implemented"),
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

    expected = ("trimesh-poses", "trimesh-probs")
    _install_fake_trimesh(monkeypatch, expected)
    _install_fake_cpp(monkeypatch, RuntimeError("extension unavailable"))

    result = stable_pose.compute_stable_poses(object(), context="auto-test")

    assert result == expected


def test_disable_cpp_stable_pose_skips_cpp_backend(monkeypatch):
    monkeypatch.setenv(stable_pose.STABLE_POSE_BACKEND_ENV_VAR, "cpp")
    monkeypatch.setenv(stable_pose.DISABLE_CPP_STABLE_POSE_ENV_VAR, "1")

    expected = ("trimesh-poses", "trimesh-probs")
    trimesh_calls = _install_fake_trimesh(monkeypatch, expected)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("C++ stable pose backend should be disabled")

    monkeypatch.setattr(stable_pose, "_compute_stable_poses_cpp", fail_if_called)

    result = stable_pose.compute_stable_poses(object(), context="disabled-test")

    assert result == expected
    assert len(trimesh_calls) == 1


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
