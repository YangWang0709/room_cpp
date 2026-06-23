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


def test_compute_stable_poses_forwards_to_trimesh(monkeypatch):
    mesh = object()
    center_mass = [1.0, 2.0, 3.0]
    expected = ("poses", "probabilities")
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
            if relative_path in ALLOWED_DIRECT_CALL_PATHS:
                continue

            text = path.read_text(encoding="utf-8", errors="ignore")
            if DIRECT_STABLE_POSE_CALL in text:
                offenders.append(str(relative_path))

    assert offenders == []
