"""Python wrapper for the optional Cython/C++ stable pose backend skeleton."""

from __future__ import annotations

from typing import Any

try:
    from . import stable_pose_kernels_cpp as _cpp
except Exception as exc:  # pragma: no cover - exercised when extension is absent.
    _cpp = None
    C_EXTENSION_ERROR = repr(exc)
else:
    C_EXTENSION_ERROR = None

C_EXTENSION_AVAILABLE = _cpp is not None


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


def compute_stable_poses_cpp(*args: Any, **kwargs: Any) -> Any:
    """Placeholder for the future C++ stable pose backend."""
    _require_cpp()
    raise NotImplementedError(
        "C++ stable pose backend skeleton is compiled but not implemented yet"
    )
