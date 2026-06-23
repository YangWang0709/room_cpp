import numpy as np
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


def test_compute_stable_poses_cpp_from_inputs_is_skeleton_only():
    with pytest.raises((NotImplementedError, RuntimeError)):
        stable_pose_kernels.compute_stable_poses_cpp_from_inputs(
            vertices=np.zeros((4, 3), dtype=np.float64),
            triangles=np.zeros((1, 3, 3), dtype=np.float64),
            face_normals=np.zeros((1, 3), dtype=np.float64),
            triangles_center=np.zeros((1, 3), dtype=np.float64),
            face_adjacency=np.zeros((0, 2), dtype=np.int64),
            face_adjacency_edges=np.zeros((0, 2), dtype=np.int64),
            sample_coms=np.zeros((1, 3), dtype=np.float64),
            threshold=0.0,
        )
