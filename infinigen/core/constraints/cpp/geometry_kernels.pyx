# cython: boundscheck=False, wraparound=False, initializedcheck=False, cdivision=True, language_level=3
"""Cython/C++ pure numeric geometry kernels.

This module intentionally avoids Blender, gin, solver code, and random number
generation. Boundary contact is treated as inclusive overlap/containment.
"""

import numpy as np
cimport numpy as cnp

cnp.import_array()

cdef object _NP_FLOAT32 = np.dtype(np.float32)
cdef object _NP_FLOAT64 = np.dtype(np.float64)


cdef object _as_2d3(str name, object value):
    cdef object arr = np.asarray(value)
    if arr.ndim != 2 or arr.shape[1] != 3:
        raise ValueError(f"{name} must have shape [N, 3], got {arr.shape}")
    if arr.shape[0] == 0:
        raise ValueError(f"{name} must contain at least one row")
    if arr.dtype != _NP_FLOAT32 and arr.dtype != _NP_FLOAT64:
        raise TypeError(f"{name} must have dtype float32 or float64, got {arr.dtype}")
    return arr


cdef object _as_1d3(str name, object value):
    cdef object arr = np.asarray(value)
    if arr.shape != (3,):
        raise ValueError(f"{name} must have shape [3], got {arr.shape}")
    if arr.dtype != _NP_FLOAT32 and arr.dtype != _NP_FLOAT64:
        raise TypeError(f"{name} must have dtype float32 or float64, got {arr.dtype}")
    return arr


cdef object _promoted_dtype(tuple arrays):
    cdef object dtype = np.dtype(np.result_type(*[arr.dtype for arr in arrays]))
    if dtype != _NP_FLOAT32 and dtype != _NP_FLOAT64:
        raise TypeError(
            "inputs must have dtype float32 or float64, got "
            + ", ".join(str(arr.dtype) for arr in arrays)
        )
    return dtype


cdef tuple _bbox_min_max_f64(double[:, ::1] points):
    cdef Py_ssize_t n = points.shape[0]
    cdef Py_ssize_t i
    cdef double min0 = points[0, 0]
    cdef double min1 = points[0, 1]
    cdef double min2 = points[0, 2]
    cdef double max0 = min0
    cdef double max1 = min1
    cdef double max2 = min2
    cdef double v0, v1, v2
    cdef cnp.ndarray[cnp.float64_t, ndim=1] mins
    cdef cnp.ndarray[cnp.float64_t, ndim=1] maxs

    for i in range(1, n):
        v0 = points[i, 0]
        v1 = points[i, 1]
        v2 = points[i, 2]
        if v0 < min0:
            min0 = v0
        elif v0 > max0:
            max0 = v0
        if v1 < min1:
            min1 = v1
        elif v1 > max1:
            max1 = v1
        if v2 < min2:
            min2 = v2
        elif v2 > max2:
            max2 = v2

    mins = np.empty(3, dtype=np.float64)
    maxs = np.empty(3, dtype=np.float64)
    mins[0] = min0
    mins[1] = min1
    mins[2] = min2
    maxs[0] = max0
    maxs[1] = max1
    maxs[2] = max2
    return mins, maxs


cdef tuple _bbox_min_max_f32(float[:, ::1] points):
    cdef Py_ssize_t n = points.shape[0]
    cdef Py_ssize_t i
    cdef float min0 = points[0, 0]
    cdef float min1 = points[0, 1]
    cdef float min2 = points[0, 2]
    cdef float max0 = min0
    cdef float max1 = min1
    cdef float max2 = min2
    cdef float v0, v1, v2
    cdef cnp.ndarray[cnp.float32_t, ndim=1] mins
    cdef cnp.ndarray[cnp.float32_t, ndim=1] maxs

    for i in range(1, n):
        v0 = points[i, 0]
        v1 = points[i, 1]
        v2 = points[i, 2]
        if v0 < min0:
            min0 = v0
        elif v0 > max0:
            max0 = v0
        if v1 < min1:
            min1 = v1
        elif v1 > max1:
            max1 = v1
        if v2 < min2:
            min2 = v2
        elif v2 > max2:
            max2 = v2

    mins = np.empty(3, dtype=np.float32)
    maxs = np.empty(3, dtype=np.float32)
    mins[0] = min0
    mins[1] = min1
    mins[2] = min2
    maxs[0] = max0
    maxs[1] = max1
    maxs[2] = max2
    return mins, maxs


def bbox_min_max(object points):
    """Return coordinate-wise min and max for points shaped [N, 3]."""
    cdef object points_arr = _as_2d3("points", points)
    cdef object dtype = _promoted_dtype((points_arr,))
    points_arr = np.ascontiguousarray(points_arr, dtype=dtype)
    if dtype == _NP_FLOAT64:
        return _bbox_min_max_f64(points_arr)
    return _bbox_min_max_f32(points_arr)


cdef tuple _bbox_union_f64(double[:, ::1] mins_in, double[:, ::1] maxs_in):
    cdef Py_ssize_t n = mins_in.shape[0]
    cdef Py_ssize_t i
    cdef double min0 = mins_in[0, 0]
    cdef double min1 = mins_in[0, 1]
    cdef double min2 = mins_in[0, 2]
    cdef double max0 = maxs_in[0, 0]
    cdef double max1 = maxs_in[0, 1]
    cdef double max2 = maxs_in[0, 2]
    cdef double v0, v1, v2
    cdef cnp.ndarray[cnp.float64_t, ndim=1] out_min
    cdef cnp.ndarray[cnp.float64_t, ndim=1] out_max

    for i in range(1, n):
        v0 = mins_in[i, 0]
        v1 = mins_in[i, 1]
        v2 = mins_in[i, 2]
        if v0 < min0:
            min0 = v0
        if v1 < min1:
            min1 = v1
        if v2 < min2:
            min2 = v2
        v0 = maxs_in[i, 0]
        v1 = maxs_in[i, 1]
        v2 = maxs_in[i, 2]
        if v0 > max0:
            max0 = v0
        if v1 > max1:
            max1 = v1
        if v2 > max2:
            max2 = v2

    out_min = np.empty(3, dtype=np.float64)
    out_max = np.empty(3, dtype=np.float64)
    out_min[0] = min0
    out_min[1] = min1
    out_min[2] = min2
    out_max[0] = max0
    out_max[1] = max1
    out_max[2] = max2
    return out_min, out_max


cdef tuple _bbox_union_f32(float[:, ::1] mins_in, float[:, ::1] maxs_in):
    cdef Py_ssize_t n = mins_in.shape[0]
    cdef Py_ssize_t i
    cdef float min0 = mins_in[0, 0]
    cdef float min1 = mins_in[0, 1]
    cdef float min2 = mins_in[0, 2]
    cdef float max0 = maxs_in[0, 0]
    cdef float max1 = maxs_in[0, 1]
    cdef float max2 = maxs_in[0, 2]
    cdef float v0, v1, v2
    cdef cnp.ndarray[cnp.float32_t, ndim=1] out_min
    cdef cnp.ndarray[cnp.float32_t, ndim=1] out_max

    for i in range(1, n):
        v0 = mins_in[i, 0]
        v1 = mins_in[i, 1]
        v2 = mins_in[i, 2]
        if v0 < min0:
            min0 = v0
        if v1 < min1:
            min1 = v1
        if v2 < min2:
            min2 = v2
        v0 = maxs_in[i, 0]
        v1 = maxs_in[i, 1]
        v2 = maxs_in[i, 2]
        if v0 > max0:
            max0 = v0
        if v1 > max1:
            max1 = v1
        if v2 > max2:
            max2 = v2

    out_min = np.empty(3, dtype=np.float32)
    out_max = np.empty(3, dtype=np.float32)
    out_min[0] = min0
    out_min[1] = min1
    out_min[2] = min2
    out_max[0] = max0
    out_max[1] = max1
    out_max[2] = max2
    return out_min, out_max


def bbox_union(object mins, object maxs):
    """Return the union min/max for bbox corner arrays shaped [N, 3]."""
    cdef object mins_arr = _as_2d3("mins", mins)
    cdef object maxs_arr = _as_2d3("maxs", maxs)
    cdef object dtype
    if mins_arr.shape != maxs_arr.shape:
        raise ValueError(
            f"mins and maxs must have the same shape, got {mins_arr.shape} "
            f"and {maxs_arr.shape}"
        )
    dtype = _promoted_dtype((mins_arr, maxs_arr))
    mins_arr = np.ascontiguousarray(mins_arr, dtype=dtype)
    maxs_arr = np.ascontiguousarray(maxs_arr, dtype=dtype)
    if dtype == _NP_FLOAT64:
        return _bbox_union_f64(mins_arr, maxs_arr)
    return _bbox_union_f32(mins_arr, maxs_arr)


cdef cnp.ndarray _aabb_overlap_matrix_f64(
    double[:, ::1] mins_a,
    double[:, ::1] maxs_a,
    double[:, ::1] mins_b,
    double[:, ::1] maxs_b,
):
    cdef Py_ssize_t a_count = mins_a.shape[0]
    cdef Py_ssize_t b_count = mins_b.shape[0]
    cdef Py_ssize_t i, j
    cdef cnp.ndarray[cnp.npy_bool, ndim=2] out = np.empty(
        (a_count, b_count), dtype=np.bool_
    )

    for i in range(a_count):
        for j in range(b_count):
            out[i, j] = (
                maxs_a[i, 0] >= mins_b[j, 0]
                and maxs_b[j, 0] >= mins_a[i, 0]
                and maxs_a[i, 1] >= mins_b[j, 1]
                and maxs_b[j, 1] >= mins_a[i, 1]
                and maxs_a[i, 2] >= mins_b[j, 2]
                and maxs_b[j, 2] >= mins_a[i, 2]
            )
    return out


cdef cnp.ndarray _aabb_overlap_matrix_f32(
    float[:, ::1] mins_a,
    float[:, ::1] maxs_a,
    float[:, ::1] mins_b,
    float[:, ::1] maxs_b,
):
    cdef Py_ssize_t a_count = mins_a.shape[0]
    cdef Py_ssize_t b_count = mins_b.shape[0]
    cdef Py_ssize_t i, j
    cdef cnp.ndarray[cnp.npy_bool, ndim=2] out = np.empty(
        (a_count, b_count), dtype=np.bool_
    )

    for i in range(a_count):
        for j in range(b_count):
            out[i, j] = (
                maxs_a[i, 0] >= mins_b[j, 0]
                and maxs_b[j, 0] >= mins_a[i, 0]
                and maxs_a[i, 1] >= mins_b[j, 1]
                and maxs_b[j, 1] >= mins_a[i, 1]
                and maxs_a[i, 2] >= mins_b[j, 2]
                and maxs_b[j, 2] >= mins_a[i, 2]
            )
    return out


def aabb_overlap_matrix(object mins_a, object maxs_a, object mins_b, object maxs_b):
    """Return inclusive AABB overlap matrix shaped [A, B]."""
    cdef object mins_a_arr = _as_2d3("mins_a", mins_a)
    cdef object maxs_a_arr = _as_2d3("maxs_a", maxs_a)
    cdef object mins_b_arr = _as_2d3("mins_b", mins_b)
    cdef object maxs_b_arr = _as_2d3("maxs_b", maxs_b)
    cdef object dtype
    if mins_a_arr.shape != maxs_a_arr.shape:
        raise ValueError(
            f"mins_a and maxs_a must have the same shape, got "
            f"{mins_a_arr.shape} and {maxs_a_arr.shape}"
        )
    if mins_b_arr.shape != maxs_b_arr.shape:
        raise ValueError(
            f"mins_b and maxs_b must have the same shape, got "
            f"{mins_b_arr.shape} and {maxs_b_arr.shape}"
        )
    dtype = _promoted_dtype((mins_a_arr, maxs_a_arr, mins_b_arr, maxs_b_arr))
    mins_a_arr = np.ascontiguousarray(mins_a_arr, dtype=dtype)
    maxs_a_arr = np.ascontiguousarray(maxs_a_arr, dtype=dtype)
    mins_b_arr = np.ascontiguousarray(mins_b_arr, dtype=dtype)
    maxs_b_arr = np.ascontiguousarray(maxs_b_arr, dtype=dtype)
    if dtype == _NP_FLOAT64:
        return _aabb_overlap_matrix_f64(
            mins_a_arr, maxs_a_arr, mins_b_arr, maxs_b_arr
        )
    return _aabb_overlap_matrix_f32(
        mins_a_arr, maxs_a_arr, mins_b_arr, maxs_b_arr
    )


cdef bint _aabb_contains_f64(
    double[::1] outer_min,
    double[::1] outer_max,
    double[::1] inner_min,
    double[::1] inner_max,
):
    return (
        outer_min[0] <= inner_min[0]
        and outer_min[1] <= inner_min[1]
        and outer_min[2] <= inner_min[2]
        and inner_max[0] <= outer_max[0]
        and inner_max[1] <= outer_max[1]
        and inner_max[2] <= outer_max[2]
    )


cdef bint _aabb_contains_f32(
    float[::1] outer_min,
    float[::1] outer_max,
    float[::1] inner_min,
    float[::1] inner_max,
):
    return (
        outer_min[0] <= inner_min[0]
        and outer_min[1] <= inner_min[1]
        and outer_min[2] <= inner_min[2]
        and inner_max[0] <= outer_max[0]
        and inner_max[1] <= outer_max[1]
        and inner_max[2] <= outer_max[2]
    )


def aabb_contains(
    object outer_min,
    object outer_max,
    object inner_min,
    object inner_max,
):
    """Return True when inner is fully contained in outer, inclusively."""
    cdef object outer_min_arr = _as_1d3("outer_min", outer_min)
    cdef object outer_max_arr = _as_1d3("outer_max", outer_max)
    cdef object inner_min_arr = _as_1d3("inner_min", inner_min)
    cdef object inner_max_arr = _as_1d3("inner_max", inner_max)
    cdef object dtype
    dtype = _promoted_dtype(
        (outer_min_arr, outer_max_arr, inner_min_arr, inner_max_arr)
    )
    outer_min_arr = np.ascontiguousarray(outer_min_arr, dtype=dtype)
    outer_max_arr = np.ascontiguousarray(outer_max_arr, dtype=dtype)
    inner_min_arr = np.ascontiguousarray(inner_min_arr, dtype=dtype)
    inner_max_arr = np.ascontiguousarray(inner_max_arr, dtype=dtype)
    if dtype == _NP_FLOAT64:
        return bool(
            _aabb_contains_f64(
                outer_min_arr, outer_max_arr, inner_min_arr, inner_max_arr
            )
        )
    return bool(
        _aabb_contains_f32(
            outer_min_arr, outer_max_arr, inner_min_arr, inner_max_arr
        )
    )
