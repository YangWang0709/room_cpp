# Copyright (C) 2023, Princeton University.
# This source code is licensed under the BSD 3-Clause license found in the LICENSE file in the root directory of this source tree.

# Authors: Stamatis Alexandropulos


import csv
import hashlib
import logging
import os
import sys
import time
from pathlib import Path

import bpy
import mathutils
import numpy as np
import trimesh

from infinigen.assets.objects import corals, creatures, mollusk, monocot, rocks
from infinigen.assets.utils import object as obj
from infinigen.assets.utils.object import join_objects
from infinigen.core.placement.factory import AssetFactory
from infinigen.core.util import blender as butil
from infinigen.core.util.math import FixedSeed
from infinigen.core.util.stable_pose import compute_stable_poses

logger = logging.getLogger(__name__)

NATURE_SHELF_TRINKETS_TIMING_ENV_VAR = "INFINIGEN_PROFILE_NATURE_SHELF_TRINKETS"
NATURE_SHELF_TRINKETS_TIMING_CSV_ENV_VAR = (
    "INFINIGEN_NATURE_SHELF_TRINKETS_TIMING_CSV"
)
FAST_NATURE_TRINKET_STABLE_POSE_ENV_VAR = (
    "INFINIGEN_FAST_NATURE_TRINKET_STABLE_POSE"
)
NATURE_SHELF_TRINKETS_TIMING_CSV_NAME = (
    "infinigen_nature_shelf_trinkets_timing.csv"
)
DEFAULT_NATURE_SHELF_TRINKETS_TIMING_CSV = (
    Path("/tmp") / NATURE_SHELF_TRINKETS_TIMING_CSV_NAME
)

NATURE_SHELF_TRINKETS_TIMING_FIELDNAMES = [
    "factory_class",
    "base_factory_class",
    "factory_seed",
    "inst_seed",
    "base_inst_seed",
    "placeholder_name",
    "create_asset_total_duration",
    "base_factory_spawn_duration",
    "join_children_duration",
    "apply_initial_transform_duration",
    "apply_modifiers_duration",
    "obj2trimesh_duration",
    "stable_pose_duration",
    "fast_stable_pose_duration",
    "apply_rotation_transform_duration",
    "scale_and_position_duration",
    "apply_final_location_transform_duration",
    "fast_stable_pose_enabled",
    "fast_stable_pose_used",
    "stable_pose_mode",
    "skipped_compute_stable_poses",
    "mesh_vertex_count",
    "mesh_face_count",
    "mesh_edge_count",
    "bbox_min_x",
    "bbox_min_y",
    "bbox_min_z",
    "bbox_max_x",
    "bbox_max_y",
    "bbox_max_z",
    "bbox_extent_x",
    "bbox_extent_y",
    "bbox_extent_z",
    "stable_pose_count",
    "stable_pose_best_prob",
    "stable_pose_cache_candidate_key",
    "material_count_before",
    "material_count_after",
    "texture_count_before",
    "texture_count_after",
    "node_group_count_before",
    "node_group_count_after",
    "mesh_count_before",
    "mesh_count_after",
    "object_count_before",
    "object_count_after",
    "created_material_count",
    "created_texture_count",
    "created_node_group_count",
    "created_mesh_count",
    "created_object_count",
    "asset_children_before_join",
    "asset_tree_object_count_after_spawn",
    "final_asset_name",
    "final_asset_type",
    "final_asset_mesh_name",
    "final_asset_child_count",
    "created_material_names",
    "created_texture_names",
    "created_node_group_names",
    "success",
    "error_type",
]

_NATURE_SHELF_TRINKETS_TIMING_WRITE_FAILED = False


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _profile_nature_shelf_trinkets_enabled() -> bool:
    return _env_truthy(NATURE_SHELF_TRINKETS_TIMING_ENV_VAR)


def _fast_nature_trinket_stable_pose_enabled() -> bool:
    return _env_truthy(FAST_NATURE_TRINKET_STABLE_POSE_ENV_VAR)


def _nature_shelf_trinkets_timing_csv_path() -> Path:
    explicit_path = os.environ.get(NATURE_SHELF_TRINKETS_TIMING_CSV_ENV_VAR)
    if explicit_path:
        return Path(explicit_path)

    solver_timing = sys.modules.get("infinigen.core.constraints.example_solver.timing")
    if solver_timing is not None:
        current_output_folder = getattr(solver_timing, "current_output_folder", None)
        if current_output_folder is not None:
            output_folder = current_output_folder()
            if output_folder is not None:
                return Path(output_folder) / NATURE_SHELF_TRINKETS_TIMING_CSV_NAME
    return DEFAULT_NATURE_SHELF_TRINKETS_TIMING_CSV


def _write_nature_shelf_trinkets_timing_row(row: dict):
    global _NATURE_SHELF_TRINKETS_TIMING_WRITE_FAILED

    if _NATURE_SHELF_TRINKETS_TIMING_WRITE_FAILED:
        return

    path = _nature_shelf_trinkets_timing_csv_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        write_header = not path.exists() or path.stat().st_size == 0
        with path.open("a", newline="") as handle:
            writer = csv.DictWriter(
                handle, fieldnames=NATURE_SHELF_TRINKETS_TIMING_FIELDNAMES
            )
            if write_header:
                writer.writeheader()
            writer.writerow(
                {
                    field: row.get(field, "")
                    for field in NATURE_SHELF_TRINKETS_TIMING_FIELDNAMES
                }
            )
    except OSError:
        _NATURE_SHELF_TRINKETS_TIMING_WRITE_FAILED = True
        logger.exception(
            "Failed to write NatureShelfTrinkets timing CSV at %s", path
        )


def _bpy_datablock_name_sets() -> dict[str, set[str]]:
    return {
        "material": set(bpy.data.materials.keys()),
        "texture": set(bpy.data.textures.keys()),
        "node_group": set(bpy.data.node_groups.keys()),
        "mesh": set(bpy.data.meshes.keys()),
        "object": set(bpy.data.objects.keys()),
    }


def _record_duration(row: dict, field: str, start_time: float):
    row[field] = row.get(field, 0.0) + time.perf_counter() - start_time


def _placeholder_name(placeholder) -> str:
    return "" if placeholder is None else getattr(placeholder, "name", "")


def _object_tree_count(asset):
    try:
        return len(list(butil.iter_object_tree(asset)))
    except Exception:
        return ""


def _is_creature_base_factory(base_factory) -> bool:
    return isinstance(
        base_factory,
        (creatures.HerbivoreFactory, creatures.CarnivoreFactory),
    )


def _fast_stable_pose_allowed(base_factory) -> bool:
    return isinstance(
        base_factory,
        (
            mollusk.ClamFactory,
            mollusk.MusselFactory,
            mollusk.ScallopFactory,
            mollusk.ConchFactory,
            mollusk.AugerFactory,
            mollusk.VoluteFactory,
            mollusk.MolluskFactory,
        ),
    )


def _mesh_digest(mesh: trimesh.Trimesh) -> str:
    digest = hashlib.blake2b(digest_size=12)
    vertices = np.ascontiguousarray(np.asarray(mesh.vertices))
    faces = np.ascontiguousarray(np.asarray(mesh.faces))
    digest.update(str(vertices.dtype).encode("utf-8"))
    digest.update(str(vertices.shape).encode("utf-8"))
    digest.update(vertices.tobytes())
    digest.update(str(faces.dtype).encode("utf-8"))
    digest.update(str(faces.shape).encode("utf-8"))
    digest.update(faces.tobytes())
    return digest.hexdigest()


def _record_trimesh_complexity(
    row: dict, base_factory_class: str, mesh: trimesh.Trimesh
):
    vertex_count = len(mesh.vertices)
    face_count = len(mesh.faces)
    edge_count = len(mesh.edges_unique)
    row["mesh_vertex_count"] = vertex_count
    row["mesh_face_count"] = face_count
    row["mesh_edge_count"] = edge_count

    bounds = np.asarray(mesh.bounds, dtype=float)
    if bounds.shape == (2, 3):
        mins = bounds[0]
        maxs = bounds[1]
        extents = maxs - mins
        for axis, value in zip(("x", "y", "z"), mins):
            row[f"bbox_min_{axis}"] = float(value)
        for axis, value in zip(("x", "y", "z"), maxs):
            row[f"bbox_max_{axis}"] = float(value)
        for axis, value in zip(("x", "y", "z"), extents):
            row[f"bbox_extent_{axis}"] = float(value)

    extent_key = ",".join(
        f"{float(row.get(f'bbox_extent_{axis}', 0.0)):.6g}"
        for axis in ("x", "y", "z")
    )
    row["stable_pose_cache_candidate_key"] = (
        f"{base_factory_class}|v={vertex_count}|f={face_count}|e={edge_count}|"
        f"extent={extent_key}|mesh={_mesh_digest(mesh)}"
    )


def _empty_timing_row(
    factory: "NatureShelfTrinketsFactory",
    inst_seed,
    placeholder,
    before_sets: dict[str, set[str]],
) -> dict:
    row = {
        "factory_class": factory.__class__.__name__,
        "base_factory_class": factory.base_factory.__class__.__name__,
        "factory_seed": getattr(factory, "factory_seed", ""),
        "inst_seed": inst_seed,
        "base_inst_seed": "",
        "placeholder_name": _placeholder_name(placeholder),
        "create_asset_total_duration": 0.0,
        "base_factory_spawn_duration": 0.0,
        "join_children_duration": 0.0,
        "apply_initial_transform_duration": 0.0,
        "apply_modifiers_duration": 0.0,
        "obj2trimesh_duration": 0.0,
        "stable_pose_duration": 0.0,
        "fast_stable_pose_duration": 0.0,
        "apply_rotation_transform_duration": 0.0,
        "scale_and_position_duration": 0.0,
        "apply_final_location_transform_duration": 0.0,
        "fast_stable_pose_enabled": _fast_nature_trinket_stable_pose_enabled(),
        "fast_stable_pose_used": False,
        "stable_pose_mode": "original",
        "skipped_compute_stable_poses": False,
        "mesh_vertex_count": "",
        "mesh_face_count": "",
        "mesh_edge_count": "",
        "bbox_min_x": "",
        "bbox_min_y": "",
        "bbox_min_z": "",
        "bbox_max_x": "",
        "bbox_max_y": "",
        "bbox_max_z": "",
        "bbox_extent_x": "",
        "bbox_extent_y": "",
        "bbox_extent_z": "",
        "stable_pose_count": "",
        "stable_pose_best_prob": "",
        "stable_pose_cache_candidate_key": "",
        "asset_children_before_join": "",
        "asset_tree_object_count_after_spawn": "",
        "final_asset_name": "",
        "final_asset_type": "",
        "final_asset_mesh_name": "",
        "final_asset_child_count": "",
        "success": False,
        "error_type": "",
    }
    for key, names in before_sets.items():
        row[f"{key}_count_before"] = len(names)
    return row


def _finish_timing_row(row: dict, before_sets: dict[str, set[str]]):
    after_sets = _bpy_datablock_name_sets()
    for key, before_names in before_sets.items():
        after_names = after_sets[key]
        row[f"{key}_count_after"] = len(after_names)
        row[f"created_{key}_count"] = len(after_names - before_names)

    for key in ("material", "texture", "node_group"):
        created_names = sorted(after_sets[key] - before_sets[key])
        row[f"created_{key}_names"] = ";".join(created_names)

    _write_nature_shelf_trinkets_timing_row(row)


class NatureShelfTrinketsFactory(AssetFactory):
    factories = [
        corals.CoralFactory,
        rocks.BlenderRockFactory,
        rocks.BoulderFactory,
        monocot.PineconeFactory,
        mollusk.MolluskFactory,
        mollusk.AugerFactory,
        mollusk.ClamFactory,
        mollusk.ConchFactory,
        mollusk.MusselFactory,
        mollusk.ScallopFactory,
        mollusk.VoluteFactory,
        creatures.CarnivoreFactory,
        creatures.HerbivoreFactory,
    ]
    probs = np.array([1, 1, 1, 1, 3, 2, 3, 2, 2, 2, 2, 5, 5])

    def __init__(self, factory_seed, coarse=False):
        super(NatureShelfTrinketsFactory, self).__init__(factory_seed, coarse)
        with FixedSeed(self.factory_seed):
            base_factory_fn = np.random.choice(
                self.factories, p=self.probs / self.probs.sum()
            )

            kwargs = {}
            if base_factory_fn in [
                creatures.HerbivoreFactory,
                creatures.CarnivoreFactory,
            ]:
                kwargs.update({"hair": False})

            self.base_factory = base_factory_fn(self.factory_seed, **kwargs)

    def create_placeholder(self, **params) -> bpy.types.Object:
        size = np.random.uniform(0.1, 0.15)
        bpy.ops.mesh.primitive_cube_add(size=size, location=(0, 0, size / 2))
        placeholder = bpy.context.active_object
        return placeholder

    def create_asset(self, i, placeholder=None, **params):
        if _profile_nature_shelf_trinkets_enabled():
            return self._create_asset_timed(i, placeholder=placeholder, **params)

        asset = self.base_factory.spawn_asset(
            np.random.randint(1e7), distance=200, adaptive_resolution=False
        )

        if list(asset.children):
            asset = join_objects(list(asset.children))

        # butil.modify_mesh(asset, 'DECIMATE')
        butil.apply_transform(asset, loc=True)
        butil.apply_modifiers(asset)
        if _is_creature_base_factory(self.base_factory):
            pass
        elif _fast_nature_trinket_stable_pose_enabled() and _fast_stable_pose_allowed(
            self.base_factory
        ):
            pass
        else:
            if not isinstance(asset, trimesh.Trimesh):
                mesh = obj.obj2trimesh(asset)
            stable_poses, probs = compute_stable_poses(
                mesh, context="NatureShelfTrinketsFactory.create_asset"
            )
            stable_pose = stable_poses[np.argmax(probs)]
            asset.rotation_euler = mathutils.Matrix(stable_pose[:3, :3]).to_euler()
        butil.apply_transform(asset, rot=True)
        dim = asset.dimensions
        bounding_box = placeholder.dimensions
        scale = min([bounding_box[i] / dim[i] for i in range(3)])
        asset.scale = [scale for i in range(3)]
        # asset.dimensions = placeholder.dimensions
        butil.apply_transform(asset, loc=True)
        bounds = butil.bounds(asset)
        cur_loc = asset.location
        new_location = [
            cur_loc[i] - (bounds[0][i] + bounds[1][i]) / 2 for i in range(3)
        ]
        new_location[2] = cur_loc[2] - (bounds[0][2] + bounding_box[2] / 2)
        asset.location = new_location
        butil.apply_transform(asset, loc=True)
        return asset

    def _create_asset_timed(self, i, placeholder=None, **params):
        before_sets = _bpy_datablock_name_sets()
        row = _empty_timing_row(self, i, placeholder, before_sets)
        total_start_time = time.perf_counter()
        asset = None

        try:
            base_inst_seed = np.random.randint(1e7)
            row["base_inst_seed"] = base_inst_seed

            step_start_time = time.perf_counter()
            try:
                asset = self.base_factory.spawn_asset(
                    base_inst_seed, distance=200, adaptive_resolution=False
                )
            finally:
                _record_duration(row, "base_factory_spawn_duration", step_start_time)

            row["asset_tree_object_count_after_spawn"] = _object_tree_count(asset)
            row["asset_children_before_join"] = len(list(asset.children))

            if list(asset.children):
                step_start_time = time.perf_counter()
                try:
                    asset = join_objects(list(asset.children))
                finally:
                    _record_duration(row, "join_children_duration", step_start_time)

            step_start_time = time.perf_counter()
            try:
                butil.apply_transform(asset, loc=True)
            finally:
                _record_duration(
                    row, "apply_initial_transform_duration", step_start_time
                )

            step_start_time = time.perf_counter()
            try:
                butil.apply_modifiers(asset)
            finally:
                _record_duration(row, "apply_modifiers_duration", step_start_time)

            if _is_creature_base_factory(self.base_factory):
                pass
            elif (
                _fast_nature_trinket_stable_pose_enabled()
                and _fast_stable_pose_allowed(self.base_factory)
            ):
                step_start_time = time.perf_counter()
                try:
                    row["fast_stable_pose_used"] = True
                    row["stable_pose_mode"] = "fast_bbox_bottom_align"
                    row["skipped_compute_stable_poses"] = True
                finally:
                    _record_duration(
                        row, "fast_stable_pose_duration", step_start_time
                    )
            else:
                if isinstance(asset, trimesh.Trimesh):
                    mesh = asset
                else:
                    step_start_time = time.perf_counter()
                    try:
                        mesh = obj.obj2trimesh(asset)
                    finally:
                        _record_duration(row, "obj2trimesh_duration", step_start_time)

                _record_trimesh_complexity(
                    row, self.base_factory.__class__.__name__, mesh
                )

                step_start_time = time.perf_counter()
                try:
                    stable_poses, probs = compute_stable_poses(
                        mesh, context="NatureShelfTrinketsFactory._create_asset_timed"
                    )
                    row["stable_pose_count"] = len(stable_poses)
                    best_idx = np.argmax(probs)
                    row["stable_pose_best_prob"] = float(probs[best_idx])
                    stable_pose = stable_poses[best_idx]
                    asset.rotation_euler = mathutils.Matrix(
                        stable_pose[:3, :3]
                    ).to_euler()
                finally:
                    _record_duration(row, "stable_pose_duration", step_start_time)

            step_start_time = time.perf_counter()
            try:
                butil.apply_transform(asset, rot=True)
            finally:
                _record_duration(
                    row, "apply_rotation_transform_duration", step_start_time
                )

            step_start_time = time.perf_counter()
            try:
                dim = asset.dimensions
                bounding_box = placeholder.dimensions
                scale = min([bounding_box[i] / dim[i] for i in range(3)])
                asset.scale = [scale for i in range(3)]
                bounds = butil.bounds(asset)
                cur_loc = asset.location
                new_location = [
                    cur_loc[i] - (bounds[0][i] + bounds[1][i]) / 2
                    for i in range(3)
                ]
                new_location[2] = cur_loc[2] - (bounds[0][2] + bounding_box[2] / 2)
                asset.location = new_location
            finally:
                _record_duration(row, "scale_and_position_duration", step_start_time)

            step_start_time = time.perf_counter()
            try:
                butil.apply_transform(asset, loc=True)
            finally:
                _record_duration(
                    row, "apply_final_location_transform_duration", step_start_time
                )

            row["final_asset_name"] = getattr(asset, "name", "")
            row["final_asset_type"] = getattr(asset, "type", "")
            row["final_asset_mesh_name"] = getattr(
                getattr(asset, "data", None), "name", ""
            )
            row["final_asset_child_count"] = len(list(asset.children))
            row["success"] = True
            return asset
        except BaseException as exc:
            row["error_type"] = exc.__class__.__name__
            raise
        finally:
            row["create_asset_total_duration"] = (
                time.perf_counter() - total_start_time
            )
            _finish_timing_row(row, before_sets)
