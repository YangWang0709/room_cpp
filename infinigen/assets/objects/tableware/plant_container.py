# Copyright (C) 2024, Princeton University.
# This source code is licensed under the BSD 3-Clause license found in the LICENSE file in the root directory of this source tree.

# Authors: Lingjie Mei
import logging
import time
from pathlib import Path

import bpy
import numpy as np
from numpy.random import uniform

from infinigen.assets.composition import material_assignments
from infinigen.assets.objects.cactus import CactusFactory
from infinigen.assets.objects.monocot import MonocotFactory
from infinigen.assets.objects.mushroom import MushroomFactory
from infinigen.assets.objects.small_plants import (
    FernFactory,
    SnakePlantFactory,
    SpiderPlantFactory,
    SucculentFactory,
)
from infinigen.assets.objects.tableware.pot import PotFactory
from infinigen.assets.utils.decorate import (
    read_edge_center,
    read_edge_direction,
    remove_vertices,
    select_edges,
    subsurf,
)
from infinigen.assets.utils.object import join_objects, new_bbox, origin2lowest
from infinigen.core.placement.factory import AssetFactory
from infinigen.core.util import blender as butil
from infinigen.core.util.math import FixedSeed
from infinigen.core.util import profile_utils
from infinigen.core.util.random import log_uniform, weighted_sample

logger = logging.getLogger(__name__)

PLANT_ASSETS_TIMING_ENV_VAR = "INFINIGEN_PROFILE_PLANT_ASSETS"
PLANT_ASSETS_TIMING_CSV_ENV_VAR = "INFINIGEN_PLANT_ASSETS_TIMING_CSV"
PLANT_ASSETS_TIMING_CSV_NAME = "infinigen_plant_assets_timing.csv"
DEFAULT_PLANT_ASSETS_TIMING_CSV = Path("/tmp") / PLANT_ASSETS_TIMING_CSV_NAME

PLANT_ASSETS_TIMING_FIELDNAMES = [
    "factory_class",
    "factory_seed",
    "inst_seed",
    "placeholder_name",
    "plant_factory_class",
    "concrete_plant_factory_class",
    "pot_factory_class",
    "geometry_template_candidate_key",
    "geometry_reuse_risk_level",
    "plant_template_reuse_enabled",
    "plant_template_reuse_used",
    "plant_template_cache_hit",
    "plant_template_cache_miss",
    "plant_template_cache_key",
    "plant_template_cache_size",
    "plant_template_reuse_scope",
    "plant_template_fallback_count",
    "create_asset_total_duration",
    "container_spawn_duration",
    "geometry_duration",
    "material_duration",
    "pot_create_duration",
    "pot_finalize_duration",
    "dirt_geometry_duration",
    "dirt_material_duration",
    "plant_spawn_duration",
    "leaf_count",
    "stem_count",
    "branch_count",
    "leaf_mesh_count",
    "stem_mesh_count",
    "branch_mesh_count",
    "leaf_generation_duration",
    "stem_generation_duration",
    "branch_generation_duration",
    "material_generation_duration",
    "nodegroup_generation_duration",
    "modifier_apply_duration",
    "plant_finalize_duration",
    "plant_place_duration",
    "join_duration",
    "join_objects_duration",
    "mesh_count_before",
    "mesh_count_after",
    "material_count_before",
    "material_count_after",
    "texture_count_before",
    "texture_count_after",
    "node_group_count_before",
    "node_group_count_after",
    "object_count_before",
    "object_count_after",
    "image_count_before",
    "image_count_after",
    "created_mesh_count",
    "created_material_count",
    "created_texture_count",
    "created_node_group_count",
    "created_object_count",
    "created_image_count",
    "created_mesh_prefix_top",
    "created_material_prefix_top",
    "created_texture_prefix_top",
    "created_node_group_prefix_top",
    "created_object_prefix_top",
    "created_image_prefix_top",
    "success",
    "error_type",
]

_PLANT_ASSETS_TIMING_WRITE_FAILED = False


def _profile_plant_assets_enabled() -> bool:
    return profile_utils.env_truthy(PLANT_ASSETS_TIMING_ENV_VAR)


def _plant_assets_timing_csv_path() -> Path:
    return profile_utils.solver_output_csv_path(
        PLANT_ASSETS_TIMING_CSV_NAME,
        DEFAULT_PLANT_ASSETS_TIMING_CSV,
        explicit_env_var=PLANT_ASSETS_TIMING_CSV_ENV_VAR,
    )


def _write_plant_assets_timing_row(row: dict):
    global _PLANT_ASSETS_TIMING_WRITE_FAILED

    if _PLANT_ASSETS_TIMING_WRITE_FAILED:
        return

    path = _plant_assets_timing_csv_path()
    try:
        profile_utils.write_csv_row(path, PLANT_ASSETS_TIMING_FIELDNAMES, row)
    except OSError:
        _PLANT_ASSETS_TIMING_WRITE_FAILED = True
        logger.exception("Failed to write plant asset timing CSV at %s", path)


def _record_plant_duration(row: dict, field: str, start_time: float):
    row[field] = row.get(field, 0.0) + time.perf_counter() - start_time


def _concrete_plant_factory_class(factory):
    concrete_factory = getattr(factory.plant_factory, "factory", None)
    if concrete_factory is None:
        return ""
    return concrete_factory.__class__.__name__


def _geometry_template_candidate_key(factory):
    concrete_factory = getattr(factory.plant_factory, "factory", None)
    if concrete_factory is None:
        return factory.plant_factory.__class__.__name__

    method_names = []
    for method_name in ("build_leaf", "build_stem", "build_branch", "build_husk"):
        if hasattr(concrete_factory, method_name):
            method_names.append(method_name)
    nested_names = []
    for attr_name in ("branch_factory", "branches_factory", "ear_factory"):
        if hasattr(concrete_factory, attr_name):
            nested_names.append(attr_name)
    return (
        f"{concrete_factory.__class__.__name__}"
        f"|is_grass={getattr(concrete_factory, 'is_grass', False)}"
        f"|methods={','.join(method_names)}"
        f"|nested={','.join(nested_names)}"
    )


def _geometry_reuse_risk_level(factory):
    concrete_class = _concrete_plant_factory_class(factory)
    if concrete_class in {"WheatMonocotFactory", "GrassesMonocotFactory"}:
        return "medium"
    if concrete_class in {"VeratrumMonocotFactory", "AgaveMonocotFactory"}:
        return "high"
    if concrete_class in {
        "BananaMonocotFactory",
        "TaroMonocotFactory",
        "MaizeMonocotFactory",
        "TussockMonocotFactory",
    }:
        return "medium"
    return "high"


def _reset_plant_template_reuse_stats(plant_factory):
    concrete_factory = getattr(plant_factory, "factory", None)
    reset = getattr(concrete_factory, "reset_plant_template_reuse_stats", None)
    if callable(reset):
        reset()


def _record_plant_template_reuse_stats(row: dict, plant_factory):
    concrete_factory = getattr(plant_factory, "factory", None)
    if concrete_factory is None:
        return
    for field in (
        "plant_template_reuse_enabled",
        "plant_template_reuse_used",
        "plant_template_cache_hit",
        "plant_template_cache_miss",
        "plant_template_cache_key",
        "plant_template_cache_size",
        "plant_template_reuse_scope",
        "plant_template_fallback_count",
    ):
        row[field] = getattr(concrete_factory, field, row.get(field, ""))


def _empty_plant_assets_timing_row(factory, i, params, before_sets):
    row = {
        "factory_class": factory.__class__.__name__,
        "factory_seed": getattr(factory, "factory_seed", ""),
        "inst_seed": i,
        "placeholder_name": getattr(params.get("placeholder"), "name", ""),
        "plant_factory_class": factory.plant_factory.__class__.__name__,
        "concrete_plant_factory_class": _concrete_plant_factory_class(factory),
        "pot_factory_class": factory.base_factory.__class__.__name__,
        "geometry_template_candidate_key": _geometry_template_candidate_key(factory),
        "geometry_reuse_risk_level": _geometry_reuse_risk_level(factory),
        "plant_template_reuse_enabled": False,
        "plant_template_reuse_used": False,
        "plant_template_cache_hit": 0,
        "plant_template_cache_miss": 0,
        "plant_template_cache_key": "",
        "plant_template_cache_size": 0,
        "plant_template_reuse_scope": "",
        "plant_template_fallback_count": 0,
        "create_asset_total_duration": 0.0,
        "container_spawn_duration": 0.0,
        "geometry_duration": 0.0,
        "material_duration": 0.0,
        "pot_create_duration": 0.0,
        "pot_finalize_duration": 0.0,
        "dirt_geometry_duration": 0.0,
        "dirt_material_duration": 0.0,
        "plant_spawn_duration": 0.0,
        "leaf_count": 0,
        "stem_count": 0,
        "branch_count": 0,
        "leaf_mesh_count": 0,
        "stem_mesh_count": 0,
        "branch_mesh_count": 0,
        "leaf_generation_duration": 0.0,
        "stem_generation_duration": 0.0,
        "branch_generation_duration": 0.0,
        "material_generation_duration": 0.0,
        "nodegroup_generation_duration": 0.0,
        "modifier_apply_duration": 0.0,
        "plant_finalize_duration": 0.0,
        "plant_place_duration": 0.0,
        "join_duration": 0.0,
        "join_objects_duration": 0.0,
        "success": False,
        "error_type": "",
    }
    profile_utils.add_datablock_before_counts(row, before_sets)
    return row


def _finish_plant_assets_timing_row(row: dict, before_sets):
    profile_utils.add_datablock_after_counts(
        row,
        before_sets,
        include_name_samples=True,
        sample_limit=20,
        prefix_limit=50,
    )
    _write_plant_assets_timing_row(row)


def _wrap_plant_stage_method(
    row: dict,
    target,
    method_name: str,
    duration_field: str,
    count_field: str,
    mesh_count_field: str,
):
    if target is None or not hasattr(target, method_name):
        return None

    original = getattr(target, method_name)
    if not callable(original):
        return None

    def timed_method(*args, **kwargs):
        stage_start = time.perf_counter()
        mesh_names_before = set(bpy.data.meshes.keys())
        try:
            return original(*args, **kwargs)
        finally:
            mesh_names_after = set(bpy.data.meshes.keys())
            row[count_field] = row.get(count_field, 0) + 1
            row[mesh_count_field] = row.get(mesh_count_field, 0) + len(
                mesh_names_after - mesh_names_before
            )
            _record_plant_duration(row, duration_field, stage_start)

    setattr(target, method_name, timed_method)
    return target, method_name, original


def _install_plant_stage_timing(row: dict, plant_factory):
    concrete_factory = getattr(plant_factory, "factory", None)
    wrapped = []

    for method_name in ("build_leaf",):
        wrapped_item = _wrap_plant_stage_method(
            row,
            concrete_factory,
            method_name,
            "leaf_generation_duration",
            "leaf_count",
            "leaf_mesh_count",
        )
        if wrapped_item is not None:
            wrapped.append(wrapped_item)

    for method_name in ("build_stem",):
        wrapped_item = _wrap_plant_stage_method(
            row,
            concrete_factory,
            method_name,
            "stem_generation_duration",
            "stem_count",
            "stem_mesh_count",
        )
        if wrapped_item is not None:
            wrapped.append(wrapped_item)

    for method_name in ("build_branch", "build_husk"):
        wrapped_item = _wrap_plant_stage_method(
            row,
            concrete_factory,
            method_name,
            "branch_generation_duration",
            "branch_count",
            "branch_mesh_count",
        )
        if wrapped_item is not None:
            wrapped.append(wrapped_item)

    for attr_name in ("branch_factory", "branches_factory", "ear_factory"):
        nested_factory = getattr(concrete_factory, attr_name, None)
        wrapped_item = _wrap_plant_stage_method(
            row,
            nested_factory,
            "create_asset",
            "branch_generation_duration",
            "branch_count",
            "branch_mesh_count",
        )
        if wrapped_item is not None:
            wrapped.append(wrapped_item)

    return wrapped


def _restore_plant_stage_timing(wrapped):
    for target, method_name, original in reversed(wrapped):
        setattr(target, method_name, original)


class PlantPotFactory(PotFactory):
    def __init__(self, factory_seed, coarse=False):
        super(PlantPotFactory, self).__init__(factory_seed, coarse)
        with FixedSeed(self.factory_seed):
            self.has_handle = self.has_bar = self.has_guard = False
            self.depth = log_uniform(0.5, 1.0)
            self.r_expand = uniform(1.1, 1.3)
            alpha = uniform(0.5, 0.8)
            self.r_mid = (self.r_expand - 1) * alpha + 1

        self.surface = weighted_sample(material_assignments.decorative_hard)()()


class PlantContainerFactory(AssetFactory):
    plant_factories = [
        CactusFactory,
        MushroomFactory,
        FernFactory,
        SucculentFactory,
        SpiderPlantFactory,
        SnakePlantFactory,
    ]

    def __init__(self, factory_seed, coarse=False):
        super(PlantContainerFactory, self).__init__(factory_seed, coarse)
        with FixedSeed(self.factory_seed):
            self.base_factory = PlantPotFactory(self.factory_seed, coarse)

            fn = np.random.choice(self.plant_factories)

            self.dirt_ratio = uniform(0.7, 0.8)
            self.plant_factory = fn(self.factory_seed)
            self.side_size = self.base_factory.scale * self.base_factory.r_expand
            self.top_size = uniform(0.4, 0.6)

            self.dirt_surface = weighted_sample(material_assignments.potting_soil)()

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        return new_bbox(
            -self.side_size,
            self.side_size,
            -self.side_size,
            self.side_size,
            -0.02,
            self.base_factory.depth * self.base_factory.scale + self.top_size,
        )

    def create_asset(self, i, **params) -> bpy.types.Object:
        if _profile_plant_assets_enabled():
            return self._create_asset_timed(i, **params)

        obj = self.base_factory.create_asset(i=i, **params)
        horizontal = np.abs(read_edge_direction(obj)[:, -1]) < 0.1

        edge_center = read_edge_center(obj)
        z = edge_center[:, -1]
        dirt_z = self.dirt_ratio * self.base_factory.depth * self.base_factory.scale
        idx = np.argmin(np.abs(z - dirt_z) - horizontal * 10)
        radius = np.sqrt((edge_center[idx] ** 2)[:2].sum())

        selection = np.zeros_like(z).astype(bool)
        selection[idx] = True
        with butil.ViewportMode(obj, "EDIT"):
            bpy.ops.mesh.select_mode(type="EDGE")
            select_edges(obj, selection)
            bpy.ops.mesh.loop_multi_select(ring=False)
            bpy.ops.mesh.duplicate_move()
            bpy.ops.mesh.separate(type="SELECTED")

        dirt_ = bpy.context.selected_objects[-1]
        butil.select_none()
        self.base_factory.finalize_assets(obj)
        with butil.ViewportMode(dirt_, "EDIT"):
            bpy.ops.mesh.select_all(action="SELECT")
            bpy.ops.mesh.fill_grid()
        subsurf(dirt_, 3)
        self.dirt_surface.apply(dirt_)
        butil.apply_modifiers(dirt_)

        remove_vertices(dirt_, lambda x, y, z: np.sqrt(x**2 + y**2) > radius * 0.92)
        dirt_.location[-1] -= 0.02

        plant = self.plant_factory.spawn_asset(i=i, loc=(0, 0, 0), rot=(0, 0, 0))
        origin2lowest(plant, approximate=True)
        self.plant_factory.finalize_assets(plant)

        scale = np.min(
            np.array([self.side_size, self.side_size, self.top_size])
            / np.max(np.abs(np.array(plant.bound_box)), 0)
        )
        plant.scale = [scale] * 3
        plant.location[-1] = dirt_z

        obj = join_objects([obj, plant, dirt_])
        return obj

    def _create_asset_timed(self, i, **params) -> bpy.types.Object:
        before_sets = profile_utils.bpy_datablock_name_sets()
        row = _empty_plant_assets_timing_row(self, i, params, before_sets)
        total_start_time = time.perf_counter()

        try:
            step_start_time = time.perf_counter()
            try:
                obj = self.base_factory.create_asset(i=i, **params)
            finally:
                _record_plant_duration(row, "pot_create_duration", step_start_time)

            step_start_time = time.perf_counter()
            try:
                horizontal = np.abs(read_edge_direction(obj)[:, -1]) < 0.1

                edge_center = read_edge_center(obj)
                z = edge_center[:, -1]
                dirt_z = (
                    self.dirt_ratio * self.base_factory.depth * self.base_factory.scale
                )
                idx = np.argmin(np.abs(z - dirt_z) - horizontal * 10)
                radius = np.sqrt((edge_center[idx] ** 2)[:2].sum())

                selection = np.zeros_like(z).astype(bool)
                selection[idx] = True
                with butil.ViewportMode(obj, "EDIT"):
                    bpy.ops.mesh.select_mode(type="EDGE")
                    select_edges(obj, selection)
                    bpy.ops.mesh.loop_multi_select(ring=False)
                    bpy.ops.mesh.duplicate_move()
                    bpy.ops.mesh.separate(type="SELECTED")

                dirt_ = bpy.context.selected_objects[-1]
                butil.select_none()
            finally:
                _record_plant_duration(row, "dirt_geometry_duration", step_start_time)

            step_start_time = time.perf_counter()
            try:
                self.base_factory.finalize_assets(obj)
            finally:
                _record_plant_duration(row, "pot_finalize_duration", step_start_time)

            step_start_time = time.perf_counter()
            try:
                with butil.ViewportMode(dirt_, "EDIT"):
                    bpy.ops.mesh.select_all(action="SELECT")
                    bpy.ops.mesh.fill_grid()
                subsurf(dirt_, 3)
            finally:
                _record_plant_duration(row, "dirt_geometry_duration", step_start_time)

            step_start_time = time.perf_counter()
            try:
                self.dirt_surface.apply(dirt_)
            finally:
                _record_plant_duration(row, "dirt_material_duration", step_start_time)

            step_start_time = time.perf_counter()
            try:
                butil.apply_modifiers(dirt_)
            finally:
                _record_plant_duration(row, "modifier_apply_duration", step_start_time)

            step_start_time = time.perf_counter()
            try:
                remove_vertices(
                    dirt_, lambda x, y, z: np.sqrt(x**2 + y**2) > radius * 0.92
                )
                dirt_.location[-1] -= 0.02
            finally:
                _record_plant_duration(row, "dirt_geometry_duration", step_start_time)

            step_start_time = time.perf_counter()
            _reset_plant_template_reuse_stats(self.plant_factory)
            wrapped_stage_methods = _install_plant_stage_timing(
                row, self.plant_factory
            )
            try:
                plant = self.plant_factory.spawn_asset(
                    i=i, loc=(0, 0, 0), rot=(0, 0, 0)
                )
                origin2lowest(plant, approximate=True)
            finally:
                _restore_plant_stage_timing(wrapped_stage_methods)
                _record_plant_template_reuse_stats(row, self.plant_factory)
                _record_plant_duration(row, "plant_spawn_duration", step_start_time)

            step_start_time = time.perf_counter()
            try:
                self.plant_factory.finalize_assets(plant)
            finally:
                _record_plant_duration(row, "plant_finalize_duration", step_start_time)

            step_start_time = time.perf_counter()
            try:
                scale = np.min(
                    np.array([self.side_size, self.side_size, self.top_size])
                    / np.max(np.abs(np.array(plant.bound_box)), 0)
                )
                plant.scale = [scale] * 3
                plant.location[-1] = dirt_z
            finally:
                _record_plant_duration(row, "plant_place_duration", step_start_time)

            step_start_time = time.perf_counter()
            try:
                obj = join_objects([obj, plant, dirt_])
            finally:
                _record_plant_duration(row, "join_duration", step_start_time)
                row["join_objects_duration"] = row["join_duration"]

            row["container_spawn_duration"] = (
                row["pot_create_duration"]
                + row["pot_finalize_duration"]
                + row["dirt_geometry_duration"]
                + row["dirt_material_duration"]
                + row["modifier_apply_duration"]
            )
            row["geometry_duration"] = (
                row["pot_create_duration"]
                + row["dirt_geometry_duration"]
                + row["plant_spawn_duration"]
                + row["plant_place_duration"]
                + row["join_duration"]
            )
            row["material_duration"] = (
                row["pot_finalize_duration"]
                + row["dirt_material_duration"]
                + row["plant_finalize_duration"]
            )
            row["material_generation_duration"] = row["material_duration"]
            row["success"] = True
            return obj
        except BaseException as exc:
            row["error_type"] = exc.__class__.__name__
            raise
        finally:
            row["create_asset_total_duration"] = time.perf_counter() - total_start_time
            _finish_plant_assets_timing_row(row, before_sets)


class LargePlantContainerFactory(PlantContainerFactory):
    plant_factories = [MonocotFactory]

    def __init__(self, factory_seed, coarse=False):
        super(LargePlantContainerFactory, self).__init__(factory_seed, coarse)
        with FixedSeed(self.factory_seed):
            self.base_factory.depth = log_uniform(1.0, 1.5)
            self.base_factory.scale = log_uniform(0.15, 0.25)
            self.side_size = (
                self.base_factory.scale * uniform(1.5, 2.0) * self.base_factory.r_expand
            )
            self.top_size = uniform(1, 1.5)
            # if WALL_HEIGHT - 2*WALL_THICKNESS < 3:
            #     self.top_size = uniform(1.5, WALL_HEIGHT - 2*WALL_THICKNESS)
            # else:
            #     self.top_size = uniform(1.5, 3)
            # print(f"{self.side_size=} {self.top_size=} {WALL_THICKNESS=} {WALL_HEIGHT=}")
