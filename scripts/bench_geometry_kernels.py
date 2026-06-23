#!/usr/bin/env python3
"""Microbenchmarks for standalone geometry kernels."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import numpy as np

from infinigen.core.constraints.cpp import geometry_kernels as kernels


def _time_call(
    func: Callable[..., Any], *args: Any, repeats: int = 5
) -> tuple[float, Any]:
    result = func(*args)
    best = float("inf")
    for _ in range(repeats):
        start = time.perf_counter()
        result = func(*args)
        best = min(best, time.perf_counter() - start)
    return best, result


def _max_abs_diff(left: Any, right: Any) -> str:
    if isinstance(left, tuple):
        diffs = [
            float(np.max(np.abs(np.asarray(a) - np.asarray(b))))
            for a, b in zip(left, right, strict=True)
        ]
        return f"{max(diffs):.3e}"
    if np.asarray(left).dtype == np.bool_ or np.asarray(right).dtype == np.bool_:
        return str(bool(np.array_equal(left, right)))
    return f"{float(np.max(np.abs(np.asarray(left) - np.asarray(right)))):.3e}"


def _print_result(
    name: str,
    size: str,
    py_time: float,
    cpp_time: float | None,
    diff: str,
) -> None:
    if cpp_time is None:
        print(
            f"{name:24s} size={size:12s} py={py_time:.6f}s "
            f"cpp=unavailable speedup=unavailable diff={diff}"
        )
        return
    speedup = py_time / cpp_time if cpp_time > 0 else float("inf")
    print(
        f"{name:24s} size={size:12s} py={py_time:.6f}s "
        f"cpp={cpp_time:.6f}s speedup={speedup:.2f}x diff={diff}"
    )


def _run_case(
    name: str,
    size: str,
    py_func: Callable[..., Any],
    cpp_func: Callable[..., Any],
    *args: Any,
) -> None:
    py_time, py_result = _time_call(py_func, *args)
    if kernels.C_EXTENSION_AVAILABLE:
        cpp_time, cpp_result = _time_call(cpp_func, *args)
        diff = _max_abs_diff(py_result, cpp_result)
    else:
        cpp_time = None
        cpp_result = py_result
        diff = _max_abs_diff(py_result, cpp_result)
    _print_result(name, size, py_time, cpp_time, diff)


def _make_boxes(rng: np.random.Generator, n: int) -> tuple[np.ndarray, np.ndarray]:
    mins = rng.normal(size=(n, 3))
    extents = rng.uniform(0.01, 2.0, size=(n, 3))
    return mins, mins + extents


def main() -> None:
    rng = np.random.default_rng(0)

    print(f"Cython extension available: {kernels.C_EXTENSION_AVAILABLE}")
    if not kernels.C_EXTENSION_AVAILABLE:
        print(f"Cython extension import error: {kernels.C_EXTENSION_ERROR}")
    print("Boundary contact policy: inclusive overlap/containment")

    for n in (1_000, 10_000, 100_000):
        points = rng.normal(size=(n, 3)).astype(np.float64)
        _run_case(
            "bbox_min_max",
            f"N={n}",
            kernels.bbox_min_max_py,
            kernels.bbox_min_max_cpp,
            points,
        )

    for n in (1_000, 10_000, 100_000):
        mins, maxs = _make_boxes(rng, n)
        _run_case(
            "bbox_union",
            f"N={n}",
            kernels.bbox_union_py,
            kernels.bbox_union_cpp,
            mins,
            maxs,
        )

    for a_count, b_count in ((100, 100), (1_000, 1_000)):
        mins_a, maxs_a = _make_boxes(rng, a_count)
        mins_b, maxs_b = _make_boxes(rng, b_count)
        _run_case(
            "aabb_overlap_matrix",
            f"{a_count}x{b_count}",
            kernels.aabb_overlap_matrix_py,
            kernels.aabb_overlap_matrix_cpp,
            mins_a,
            maxs_a,
            mins_b,
            maxs_b,
        )


if __name__ == "__main__":
    main()
