"""Python wrapper for the optional Cython/C++ stable pose backend skeleton."""

from __future__ import annotations

from typing import Any

import numpy as np

try:
    from . import stable_pose_kernels_cpp as _cpp
except Exception as exc:  # pragma: no cover - exercised when extension is absent.
    _cpp = None
    C_EXTENSION_ERROR = repr(exc)
else:
    C_EXTENSION_ERROR = None

C_EXTENSION_AVAILABLE = _cpp is not None


def _float_array(value: Any) -> np.ndarray:
    return np.array(value, dtype=np.float64, order="C", copy=True)


def _index_array(value: Any) -> np.ndarray:
    return np.array(value, dtype=np.int_, order="C", copy=True)


def cpp_backend_available() -> bool:
    """Return whether the optional stable pose C++ extension imported."""
    return C_EXTENSION_AVAILABLE


def backend_name() -> str | None:
    """Return the compiled skeleton backend name, or None when unavailable."""
    if _cpp is None:
        return None
    return _cpp.backend_name()


def sanity_check() -> bool:
    """Run a minimal compiled-extension smoke check when available."""
    if _cpp is None:
        return False
    return bool(_cpp.sanity_check())


def _require_cpp() -> Any:
    if _cpp is None:
        raise RuntimeError(
            "stable_pose_kernels_cpp extension is not available; "
            f"fallback remains usable. import error: {C_EXTENSION_ERROR}"
        )
    return _cpp


def compute_stable_poses_cpp_from_inputs(
    *,
    vertices: Any,
    triangles: Any,
    face_normals: Any,
    triangles_center: Any,
    face_adjacency: Any,
    face_adjacency_edges: Any,
    sample_coms: Any,
    threshold: float,
    context: Any = None,
) -> Any:
    """Compute stable poses with the arrays-based C++/Cython backend."""
    _ = context
    cpp = _require_cpp()
    kernel = getattr(cpp, "compute_stable_poses_from_arrays", None)
    if kernel is None:
        raise RuntimeError(
            "stable_pose_kernels_cpp extension does not expose "
            "compute_stable_poses_from_arrays; rebuild the extension"
        )
    return kernel(
        _float_array(vertices),
        _float_array(triangles),
        _float_array(face_normals),
        _float_array(triangles_center),
        _index_array(face_adjacency),
        _index_array(face_adjacency_edges),
        _float_array(sample_coms),
        float(threshold),
    )


def compute_stable_poses_cpp(*args: Any, **kwargs: Any) -> Any:
    """Deprecated mesh-based skeleton entry point."""
    _require_cpp()
    raise NotImplementedError(
        "C++ stable pose backend core is not implemented yet"
    )
