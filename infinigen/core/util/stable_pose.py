"""Global stable pose entry point for Infinigen.

The default backend is trimesh. The optional context argument is reserved for
future diagnostics and does not change behavior in this wrapper.
"""

import trimesh


def compute_stable_poses(
    mesh,
    center_mass=None,
    sigma=0.0,
    n_samples=1,
    threshold=0.0,
    *,
    context=None,
):
    """Compute stable poses using the default trimesh backend."""
    _ = context
    return trimesh.poses.compute_stable_poses(
        mesh,
        center_mass=center_mass,
        sigma=sigma,
        n_samples=n_samples,
        threshold=threshold,
    )
