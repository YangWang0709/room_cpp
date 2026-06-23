import pytest

from infinigen.core.constraints.cpp import stable_pose_kernels


def test_cpp_backend_available_returns_bool():
    assert stable_pose_kernels.cpp_backend_available() in (True, False)


def test_stable_pose_kernels_extension_smoke():
    if stable_pose_kernels.cpp_backend_available():
        assert stable_pose_kernels.backend_name() == "stable_pose_kernels_cpp"
        assert stable_pose_kernels.sanity_check() is True
    else:
        assert stable_pose_kernels.backend_name() is None
        assert stable_pose_kernels.sanity_check() is False


def test_compute_stable_poses_cpp_is_skeleton_only():
    expected_error = (
        NotImplementedError
        if stable_pose_kernels.cpp_backend_available()
        else RuntimeError
    )

    with pytest.raises(expected_error):
        stable_pose_kernels.compute_stable_poses_cpp(object())
