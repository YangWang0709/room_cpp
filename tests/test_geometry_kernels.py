import numpy as np
import pytest

from infinigen.core.constraints.cpp import geometry_kernels as kernels


def test_bbox_min_max_matches_numpy_for_float32_and_float64():
    base = np.array(
        [
            [1.0, -2.0, 3.5],
            [-4.0, 5.0, 0.25],
            [2.5, 1.0, -7.0],
        ]
    )
    for dtype in (np.float32, np.float64):
        points = base.astype(dtype)
        mins, maxs = kernels.bbox_min_max(points)
        np.testing.assert_allclose(mins, np.min(points, axis=0))
        np.testing.assert_allclose(maxs, np.max(points, axis=0))


def test_bbox_union_matches_numpy_for_float32_and_float64():
    mins_base = np.array(
        [
            [0.0, 0.0, -1.0],
            [-2.0, 1.0, 0.0],
            [1.0, -3.0, 2.0],
        ]
    )
    maxs_base = np.array(
        [
            [1.0, 2.0, 0.0],
            [-1.0, 4.0, 3.0],
            [3.0, -2.0, 5.0],
        ]
    )
    for dtype in (np.float32, np.float64):
        mins = mins_base.astype(dtype)
        maxs = maxs_base.astype(dtype)
        union_min, union_max = kernels.bbox_union(mins, maxs)
        np.testing.assert_allclose(union_min, np.min(mins, axis=0))
        np.testing.assert_allclose(union_max, np.max(maxs, axis=0))


def test_aabb_overlap_matrix_hand_cases():
    mins_a_base = np.array(
        [
            [0.0, 0.0, 0.0],
            [2.0, 2.0, 2.0],
        ]
    )
    maxs_a_base = np.array(
        [
            [1.0, 1.0, 1.0],
            [3.0, 3.0, 3.0],
        ]
    )
    mins_b_base = np.array(
        [
            [0.5, 0.5, 0.5],
            [1.0, 1.0, 1.0],
            [1.1, 0.0, 0.0],
            [3.0, 3.0, 3.0],
        ]
    )
    maxs_b_base = np.array(
        [
            [2.0, 2.0, 2.0],
            [2.0, 2.0, 2.0],
            [2.0, 1.0, 1.0],
            [4.0, 4.0, 4.0],
        ]
    )

    expected = np.array(
        [
            [True, True, False, False],
            [True, True, False, True],
        ],
        dtype=np.bool_,
    )
    for dtype in (np.float32, np.float64):
        np.testing.assert_array_equal(
            kernels.aabb_overlap_matrix(
                mins_a_base.astype(dtype),
                maxs_a_base.astype(dtype),
                mins_b_base.astype(dtype),
                maxs_b_base.astype(dtype),
            ),
            expected,
        )


def test_aabb_contains_inside_outside_and_touching_boundary():
    for dtype in (np.float32, np.float64):
        outer_min = np.array([0.0, 0.0, 0.0], dtype=dtype)
        outer_max = np.array([1.0, 1.0, 1.0], dtype=dtype)

        assert kernels.aabb_contains(
            outer_min,
            outer_max,
            np.array([0.25, 0.25, 0.25], dtype=dtype),
            np.array([0.75, 0.75, 0.75], dtype=dtype),
        )
        assert not kernels.aabb_contains(
            outer_min,
            outer_max,
            np.array([-0.1, 0.25, 0.25], dtype=dtype),
            np.array([0.75, 0.75, 0.75], dtype=dtype),
        )
        assert kernels.aabb_contains(
            outer_min,
            outer_max,
            np.array([0.0, 0.0, 0.0], dtype=dtype),
            np.array([1.0, 1.0, 1.0], dtype=dtype),
        )


def test_empty_arrays_raise_value_error():
    empty = np.empty((0, 3), dtype=np.float64)
    one_box_min = np.array([[0.0, 0.0, 0.0]], dtype=np.float64)
    one_box_max = np.array([[1.0, 1.0, 1.0]], dtype=np.float64)

    with pytest.raises(ValueError, match="at least one row"):
        kernels.bbox_min_max(empty)
    with pytest.raises(ValueError, match="at least one row"):
        kernels.bbox_union(empty, empty)
    with pytest.raises(ValueError, match="at least one row"):
        kernels.aabb_overlap_matrix(empty, empty, one_box_min, one_box_max)
    with pytest.raises(ValueError, match="at least one row"):
        kernels.aabb_overlap_matrix(one_box_min, one_box_max, empty, empty)


def test_python_fallback_and_cython_outputs_match_when_available():
    points = np.array(
        [
            [-1.0, 2.0, 0.0],
            [3.0, -4.0, 5.0],
            [0.5, 1.5, -2.5],
        ],
        dtype=np.float64,
    )
    mins = np.array(
        [[-1.0, 0.0, 0.0], [2.0, 2.0, 2.0]],
        dtype=np.float64,
    )
    maxs = np.array(
        [[1.0, 1.0, 1.0], [4.0, 4.0, 4.0]],
        dtype=np.float64,
    )

    py_min, py_max = kernels.bbox_min_max_py(points)
    py_union_min, py_union_max = kernels.bbox_union_py(mins, maxs)
    py_overlap = kernels.aabb_overlap_matrix_py(mins, maxs, mins, maxs)
    py_contains = kernels.aabb_contains_py(mins[0], maxs[0], mins[0], maxs[0])

    if not kernels.C_EXTENSION_AVAILABLE:
        assert kernels.bbox_min_max(points)[0].shape == (3,)
        assert py_overlap.dtype == np.bool_
        pytest.skip(f"Cython extension unavailable: {kernels.C_EXTENSION_ERROR}")

    cpp_min, cpp_max = kernels.bbox_min_max_cpp(points)
    cpp_union_min, cpp_union_max = kernels.bbox_union_cpp(mins, maxs)
    cpp_overlap = kernels.aabb_overlap_matrix_cpp(mins, maxs, mins, maxs)
    cpp_contains = kernels.aabb_contains_cpp(mins[0], maxs[0], mins[0], maxs[0])

    np.testing.assert_allclose(cpp_min, py_min)
    np.testing.assert_allclose(cpp_max, py_max)
    np.testing.assert_allclose(cpp_union_min, py_union_min)
    np.testing.assert_allclose(cpp_union_max, py_union_max)
    np.testing.assert_array_equal(cpp_overlap, py_overlap)
    assert cpp_contains == py_contains
