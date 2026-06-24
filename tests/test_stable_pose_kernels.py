import numpy as np
import trimesh

from infinigen.core.constraints.cpp import stable_pose_kernels
from infinigen.core.util import stable_pose


def _cpp_stable_poses(mesh, *, threshold=0.0):
    inputs = stable_pose._prepare_stable_pose_inputs(
        mesh,
        sigma=0.0,
        n_samples=1,
        threshold=threshold,
    )
    return stable_pose_kernels.compute_stable_poses_cpp_from_inputs(
        vertices=inputs.vertices,
        triangles=inputs.triangles,
        face_normals=inputs.face_normals,
        triangles_center=inputs.triangles_center,
        face_adjacency=inputs.face_adjacency,
        face_adjacency_edges=inputs.face_adjacency_edges,
        sample_coms=inputs.sample_coms,
        threshold=inputs.threshold,
    )


def _assert_cpp_matches_trimesh(mesh):
    np.random.seed(0)
    trimesh_result = stable_pose._compute_stable_poses_trimesh(mesh)

    np.random.seed(0)
    cpp_result = _cpp_stable_poses(mesh)

    stable_pose._validate_stable_pose_result(*cpp_result)
    stable_pose._compare_stable_pose_results(cpp_result, trimesh_result)


def test_cpp_backend_available_returns_bool():
    assert stable_pose_kernels.cpp_backend_available() in (True, False)


def test_stable_pose_kernels_extension_smoke():
    if stable_pose_kernels.cpp_backend_available():
        assert stable_pose_kernels.backend_name() == "stable_pose_kernels_cpp"
        assert stable_pose_kernels.sanity_check() is True
    else:
        assert stable_pose_kernels.backend_name() is None
        assert stable_pose_kernels.sanity_check() is False


def test_compute_stable_poses_cpp_from_inputs_box_matches_trimesh():
    _assert_cpp_matches_trimesh(trimesh.creation.box())


def test_compute_stable_poses_cpp_from_inputs_tetrahedron_matches_trimesh():
    vertices = np.array(
        [
            [1.0, 1.0, 1.0],
            [-1.0, -1.0, 1.0],
            [-1.0, 1.0, -1.0],
            [1.0, -1.0, -1.0],
        ],
        dtype=np.float64,
    )
    faces = np.array(
        [
            [0, 2, 1],
            [0, 1, 3],
            [0, 3, 2],
            [1, 2, 3],
        ]
    )
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=True)

    _assert_cpp_matches_trimesh(mesh)


def test_compute_static_prob_matches_trimesh_reference_for_finite_cases():
    cpp = stable_pose_kernels._require_cpp()

    cases = [
        (
            np.array(
                [
                    [0.0, 0.0, 0.0],
                    [1.0, 0.0, 0.0],
                    [0.0, 1.0, 0.0],
                ],
                dtype=np.float64,
            ),
            np.array([0.25, 0.25, 1.0], dtype=np.float64),
        ),
        (
            np.array(
                [
                    [0.0, 0.0, 0.0],
                    [1.0, 0.0, 0.0],
                    [0.0, 1.0, 0.0],
                ],
                dtype=np.float64,
            ),
            np.array([0.0, 0.0, 0.0], dtype=np.float64),
        ),
        (
            np.array(
                [
                    [0.0, 0.0, 0.0],
                    [1e-8, 0.0, 0.0],
                    [0.0, 1e-8, 0.0],
                ],
                dtype=np.float64,
            ),
            np.array([0.2, 0.3, 0.4], dtype=np.float64),
        ),
    ]

    for tri, com in cases:
        expected = trimesh.poses._compute_static_prob(tri, com)
        actual = cpp._compute_static_prob(tri, com)
        if np.isfinite(expected):
            assert np.isclose(actual, expected, rtol=1e-12, atol=1e-12)
        else:
            assert actual == 0.0
