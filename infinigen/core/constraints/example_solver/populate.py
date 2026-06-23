# Copyright (C) 2024, Princeton University.
# This source code is licensed under the BSD 3-Clause license found in the LICENSE file in the root directory of this source tree.

# Authors:
# - Alexander Raistrick: populate_state_placeholders, apply_cutter
# - Stamatis Alexandropoulos: Initial version of window cutting

import csv
import logging
import os
import sys
import time
from pathlib import Path

import bpy
from tqdm import tqdm

from infinigen.core import tagging
from infinigen.core import tags as t
from infinigen.core.constraints import usage_lookup
from infinigen.core.constraints.constraint_language.util import delete_obj
from infinigen.core.constraints.example_solver.geometry import parse_scene
from infinigen.core.constraints.example_solver.state_def import State
from infinigen.core.placement.placement import parse_asset_name
from infinigen.core.util import blender as butil
from infinigen.core.util import profile_utils

logger = logging.getLogger(__name__)

POPULATE_ASSETS_TIMING_ENV_VAR = "INFINIGEN_PROFILE_POPULATE_ASSETS"
POPULATE_ASSETS_TIMING_CSV_NAME = "infinigen_populate_assets_timing.csv"
DEFAULT_POPULATE_ASSETS_TIMING_CSV = (
    Path("/tmp") / POPULATE_ASSETS_TIMING_CSV_NAME
)
DATABLOCK_GROWTH_TIMING_ENV_VAR = "INFINIGEN_PROFILE_DATABLOCK_GROWTH"
DATABLOCK_GROWTH_TIMING_CSV_NAME = "infinigen_datablock_growth_timing.csv"
DEFAULT_DATABLOCK_GROWTH_TIMING_CSV = (
    Path("/tmp") / DATABLOCK_GROWTH_TIMING_CSV_NAME
)

POPULATE_ASSETS_TIMING_FIELDNAMES = [
    "index",
    "total_count",
    "placeholder_name",
    "factory_class",
    "placeholder_type",
    "spawn_asset_duration",
    "finalize_assets_duration",
    "collection_duration",
    "cutter_duration",
    "total_duration",
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
    "success",
    "error_type",
]

_POPULATE_ASSETS_TIMING_WRITE_FAILED = False
_DATABLOCK_GROWTH_TIMING_WRITE_FAILED = False

DATABLOCK_GROWTH_TIMING_FIELDNAMES = [
    "index",
    "total_count",
    "factory_class",
    "placeholder_name",
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
    "image_count_before",
    "image_count_after",
    "created_material_count",
    "created_texture_count",
    "created_node_group_count",
    "created_mesh_count",
    "created_object_count",
    "created_image_count",
    "created_material_names_sample",
    "created_texture_names_sample",
    "created_node_group_names_sample",
    "created_mesh_names_sample",
    "created_image_names_sample",
    "created_material_prefix_top",
    "created_texture_prefix_top",
    "created_node_group_prefix_top",
    "created_mesh_prefix_top",
    "created_image_prefix_top",
    "duration",
    "success",
    "error_type",
]


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _profile_populate_assets_enabled() -> bool:
    return _env_truthy(POPULATE_ASSETS_TIMING_ENV_VAR)


def _profile_datablock_growth_enabled() -> bool:
    return _env_truthy(DATABLOCK_GROWTH_TIMING_ENV_VAR)


def _populate_assets_timing_csv_path() -> Path:
    solver_timing = sys.modules.get("infinigen.core.constraints.example_solver.timing")
    if solver_timing is not None:
        current_output_folder = getattr(solver_timing, "current_output_folder", None)
        if current_output_folder is not None:
            output_folder = current_output_folder()
            if output_folder is not None:
                return Path(output_folder) / POPULATE_ASSETS_TIMING_CSV_NAME
    return DEFAULT_POPULATE_ASSETS_TIMING_CSV


def _datablock_growth_timing_csv_path() -> Path:
    return profile_utils.solver_output_csv_path(
        DATABLOCK_GROWTH_TIMING_CSV_NAME,
        DEFAULT_DATABLOCK_GROWTH_TIMING_CSV,
    )


def _write_populate_assets_timing_row(row: dict):
    global _POPULATE_ASSETS_TIMING_WRITE_FAILED

    if _POPULATE_ASSETS_TIMING_WRITE_FAILED:
        return

    path = _populate_assets_timing_csv_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        write_header = not path.exists() or path.stat().st_size == 0
        with path.open("a", newline="") as handle:
            writer = csv.DictWriter(
                handle, fieldnames=POPULATE_ASSETS_TIMING_FIELDNAMES
            )
            if write_header:
                writer.writeheader()
            writer.writerow(
                {
                    field: row.get(field, "")
                    for field in POPULATE_ASSETS_TIMING_FIELDNAMES
                }
            )
    except OSError:
        _POPULATE_ASSETS_TIMING_WRITE_FAILED = True
        logger.exception("Failed to write populate assets timing CSV at %s", path)


def _write_datablock_growth_timing_row(row: dict):
    global _DATABLOCK_GROWTH_TIMING_WRITE_FAILED

    if _DATABLOCK_GROWTH_TIMING_WRITE_FAILED:
        return

    path = _datablock_growth_timing_csv_path()
    try:
        profile_utils.write_csv_row(path, DATABLOCK_GROWTH_TIMING_FIELDNAMES, row)
    except OSError:
        _DATABLOCK_GROWTH_TIMING_WRITE_FAILED = True
        logger.exception("Failed to write datablock growth timing CSV at %s", path)


def _bpy_datablock_name_sets() -> dict[str, set[str]]:
    return {
        "material": set(bpy.data.materials.keys()),
        "texture": set(bpy.data.textures.keys()),
        "node_group": set(bpy.data.node_groups.keys()),
        "mesh": set(bpy.data.meshes.keys()),
        "object": set(bpy.data.objects.keys()),
    }


def _placeholder_type(name: str) -> str:
    if "bbox_placeholder" in name:
        return "bbox_placeholder"
    if "spawn_placeholder" in name:
        return "spawn_placeholder"
    return "(unknown)"


def _empty_populate_assets_timing_row(
    index: int,
    total_count: int,
    placeholder_name: str,
    factory_class: str,
    before_sets: dict[str, set[str]],
) -> dict:
    row = {
        "index": index,
        "total_count": total_count,
        "placeholder_name": placeholder_name,
        "factory_class": factory_class,
        "placeholder_type": _placeholder_type(placeholder_name),
        "spawn_asset_duration": 0.0,
        "finalize_assets_duration": 0.0,
        "collection_duration": 0.0,
        "cutter_duration": 0.0,
        "total_duration": 0.0,
        "success": False,
        "error_type": "",
    }
    for key, names in before_sets.items():
        row[f"{key}_count_before"] = len(names)
    return row


def _empty_datablock_growth_timing_row(
    index: int,
    total_count: int,
    placeholder_name: str,
    factory_class: str,
    before_sets: dict[str, set[str]],
) -> dict:
    row = {
        "index": index,
        "total_count": total_count,
        "placeholder_name": placeholder_name,
        "factory_class": factory_class,
        "duration": 0.0,
        "success": False,
        "error_type": "",
    }
    profile_utils.add_datablock_before_counts(row, before_sets)
    return row


def _record_populate_assets_duration(row: dict, field: str, start_time: float):
    row[field] = row.get(field, 0.0) + time.perf_counter() - start_time


def _finish_populate_assets_timing_row(
    row: dict,
    before_sets: dict[str, set[str]],
):
    after_sets = _bpy_datablock_name_sets()
    for key, before_names in before_sets.items():
        after_names = after_sets[key]
        row[f"{key}_count_after"] = len(after_names)
        row[f"created_{key}_count"] = len(after_names - before_names)
    _write_populate_assets_timing_row(row)


def _finish_datablock_growth_timing_row(
    row: dict,
    before_sets: dict[str, set[str]],
):
    profile_utils.add_datablock_after_counts(
        row,
        before_sets,
        include_name_samples=True,
        sample_limit=20,
        prefix_limit=8,
    )
    _write_datablock_growth_timing_row(row)


def apply_cutter(state, objkey, cutter):
    os = state.objs[objkey]

    cut_objs = []
    for i, relation_state in enumerate(os.relations):
        # TODO in theory we maybe should check if they actually intersect

        parent_obj = state.objs[relation_state.target_name].obj
        butil.modify_mesh(
            parent_obj,
            "BOOLEAN",
            object=butil.copy(cutter),
            operation="DIFFERENCE",
            solver="FAST",
        )

        target_obj_name = state.objs[relation_state.target_name].obj.name
        cut_objs.append((relation_state.target_name, target_obj_name))

    cutter_col = butil.get_collection("placeholders:asset_cutters")
    butil.put_in_collection(cutter, cutter_col)

    return cut_objs


def populate_state_placeholders(state: State, filter=None, final=True):
    logger.info(f"Populating placeholders {final=} {filter=}")
    unique_assets = butil.get_collection("unique_assets")
    unique_assets.hide_viewport = True
    profile_populate_assets = (
        _profile_populate_assets_enabled() and final and filter is None
    )
    profile_datablock_growth = (
        _profile_datablock_growth_enabled() and final and filter is None
    )

    if final:
        for os in state.objs.values():
            if t.Semantics.Room in os.tags:
                os.obj = bpy.data.objects[os.obj.name + ".meshed"]

    targets = []

    for objkey, os in state.objs.items():
        if os.generator is None:
            continue

        if filter is not None and not usage_lookup.has_usage(
            os.generator.__class__, filter
        ):
            continue

        if "spawn_asset" in os.obj.name:
            butil.put_in_collection(os.obj, unique_assets)
            logger.debug(f"Found already populated asset {os.obj.name=}, continuing")
            continue

        targets.append(objkey)

    update_state_mesh_objs = []

    for i, objkey in enumerate(targets):
        os = state.objs[objkey]
        placeholder = os.obj

        logger.info(f"Populating {i}/{len(targets)} {placeholder.name=}")

        old_objname = placeholder.name
        update_state_mesh_objs.append((objkey, old_objname))

        if profile_populate_assets or profile_datablock_growth:
            populate_before_sets = (
                _bpy_datablock_name_sets() if profile_populate_assets else None
            )
            datablock_before_sets = (
                profile_utils.bpy_datablock_name_sets()
                if profile_datablock_growth
                else None
            )
            row = (
                _empty_populate_assets_timing_row(
                    i,
                    len(targets),
                    old_objname,
                    os.generator.__class__.__name__,
                    populate_before_sets,
                )
                if populate_before_sets is not None
                else None
            )
            datablock_row = (
                _empty_datablock_growth_timing_row(
                    i,
                    len(targets),
                    old_objname,
                    os.generator.__class__.__name__,
                    datablock_before_sets,
                )
                if datablock_before_sets is not None
                else None
            )
            total_start_time = time.perf_counter()
            try:
                *_, inst_seed = parse_asset_name(placeholder.name)
                step_start_time = time.perf_counter()
                try:
                    os.obj = os.generator.spawn_asset(
                        i=int(inst_seed),
                        loc=placeholder.location,  # we could use placeholder=pholder here, but I worry pholder may have been modified
                        rot=placeholder.rotation_euler,
                    )
                finally:
                    if row is not None:
                        _record_populate_assets_duration(
                            row, "spawn_asset_duration", step_start_time
                        )

                step_start_time = time.perf_counter()
                try:
                    os.generator.finalize_assets([os.obj])
                finally:
                    if row is not None:
                        _record_populate_assets_duration(
                            row, "finalize_assets_duration", step_start_time
                        )

                step_start_time = time.perf_counter()
                try:
                    butil.put_in_collection(os.obj, unique_assets)
                finally:
                    if row is not None:
                        _record_populate_assets_duration(
                            row, "collection_duration", step_start_time
                        )

                cutter = next(
                    (
                        o
                        for o in butil.iter_object_tree(os.obj)
                        if o.name.endswith(".cutter")
                    ),
                    None,
                )
                logger.debug(
                    f"{populate_state_placeholders.__name__} found {cutter=} for {os.obj.name=}"
                )
                if cutter is not None:
                    step_start_time = time.perf_counter()
                    try:
                        cut_objs = apply_cutter(state, objkey, cutter)
                    finally:
                        if row is not None:
                            _record_populate_assets_duration(
                                row, "cutter_duration", step_start_time
                            )
                    logger.debug(
                        f"{populate_state_placeholders.__name__} cut {cutter.name=} from {cut_objs=}"
                    )
                    update_state_mesh_objs += cut_objs

                if row is not None:
                    row["success"] = True
                if datablock_row is not None:
                    datablock_row["success"] = True
            except BaseException as exc:
                if row is not None:
                    row["error_type"] = exc.__class__.__name__
                if datablock_row is not None:
                    datablock_row["error_type"] = exc.__class__.__name__
                raise
            finally:
                duration = time.perf_counter() - total_start_time
                if row is not None:
                    row["total_duration"] = duration
                    _finish_populate_assets_timing_row(row, populate_before_sets)
                if datablock_row is not None:
                    datablock_row["duration"] = duration
                    _finish_datablock_growth_timing_row(
                        datablock_row,
                        datablock_before_sets,
                    )
        else:
            *_, inst_seed = parse_asset_name(placeholder.name)
            os.obj = os.generator.spawn_asset(
                i=int(inst_seed),
                loc=placeholder.location,  # we could use placeholder=pholder here, but I worry pholder may have been modified
                rot=placeholder.rotation_euler,
            )
            os.generator.finalize_assets([os.obj])
            butil.put_in_collection(os.obj, unique_assets)

            cutter = next(
                (
                    o
                    for o in butil.iter_object_tree(os.obj)
                    if o.name.endswith(".cutter")
                ),
                None,
            )
            logger.debug(
                f"{populate_state_placeholders.__name__} found {cutter=} for {os.obj.name=}"
            )
            if cutter is not None:
                cut_objs = apply_cutter(state, objkey, cutter)
                logger.debug(
                    f"{populate_state_placeholders.__name__} cut {cutter.name=} from {cut_objs=}"
                )
                update_state_mesh_objs += cut_objs

    unique_assets.hide_viewport = False

    if final:
        return

    # objects modified in any way (via pholder update or boolean cut) must be synched with trimesh state
    for objkey, old_objname in tqdm(
        set(update_state_mesh_objs), desc="Updating trimesh with populated objects"
    ):
        os = state.objs[objkey]

        # delete old trimesh
        delete_obj(state.trimesh_scene, old_objname, delete_blender=False)

        # put the new, populated object into the state
        parse_scene.preprocess_obj(os.obj)
        if not final:
            tagging.tag_canonical_surfaces(os.obj)
        parse_scene.add_to_scene(state.trimesh_scene, os.obj, preprocess=True)
