"""Pure NumPy fallback and optional Cython/C++ geometry kernels.

These helpers are standalone prototypes for numeric AABB and bbox reductions.
They do not import Blender, gin, solver code, or random number generators.

Boundary policy:
    AABB boundary contact counts as overlap and containment. This is the
    conservative broad-phase choice for future exact collision checks because a
    touching pair must not be skipped before the existing contact logic sees it.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np

_SUPPORTED_DTYPES = (np.dtype(np.float32), np.dtype(np.float64))

try:
    from . import geometry_kernels_cpp as _cpp
except Exception as exc:  # pragma: no cover - exercised when extension is absent.
    _cpp = None
    C_EXTENSION_ERROR = repr(exc)
else:
    C_EXTENSION_ERROR = None

C_EXTENSION_AVAILABLE = _cpp is not None


def _require_float_dtype(name: str, arr: np.ndarray) -> None:
    if arr.dtype not in _SUPPORTED_DTYPES:
        raise TypeError(
            f"{name} must have dtype float32 or float64, got {arr.dtype}"
        )


def _promoted_float_dtype(*arrays: np.ndarray) -> np.dtype:
    dtype = np.dtype(np.result_type(*(arr.dtype for arr in arrays)))
    if dtype not in _SUPPORTED_DTYPES:
        dtypes = ", ".join(str(arr.dtype) for arr in arrays)
        raise TypeError(f"inputs must have dtype float32 or float64, got {dtypes}")
    return dtype


def _as_points(name: str, value: Any) -> np.ndarray:
    arr = np.asarray(value)
    if arr.ndim != 2 or arr.shape[1] != 3:
        raise ValueError(f"{name} must have shape [N, 3], got {arr.shape}")
    if arr.shape[0] == 0:
        raise ValueError(f"{name} must contain at least one row")
    _require_float_dtype(name, arr)
    return arr


def _as_boxes(name: str, value: Any) -> np.ndarray:
    return _as_points(name, value)


def _as_corner(name: str, value: Any) -> np.ndarray:
    arr = np.asarray(value)
    if arr.shape != (3,):
        raise ValueError(f"{name} must have shape [3], got {arr.shape}")
    _require_float_dtype(name, arr)
    return arr


def _call_cpp(name: str, fallback: Callable, *args: Any) -> Any:
    if _cpp is None:
        return fallback(*args)
    return getattr(_cpp, name)(*args)


def _require_cpp() -> Any:
    if _cpp is None:
        raise RuntimeError(
            "geometry_kernels_cpp extension is not available; "
            f"fallback remains usable. import error: {C_EXTENSION_ERROR}"
        )
    return _cpp


def bbox_min_max_py(points: Any) -> tuple[np.ndarray, np.ndarray]:
    """Return coordinate-wise min and max for points shaped [N, 3]."""
    points_arr = _as_points("points", points)
    return np.min(points_arr, axis=0), np.max(points_arr, axis=0)


def bbox_min_max_cpp(points: Any) -> tuple[np.ndarray, np.ndarray]:
    """Call the compiled bbox_min_max kernel or raise if it is unavailable."""
    return _require_cpp().bbox_min_max(points)


def bbox_min_max(points: Any) -> tuple[np.ndarray, np.ndarray]:
    """Return coordinate-wise min and max, using Cython/C++ when available."""
    return _call_cpp("bbox_min_max", bbox_min_max_py, points)


def bbox_union_py(mins: Any, maxs: Any) -> tuple[np.ndarray, np.ndarray]:
    """Return the union min/max for bbox corner arrays shaped [N, 3]."""
    mins_arr = _as_boxes("mins", mins)
    maxs_arr = _as_boxes("maxs", maxs)
    if mins_arr.shape != maxs_arr.shape:
        raise ValueError(
            f"mins and maxs must have the same shape, got {mins_arr.shape} "
            f"and {maxs_arr.shape}"
        )
    dtype = _promoted_float_dtype(mins_arr, maxs_arr)
    mins_arr = np.asarray(mins_arr, dtype=dtype)
    maxs_arr = np.asarray(maxs_arr, dtype=dtype)
    return np.min(mins_arr, axis=0), np.max(maxs_arr, axis=0)


def bbox_union_cpp(mins: Any, maxs: Any) -> tuple[np.ndarray, np.ndarray]:
    """Call the compiled bbox_union kernel or raise if it is unavailable."""
    return _require_cpp().bbox_union(mins, maxs)


def bbox_union(mins: Any, maxs: Any) -> tuple[np.ndarray, np.ndarray]:
    """Return the union min/max, using Cython/C++ when available."""
    return _call_cpp("bbox_union", bbox_union_py, mins, maxs)


def aabb_overlap_matrix_py(
    mins_a: Any, maxs_a: Any, mins_b: Any, maxs_b: Any
) -> np.ndarray:
    """Return inclusive AABB overlap matrix shaped [A, B]."""
    mins_a_arr = _as_boxes("mins_a", mins_a)
    maxs_a_arr = _as_boxes("maxs_a", maxs_a)
    mins_b_arr = _as_boxes("mins_b", mins_b)
    maxs_b_arr = _as_boxes("maxs_b", maxs_b)
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
    dtype = _promoted_float_dtype(mins_a_arr, maxs_a_arr, mins_b_arr, maxs_b_arr)
    mins_a_arr = np.asarray(mins_a_arr, dtype=dtype)
    maxs_a_arr = np.asarray(maxs_a_arr, dtype=dtype)
    mins_b_arr = np.asarray(mins_b_arr, dtype=dtype)
    maxs_b_arr = np.asarray(maxs_b_arr, dtype=dtype)
    return np.all(
        (maxs_a_arr[:, np.newaxis, :] >= mins_b_arr[np.newaxis, :, :])
        & (maxs_b_arr[np.newaxis, :, :] >= mins_a_arr[:, np.newaxis, :]),
        axis=2,
    )


def aabb_overlap_matrix_cpp(
    mins_a: Any, maxs_a: Any, mins_b: Any, maxs_b: Any
) -> np.ndarray:
    """Call the compiled AABB overlap kernel or raise if it is unavailable."""
    return _require_cpp().aabb_overlap_matrix(mins_a, maxs_a, mins_b, maxs_b)


def aabb_overlap_matrix(
    mins_a: Any, maxs_a: Any, mins_b: Any, maxs_b: Any
) -> np.ndarray:
    """Return inclusive AABB overlap matrix, using Cython/C++ when available."""
    return _call_cpp(
        "aabb_overlap_matrix",
        aabb_overlap_matrix_py,
        mins_a,
        maxs_a,
        mins_b,
        maxs_b,
    )


def aabb_contains_py(
    outer_min: Any, outer_max: Any, inner_min: Any, inner_max: Any
) -> bool:
    """Return True when inner is fully contained in outer, inclusively."""
    outer_min_arr = _as_corner("outer_min", outer_min)
    outer_max_arr = _as_corner("outer_max", outer_max)
    inner_min_arr = _as_corner("inner_min", inner_min)
    inner_max_arr = _as_corner("inner_max", inner_max)
    dtype = _promoted_float_dtype(
        outer_min_arr, outer_max_arr, inner_min_arr, inner_max_arr
    )
    outer_min_arr = np.asarray(outer_min_arr, dtype=dtype)
    outer_max_arr = np.asarray(outer_max_arr, dtype=dtype)
    inner_min_arr = np.asarray(inner_min_arr, dtype=dtype)
    inner_max_arr = np.asarray(inner_max_arr, dtype=dtype)
    return bool(
        np.all(outer_min_arr <= inner_min_arr)
        and np.all(inner_max_arr <= outer_max_arr)
    )


def aabb_contains_cpp(
    outer_min: Any, outer_max: Any, inner_min: Any, inner_max: Any
) -> bool:
    """Call the compiled AABB containment kernel or raise if unavailable."""
    return bool(
        _require_cpp().aabb_contains(outer_min, outer_max, inner_min, inner_max)
    )


def aabb_contains(
    outer_min: Any, outer_max: Any, inner_min: Any, inner_max: Any
) -> bool:
    """Return inclusive AABB containment, using Cython/C++ when available."""
    return bool(
        _call_cpp(
            "aabb_contains",
            aabb_contains_py,
            outer_min,
            outer_max,
            inner_min,
            inner_max,
        )
    )
