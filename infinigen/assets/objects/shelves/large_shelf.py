# Copyright (C) 2024, Princeton University.
# This source code is licensed under the BSD 3-Clause license found in the LICENSE file in the root directory of this source tree.

# Authors: Beining Han

import csv
import json
import logging
import os
import sys
import time
from collections import Counter
from pathlib import Path

import bpy
import numpy as np
from numpy.random import normal, randint, uniform

from infinigen.assets.materials.wood.plywood import (
    shader_shelves_black_wood,
    shader_shelves_black_wood_z,
    shader_shelves_white,
    shader_shelves_wood,
    shader_shelves_wood_z,
)
from infinigen.assets.objects.shelves.utils import nodegroup_tagged_cube
from infinigen.core import surface, tagging
from infinigen.core.nodes import node_utils
from infinigen.core.nodes.node_wrangler import Nodes, NodeWrangler
from infinigen.core.placement.factory import AssetFactory

logger = logging.getLogger(__name__)

SHELF_NODEGROUP_TIMING_ENV_VAR = "INFINIGEN_PROFILE_SHELF_NODEGROUPS"
LARGESHELF_CHILD_NODEGROUP_REUSE_ENV_VAR = (
    "INFINIGEN_REUSE_LARGESHELF_CHILD_NODEGROUPS"
)
SHELF_NODEGROUP_TIMING_CSV_NAME = "infinigen_shelf_nodegroup_timing.csv"
DEFAULT_SHELF_NODEGROUP_TIMING_CSV = (
    Path("/tmp") / SHELF_NODEGROUP_TIMING_CSV_NAME
)
LARGESHELF_CHILD_NODEGROUP_REUSE_PREFIXES = {
    "nodegroup_screw_head",
    "nodegroup_side_board",
    "nodegroup_bottom_board",
    "nodegroup_back_board",
}

SHELF_NODEGROUP_TIMING_FIELDNAMES = [
    "event",
    "spawn_id",
    "factory_class",
    "factory_seed",
    "create_asset_index",
    "call_index",
    "prefix",
    "node_group_name",
    "duration",
    "node_groups_before",
    "node_groups_after",
    "created_count",
    "created_names",
    "created_prefix_counts",
    "call_prefix_counts",
    "shelf_cell_count",
    "division_level_count",
    "side_board_count",
    "tag_support",
    "reuse_enabled",
    "cache_hit",
    "cache_key",
    "cache_size",
    "returned_nodegroup_name",
    "success",
    "error_type",
]

_SHELF_NODEGROUP_TIMING_WRITE_FAILED = False
_SHELF_NODEGROUP_SPAWN_COUNTER = 0
_LARGESHELF_CHILD_NODEGROUP_CACHE = {}


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _profile_shelf_nodegroups_enabled() -> bool:
    return _env_truthy(SHELF_NODEGROUP_TIMING_ENV_VAR)


def _reuse_largeshelf_child_nodegroups_enabled() -> bool:
    return _env_truthy(LARGESHELF_CHILD_NODEGROUP_REUSE_ENV_VAR)


def _shelf_nodegroup_timing_csv_path() -> Path:
    solver_timing = sys.modules.get("infinigen.core.constraints.example_solver.timing")
    if solver_timing is not None:
        current_output_folder = getattr(solver_timing, "current_output_folder", None)
        if current_output_folder is not None:
            output_folder = current_output_folder()
            if output_folder is not None:
                return Path(output_folder) / SHELF_NODEGROUP_TIMING_CSV_NAME
    return DEFAULT_SHELF_NODEGROUP_TIMING_CSV


def _write_shelf_nodegroup_timing_row(row: dict):
    global _SHELF_NODEGROUP_TIMING_WRITE_FAILED

    if _SHELF_NODEGROUP_TIMING_WRITE_FAILED:
        return

    path = _shelf_nodegroup_timing_csv_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        write_header = not path.exists() or path.stat().st_size == 0
        with path.open("a", newline="") as handle:
            writer = csv.DictWriter(
                handle, fieldnames=SHELF_NODEGROUP_TIMING_FIELDNAMES
            )
            if write_header:
                writer.writeheader()
            writer.writerow(
                {
                    field: row.get(field, "")
                    for field in SHELF_NODEGROUP_TIMING_FIELDNAMES
                }
            )
    except OSError:
        _SHELF_NODEGROUP_TIMING_WRITE_FAILED = True
        logger.exception("Failed to write shelf node group timing CSV at %s", path)


def _nodegroup_name_set() -> set[str]:
    return {str(name) for name in bpy.data.node_groups.keys()}


def _nodegroup_prefix(name: str) -> str:
    if "." not in name:
        return name
    base, suffix = name.rsplit(".", 1)
    return base if suffix.isdigit() else name


def _json_counter(counter: Counter) -> str:
    return json.dumps(dict(sorted(counter.items())), sort_keys=True)


def _json_list(values) -> str:
    return json.dumps(list(values))


def _format_shelf_nodegroup_cache_key(cache_key) -> str:
    if cache_key is None:
        return ""
    return json.dumps(list(cache_key))


def _live_cached_largeshelf_child_nodegroup(cache_key):
    cached_nodegroup = _LARGESHELF_CHILD_NODEGROUP_CACHE.get(cache_key)
    if cached_nodegroup is None:
        return None

    try:
        cached_name = cached_nodegroup.name
        cached_pointer = cached_nodegroup.as_pointer()
    except ReferenceError:
        _LARGESHELF_CHILD_NODEGROUP_CACHE.pop(cache_key, None)
        return None

    live_nodegroup = bpy.data.node_groups.get(cached_name)
    if live_nodegroup is None:
        _LARGESHELF_CHILD_NODEGROUP_CACHE.pop(cache_key, None)
        return None

    try:
        live_pointer = live_nodegroup.as_pointer()
    except ReferenceError:
        _LARGESHELF_CHILD_NODEGROUP_CACHE.pop(cache_key, None)
        return None
    if live_pointer != cached_pointer:
        _LARGESHELF_CHILD_NODEGROUP_CACHE.pop(cache_key, None)
        return None
    if live_nodegroup is not cached_nodegroup:
        _LARGESHELF_CHILD_NODEGROUP_CACHE[cache_key] = live_nodegroup
    return live_nodegroup


def _create_or_reuse_largeshelf_child_nodegroup(prefix: str, creator, cache_key=None):
    reuse_enabled = (
        _reuse_largeshelf_child_nodegroups_enabled()
        and cache_key is not None
        and prefix in LARGESHELF_CHILD_NODEGROUP_REUSE_PREFIXES
    )
    if not reuse_enabled:
        return creator(), False

    cached_nodegroup = _live_cached_largeshelf_child_nodegroup(cache_key)
    if cached_nodegroup is not None:
        return cached_nodegroup, True

    nodegroup = creator()
    _LARGESHELF_CHILD_NODEGROUP_CACHE[cache_key] = nodegroup
    return nodegroup, False


def _begin_shelf_nodegroup_spawn(factory, create_asset_index: int) -> dict | None:
    global _SHELF_NODEGROUP_SPAWN_COUNTER

    if not _profile_shelf_nodegroups_enabled():
        return None

    _SHELF_NODEGROUP_SPAWN_COUNTER += 1
    before_names = _nodegroup_name_set()
    return {
        "spawn_id": _SHELF_NODEGROUP_SPAWN_COUNTER,
        "factory_class": factory.__class__.__name__,
        "factory_seed": getattr(factory, "factory_seed", ""),
        "create_asset_index": create_asset_index,
        "start_time": time.perf_counter(),
        "node_group_names_before": before_names,
        "node_groups_before": len(before_names),
        "nodegroup_rows": [],
        "call_prefix_counts": Counter(),
        "call_index": 0,
        "shelf_cell_count": "",
        "division_level_count": "",
        "side_board_count": "",
        "tag_support": "",
        "reuse_enabled": _reuse_largeshelf_child_nodegroups_enabled(),
    }


def _update_shelf_nodegroup_spawn_context(context: dict | None, params: dict):
    if context is None:
        return
    context["shelf_cell_count"] = len(params.get("shelf_cell_width", []))
    context["division_level_count"] = len(
        params.get("division_board_z_translation", [])
    )
    context["side_board_count"] = len(params.get("side_board_x_translation", []))
    context["tag_support"] = params.get("tag_support", "")


def _profile_shelf_nodegroup(
    context: dict | None, prefix: str, creator, cache_key=None
):
    if context is None:
        node_group, _cache_hit = _create_or_reuse_largeshelf_child_nodegroup(
            prefix, creator, cache_key=cache_key
        )
        return node_group

    context["call_index"] += 1
    call_index = context["call_index"]
    before_names = _nodegroup_name_set()
    start_time = time.perf_counter()
    node_group = None
    error_type = ""
    cache_hit = False
    cache_key_text = _format_shelf_nodegroup_cache_key(cache_key)
    try:
        node_group, cache_hit = _create_or_reuse_largeshelf_child_nodegroup(
            prefix, creator, cache_key=cache_key
        )
        return node_group
    except Exception as exc:
        error_type = exc.__class__.__name__
        raise
    finally:
        duration = time.perf_counter() - start_time
        after_names = _nodegroup_name_set()
        created_names = sorted(after_names - before_names)
        created_prefix_counts = Counter(
            _nodegroup_prefix(name) for name in created_names
        )
        context["call_prefix_counts"][prefix] += 1
        context["nodegroup_rows"].append(
            {
                "event": "nodegroup_create",
                "spawn_id": context["spawn_id"],
                "factory_class": context["factory_class"],
                "factory_seed": context["factory_seed"],
                "create_asset_index": context["create_asset_index"],
                "call_index": call_index,
                "prefix": prefix,
                "node_group_name": getattr(node_group, "name", ""),
                "duration": duration,
                "node_groups_before": len(before_names),
                "node_groups_after": len(after_names),
                "created_count": len(created_names),
                "created_names": _json_list(created_names),
                "created_prefix_counts": _json_counter(created_prefix_counts),
                "shelf_cell_count": context["shelf_cell_count"],
                "division_level_count": context["division_level_count"],
                "side_board_count": context["side_board_count"],
                "tag_support": context["tag_support"],
                "reuse_enabled": context["reuse_enabled"],
                "cache_hit": cache_hit,
                "cache_key": cache_key_text,
                "cache_size": len(_LARGESHELF_CHILD_NODEGROUP_CACHE),
                "returned_nodegroup_name": getattr(node_group, "name", ""),
                "success": not error_type,
                "error_type": error_type,
            }
        )


def _finish_shelf_nodegroup_spawn(
    context: dict | None, success: bool, error_type: str = ""
):
    if context is None:
        return

    after_names = _nodegroup_name_set()
    created_names = sorted(after_names - context["node_group_names_before"])
    created_prefix_counts = Counter(_nodegroup_prefix(name) for name in created_names)
    duration = time.perf_counter() - context["start_time"]

    for row in context["nodegroup_rows"]:
        _write_shelf_nodegroup_timing_row(row)

    _write_shelf_nodegroup_timing_row(
        {
            "event": "spawn_summary",
            "spawn_id": context["spawn_id"],
            "factory_class": context["factory_class"],
            "factory_seed": context["factory_seed"],
            "create_asset_index": context["create_asset_index"],
            "duration": duration,
            "node_groups_before": context["node_groups_before"],
            "node_groups_after": len(after_names),
            "created_count": len(created_names),
            "created_names": _json_list(created_names),
            "created_prefix_counts": _json_counter(created_prefix_counts),
            "call_prefix_counts": _json_counter(context["call_prefix_counts"]),
            "shelf_cell_count": context["shelf_cell_count"],
            "division_level_count": context["division_level_count"],
            "side_board_count": context["side_board_count"],
            "tag_support": context["tag_support"],
            "reuse_enabled": context["reuse_enabled"],
            "cache_size": len(_LARGESHELF_CHILD_NODEGROUP_CACHE),
            "success": success,
            "error_type": error_type,
        }
    )


@node_utils.to_nodegroup(
    "nodegroup_screw_head", singleton=False, type="GeometryNodeTree"
)
def nodegroup_screw_head(nw: NodeWrangler):
    # Code generated using version 2.6.4 of the node_transpiler

    group_input = nw.new_node(
        Nodes.GroupInput,
        expose_input=[
            ("NodeSocketFloat", "Depth", 0.0050),
            ("NodeSocketFloat", "Radius", 1.0000),
            ("NodeSocketFloat", "division_thickness", 0.5000),
            ("NodeSocketFloat", "width", 0.5000),
            ("NodeSocketFloat", "depth", 0.5000),
            ("NodeSocketFloat", "screw_width_gap", 0.5000),
            ("NodeSocketFloat", "screw_depth_gap", 0.0000),
        ],
    )

    cylinder = nw.new_node(
        "GeometryNodeMeshCylinder",
        input_kwargs={
            "Radius": group_input.outputs["Radius"],
            "Depth": group_input.outputs["Depth"],
        },
        attrs={"fill_type": "TRIANGLE_FAN"},
    )

    transform = nw.new_node(
        Nodes.Transform, input_kwargs={"Geometry": cylinder.outputs["Mesh"]}
    )

    multiply = nw.new_node(
        Nodes.Math,
        input_kwargs={0: group_input.outputs["width"]},
        attrs={"operation": "MULTIPLY"},
    )

    subtract = nw.new_node(
        Nodes.Math,
        input_kwargs={0: multiply, 1: group_input.outputs["screw_width_gap"]},
        attrs={"operation": "SUBTRACT"},
    )

    multiply_1 = nw.new_node(
        Nodes.Math,
        input_kwargs={0: group_input.outputs["depth"]},
        attrs={"operation": "MULTIPLY"},
    )

    add = nw.new_node(
        Nodes.Math, input_kwargs={0: group_input.outputs["screw_width_gap"], 1: 0.0000}
    )

    subtract_1 = nw.new_node(
        Nodes.Math,
        input_kwargs={0: multiply_1, 1: add},
        attrs={"operation": "SUBTRACT"},
    )

    multiply_2 = nw.new_node(
        Nodes.Math,
        input_kwargs={0: subtract_1, 1: -1.0000},
        attrs={"operation": "MULTIPLY"},
    )

    multiply_3 = nw.new_node(
        Nodes.Math,
        input_kwargs={0: group_input.outputs["division_thickness"], 1: -0.5000},
        attrs={"operation": "MULTIPLY"},
    )

    combine_xyz = nw.new_node(
        Nodes.CombineXYZ, input_kwargs={"X": subtract, "Y": multiply_2, "Z": multiply_3}
    )

    transform_1 = nw.new_node(
        Nodes.Transform,
        input_kwargs={"Geometry": transform, "Translation": combine_xyz},
    )

    combine_xyz_4 = nw.new_node(
        Nodes.CombineXYZ, input_kwargs={"X": subtract, "Y": subtract_1, "Z": multiply_3}
    )

    transform_6 = nw.new_node(
        Nodes.Transform,
        input_kwargs={"Geometry": transform, "Translation": combine_xyz_4},
    )

    join_geometry_2 = nw.new_node(
        Nodes.JoinGeometry, input_kwargs={"Geometry": [transform_1, transform_6]}
    )

    transform_4 = nw.new_node(
        Nodes.Transform,
        input_kwargs={"Geometry": join_geometry_2, "Scale": (-1.0000, 1.0000, 1.0000)},
    )

    join_geometry_3 = nw.new_node(
        Nodes.JoinGeometry, input_kwargs={"Geometry": [transform_4, join_geometry_2]}
    )

    realize_instances = nw.new_node(
        Nodes.RealizeInstances, input_kwargs={"Geometry": join_geometry_3}
    )

    group_output = nw.new_node(
        Nodes.GroupOutput,
        input_kwargs={"Geometry": realize_instances},
        attrs={"is_active_output": True},
    )


@node_utils.to_nodegroup(
    "nodegroup_attachment", singleton=False, type="GeometryNodeTree"
)
def nodegroup_attachment(nw: NodeWrangler):
    # Code generated using version 2.6.4 of the node_transpiler

    group_input = nw.new_node(
        Nodes.GroupInput,
        expose_input=[
            ("NodeSocketFloat", "attach_thickness", 0.0000),
            ("NodeSocketFloat", "attach_length", 0.0000),
            ("NodeSocketFloat", "attach_z_translation", 0.0000),
            ("NodeSocketFloat", "depth", 0.5000),
            ("NodeSocketFloat", "width", 0.5000),
            ("NodeSocketFloat", "attach_gap", 0.5000),
            ("NodeSocketFloat", "attach_width", 0.5000),
        ],
    )

    add = nw.new_node(
        Nodes.Math, input_kwargs={0: group_input.outputs["attach_width"], 1: 0.0000}
    )

    add_1 = nw.new_node(
        Nodes.Math, input_kwargs={0: group_input.outputs["attach_length"], 1: 0.0000}
    )

    combine_xyz = nw.new_node(
        Nodes.CombineXYZ,
        input_kwargs={
            "X": add,
            "Y": add_1,
            "Z": group_input.outputs["attach_thickness"],
        },
    )

    cube = nw.new_node(
        Nodes.MeshCube,
        input_kwargs={
            "Size": combine_xyz,
            "Vertices X": 2,
            "Vertices Y": 2,
            "Vertices Z": 2,
        },
    )

    multiply = nw.new_node(
        Nodes.Math,
        input_kwargs={0: group_input.outputs["width"]},
        attrs={"operation": "MULTIPLY"},
    )

    subtract = nw.new_node(
        Nodes.Math,
        input_kwargs={0: multiply, 1: group_input.outputs["attach_gap"]},
        attrs={"operation": "SUBTRACT"},
    )

    subtract_1 = nw.new_node(
        Nodes.Math, input_kwargs={0: subtract, 1: add}, attrs={"operation": "SUBTRACT"}
    )

    multiply_1 = nw.new_node(
        Nodes.Math, input_kwargs={0: add_1}, attrs={"operation": "MULTIPLY"}
    )

    multiply_2 = nw.new_node(
        Nodes.Math,
        input_kwargs={0: group_input.outputs["depth"], 1: -0.5000},
        attrs={"operation": "MULTIPLY"},
    )

    add_2 = nw.new_node(Nodes.Math, input_kwargs={0: multiply_1, 1: multiply_2})

    combine_xyz_1 = nw.new_node(
        Nodes.CombineXYZ,
        input_kwargs={
            "X": subtract_1,
            "Y": add_2,
            "Z": group_input.outputs["attach_z_translation"],
        },
    )

    transform = nw.new_node(
        Nodes.Transform, input_kwargs={"Geometry": cube, "Translation": combine_xyz_1}
    )

    transform_1 = nw.new_node(
        Nodes.Transform,
        input_kwargs={"Geometry": transform, "Scale": (-1.0000, 1.0000, 1.0000)},
    )

    join_geometry_1 = nw.new_node(
        Nodes.JoinGeometry, input_kwargs={"Geometry": [transform_1, transform]}
    )

    group_output = nw.new_node(
        Nodes.GroupOutput,
        input_kwargs={"Geometry": join_geometry_1},
        attrs={"is_active_output": True},
    )


@node_utils.to_nodegroup(
    "nodegroup_division_board", singleton=False, type="GeometryNodeTree"
)
def nodegroup_division_board(
    nw: NodeWrangler, material, tag_support=False, shelf_nodegroup_profile=None
):
    # Code generated using version 2.6.4 of the node_transpiler

    group_input = nw.new_node(
        Nodes.GroupInput,
        expose_input=[
            ("NodeSocketFloat", "thickness", 0.0000),
            ("NodeSocketFloat", "width", 0.0000),
            ("NodeSocketFloat", "depth", 0.0000),
            ("NodeSocketFloat", "z_translation", 0.0000),
            ("NodeSocketFloat", "x_translation", 0.0000),
            ("NodeSocketFloat", "screw_depth", 0.0000),
            ("NodeSocketFloat", "screw_radius", 0.0000),
            ("NodeSocketFloat", "screw_width_gap", 0.0000),
            ("NodeSocketFloat", "screw_depth_gap", 0.0000),
        ],
    )

    combine_xyz = nw.new_node(
        Nodes.CombineXYZ,
        input_kwargs={
            "X": group_input.outputs["width"],
            "Y": group_input.outputs["depth"],
            "Z": group_input.outputs["thickness"],
        },
    )

    if tag_support:
        tagged_cube_nodegroup = _profile_shelf_nodegroup(
            shelf_nodegroup_profile, "nodegroup_tagged_cube", nodegroup_tagged_cube
        )
        cube = nw.new_node(
            tagged_cube_nodegroup.name, input_kwargs={"Size": combine_xyz}
        )
    else:
        cube = nw.new_node(
            Nodes.MeshCube,
            input_kwargs={
                "Size": combine_xyz,
                "Vertices X": 2,
                "Vertices Y": 2,
                "Vertices Z": 2,
            },
        )

    screw_head_nodegroup = _profile_shelf_nodegroup(
        shelf_nodegroup_profile,
        "nodegroup_screw_head",
        nodegroup_screw_head,
        cache_key=("nodegroup_screw_head",),
    )
    screw_head = nw.new_node(
        screw_head_nodegroup.name,
        input_kwargs={
            "Depth": group_input.outputs["screw_depth"],
            "Radius": group_input.outputs["screw_radius"],
            "division_thickness": group_input.outputs["thickness"],
            "width": group_input.outputs["width"],
            "depth": group_input.outputs["depth"],
            "screw_width_gap": group_input.outputs["screw_width_gap"],
            "screw_depth_gap": group_input.outputs["screw_depth_gap"],
        },
    )

    join_geometry = nw.new_node(
        Nodes.JoinGeometry, input_kwargs={"Geometry": [cube, screw_head]}
    )

    combine_xyz_1 = nw.new_node(
        Nodes.CombineXYZ,
        input_kwargs={
            "X": group_input.outputs["x_translation"],
            "Z": group_input.outputs["z_translation"],
        },
    )

    transform = nw.new_node(
        Nodes.Transform,
        input_kwargs={"Geometry": join_geometry, "Translation": combine_xyz_1},
    )

    group_output = nw.new_node(
        Nodes.GroupOutput,
        input_kwargs={"Geometry": transform},
        attrs={"is_active_output": True},
    )


@node_utils.to_nodegroup(
    "nodegroup_bottom_board", singleton=False, type="GeometryNodeTree"
)
def nodegroup_bottom_board(nw: NodeWrangler):
    # Code generated using version 2.6.4 of the node_transpiler

    group_input = nw.new_node(
        Nodes.GroupInput,
        expose_input=[
            ("NodeSocketFloat", "thickness", 0.0000),
            ("NodeSocketFloat", "depth", 0.5000),
            ("NodeSocketFloat", "y_gap", 0.5000),
            ("NodeSocketFloat", "x_translation", 0.0000),
            ("NodeSocketFloat", "height", 0.5000),
            ("NodeSocketFloat", "width", 0.0000),
        ],
    )

    add = nw.new_node(
        Nodes.Math, input_kwargs={0: group_input.outputs["height"], 1: 0.0000}
    )

    combine_xyz = nw.new_node(
        Nodes.CombineXYZ,
        input_kwargs={
            "X": group_input.outputs["width"],
            "Y": group_input.outputs["thickness"],
            "Z": add,
        },
    )

    cube = nw.new_node(
        Nodes.MeshCube,
        input_kwargs={
            "Size": combine_xyz,
            "Vertices X": 2,
            "Vertices Y": 2,
            "Vertices Z": 2,
        },
    )

    multiply = nw.new_node(
        Nodes.Math,
        input_kwargs={0: group_input.outputs["depth"]},
        attrs={"operation": "MULTIPLY"},
    )

    subtract = nw.new_node(
        Nodes.Math,
        input_kwargs={0: multiply, 1: group_input.outputs["y_gap"]},
        attrs={"operation": "SUBTRACT"},
    )

    multiply_1 = nw.new_node(
        Nodes.Math, input_kwargs={0: add}, attrs={"operation": "MULTIPLY"}
    )

    combine_xyz_1 = nw.new_node(
        Nodes.CombineXYZ,
        input_kwargs={
            "X": group_input.outputs["x_translation"],
            "Y": subtract,
            "Z": multiply_1,
        },
    )

    transform = nw.new_node(
        Nodes.Transform, input_kwargs={"Geometry": cube, "Translation": combine_xyz_1}
    )

    group_output = nw.new_node(
        Nodes.GroupOutput,
        input_kwargs={"Geometry": transform},
        attrs={"is_active_output": True},
    )


@node_utils.to_nodegroup(
    "nodegroup_back_board", singleton=False, type="GeometryNodeTree"
)
def nodegroup_back_board(nw: NodeWrangler):
    # Code generated using version 2.6.4 of the node_transpiler

    group_input = nw.new_node(
        Nodes.GroupInput,
        expose_input=[
            ("NodeSocketFloat", "width", 0.0000),
            ("NodeSocketFloat", "thickness", 0.5000),
            ("NodeSocketFloat", "height", 0.5000),
            ("NodeSocketFloat", "depth", 0.5000),
        ],
    )

    add = nw.new_node(
        Nodes.Math, input_kwargs={0: group_input.outputs["thickness"], 1: 0.0000}
    )

    add_1 = nw.new_node(
        Nodes.Math, input_kwargs={0: group_input.outputs["height"], 1: 0.0000}
    )

    combine_xyz_4 = nw.new_node(
        Nodes.CombineXYZ,
        input_kwargs={"X": group_input.outputs["width"], "Y": add, "Z": add_1},
    )

    cube_2 = nw.new_node(
        Nodes.MeshCube,
        input_kwargs={
            "Size": combine_xyz_4,
            "Vertices X": 2,
            "Vertices Y": 2,
            "Vertices Z": 2,
        },
    )

    add_2 = nw.new_node(
        Nodes.Math, input_kwargs={0: group_input.outputs["depth"], 1: 0.0000}
    )

    multiply = nw.new_node(
        Nodes.Math, input_kwargs={0: add, 1: -0.5000}, attrs={"operation": "MULTIPLY"}
    )

    multiply_add = nw.new_node(
        Nodes.Math,
        input_kwargs={0: add_2, 1: -0.5000, 2: multiply},
        attrs={"operation": "MULTIPLY_ADD"},
    )

    multiply_1 = nw.new_node(
        Nodes.Math, input_kwargs={0: add_1}, attrs={"operation": "MULTIPLY"}
    )

    combine_xyz_5 = nw.new_node(
        Nodes.CombineXYZ, input_kwargs={"Y": multiply_add, "Z": multiply_1}
    )

    transform_5 = nw.new_node(
        Nodes.Transform, input_kwargs={"Geometry": cube_2, "Translation": combine_xyz_5}
    )

    group_output = nw.new_node(
        Nodes.GroupOutput,
        input_kwargs={"Geometry": transform_5},
        attrs={"is_active_output": True},
    )


@node_utils.to_nodegroup(
    "nodegroup_side_board", singleton=False, type="GeometryNodeTree"
)
def nodegroup_side_board(nw: NodeWrangler):
    # Code generated using version 2.6.4 of the node_transpiler

    group_input = nw.new_node(
        Nodes.GroupInput,
        expose_input=[
            ("NodeSocketFloat", "board_thickness", 0.5000),
            ("NodeSocketFloat", "depth", 0.5000),
            ("NodeSocketFloat", "height", 0.5000),
            ("NodeSocketFloat", "x_translation", 0.0000),
        ],
    )

    add = nw.new_node(
        Nodes.Math, input_kwargs={0: group_input.outputs["board_thickness"], 1: 0.0000}
    )

    add_1 = nw.new_node(
        Nodes.Math, input_kwargs={0: group_input.outputs["depth"], 1: 0.0000}
    )

    add_2 = nw.new_node(
        Nodes.Math, input_kwargs={0: group_input.outputs["height"], 1: 0.0000}
    )

    combine_xyz = nw.new_node(
        Nodes.CombineXYZ, input_kwargs={"X": add, "Y": add_1, "Z": add_2}
    )

    cube = nw.new_node(
        Nodes.MeshCube,
        input_kwargs={
            "Size": combine_xyz,
            "Vertices X": 2,
            "Vertices Y": 2,
            "Vertices Z": 2,
        },
    )

    multiply = nw.new_node(
        Nodes.Math, input_kwargs={0: add_2, 1: 0.5000}, attrs={"operation": "MULTIPLY"}
    )

    combine_xyz_1 = nw.new_node(
        Nodes.CombineXYZ,
        input_kwargs={"X": group_input.outputs["x_translation"], "Z": multiply},
    )

    transform = nw.new_node(
        Nodes.Transform, input_kwargs={"Geometry": cube, "Translation": combine_xyz_1}
    )

    group_output = nw.new_node(
        Nodes.GroupOutput,
        input_kwargs={"Geometry": transform},
        attrs={"is_active_output": True},
    )


def geometry_nodes(nw: NodeWrangler, **kwargs):
    # Code generated using version 2.6.4 of the node_transpiler
    shelf_nodegroup_profile = kwargs.get("shelf_nodegroup_profile")

    side_board_thickness = nw.new_node(Nodes.Value, label="side_board_thickness")
    side_board_thickness.outputs[0].default_value = kwargs["side_board_thickness"]

    shelf_depth = nw.new_node(Nodes.Value, label="shelf_depth")
    shelf_depth.outputs[0].default_value = kwargs["shelf_depth"]

    add = nw.new_node(Nodes.Math, input_kwargs={0: shelf_depth, 1: 0.0040})

    shelf_height = nw.new_node(Nodes.Value, label="shelf_height")
    shelf_height.outputs[0].default_value = kwargs["shelf_height"]

    add_1 = nw.new_node(Nodes.Math, input_kwargs={0: shelf_height, 1: 0.0020})
    add_2 = nw.new_node(Nodes.Math, input_kwargs={0: shelf_height, 1: -0.0010})
    side_boards = []

    for x in kwargs["side_board_x_translation"]:
        side_board_x_translation = nw.new_node(
            Nodes.Value, label="side_board_x_translation"
        )
        side_board_x_translation.outputs[0].default_value = x

        side_board_nodegroup = _profile_shelf_nodegroup(
            shelf_nodegroup_profile,
            "nodegroup_side_board",
            nodegroup_side_board,
            cache_key=("nodegroup_side_board",),
        )
        side_board = nw.new_node(
            side_board_nodegroup.name,
            input_kwargs={
                "board_thickness": side_board_thickness,
                "depth": add,
                "height": add_1,
                "x_translation": side_board_x_translation,
            },
        )
        side_boards.append(side_board)

    shelf_width = nw.new_node(Nodes.Value, label="shelf_width")
    shelf_width.outputs[0].default_value = kwargs["shelf_width"]

    backboard_thickness = nw.new_node(Nodes.Value, label="backboard_thickness")
    backboard_thickness.outputs[0].default_value = kwargs["backboard_thickness"]

    add_side = nw.new_node(
        Nodes.Math, input_kwargs={0: shelf_width, 1: kwargs["side_board_thickness"] * 2}
    )
    back_board_nodegroup = _profile_shelf_nodegroup(
        shelf_nodegroup_profile,
        "nodegroup_back_board",
        nodegroup_back_board,
        cache_key=("nodegroup_back_board",),
    )
    back_board = nw.new_node(
        back_board_nodegroup.name,
        input_kwargs={
            "width": add_side,
            "thickness": backboard_thickness,
            "height": add_2,
            "depth": shelf_depth,
        },
    )

    bottom_board_y_gap = nw.new_node(Nodes.Value, label="bottom_board_y_gap")
    bottom_board_y_gap.outputs[0].default_value = kwargs["bottom_board_y_gap"]

    bottom_board_height = nw.new_node(Nodes.Value, label="bottom_board_height")
    bottom_board_height.outputs[0].default_value = kwargs["bottom_board_height"]

    bottom_boards = []
    for i in range(len(kwargs["shelf_cell_width"])):
        bottom_gap_x_translation = nw.new_node(
            Nodes.Value, label="bottom_gap_x_translation"
        )
        bottom_gap_x_translation.outputs[0].default_value = kwargs[
            "bottom_gap_x_translation"
        ][i]

        shelf_cell_width = nw.new_node(Nodes.Value, label="shelf_cell_width")
        shelf_cell_width.outputs[0].default_value = kwargs["shelf_cell_width"][i]

        bottom_board_nodegroup = _profile_shelf_nodegroup(
            shelf_nodegroup_profile,
            "nodegroup_bottom_board",
            nodegroup_bottom_board,
            cache_key=("nodegroup_bottom_board",),
        )
        bottomboard = nw.new_node(
            bottom_board_nodegroup.name,
            input_kwargs={
                "thickness": side_board_thickness,
                "depth": shelf_depth,
                "y_gap": bottom_board_y_gap,
                "x_translation": bottom_gap_x_translation,
                "height": bottom_board_height,
                "width": shelf_cell_width,
            },
        )

        bottom_boards.append(bottomboard)

    join_geometry = nw.new_node(
        Nodes.JoinGeometry,
        input_kwargs={"Geometry": [back_board] + side_boards + bottom_boards},
    )

    realize_instances = nw.new_node(
        Nodes.RealizeInstances, input_kwargs={"Geometry": join_geometry}
    )

    set_material = nw.new_node(
        Nodes.SetMaterial,
        input_kwargs={
            "Geometry": realize_instances,
            "Material": kwargs["frame_material"],
        },
    )

    division_board_thickness = nw.new_node(
        Nodes.Value, label="division_board_thickness"
    )
    division_board_thickness.outputs[0].default_value = kwargs[
        "division_board_thickness"
    ]

    division_boards = []
    for i in range(len(kwargs["shelf_cell_width"])):
        for j in range(len(kwargs["division_board_z_translation"])):
            division_board_z_translation = nw.new_node(
                Nodes.Value, label="division_board_z_translation"
            )
            division_board_z_translation.outputs[0].default_value = kwargs[
                "division_board_z_translation"
            ][j]

            division_board_x_translation = nw.new_node(
                Nodes.Value, label="division_board_x_translation"
            )
            division_board_x_translation.outputs[0].default_value = kwargs[
                "division_board_x_translation"
            ][i]

            shelf_cell_width = nw.new_node(Nodes.Value, label="shelf_cell_width")
            shelf_cell_width.outputs[0].default_value = kwargs["shelf_cell_width"][i]

            screw_depth_head = nw.new_node(Nodes.Value, label="screw_depth_head")
            screw_depth_head.outputs[0].default_value = kwargs["screw_depth_head"]

            screw_head_radius = nw.new_node(Nodes.Value, label="screw_head_radius")
            screw_head_radius.outputs[0].default_value = kwargs["screw_head_radius"]

            screw_width_gap = nw.new_node(Nodes.Value, label="screw_width_gap")
            screw_width_gap.outputs[0].default_value = kwargs["screw_width_gap"]

            screw_depth_gap = nw.new_node(Nodes.Value, label="screw_depth_gap")
            screw_depth_gap.outputs[0].default_value = kwargs["screw_depth_gap"]

            division_board_nodegroup = _profile_shelf_nodegroup(
                shelf_nodegroup_profile,
                "nodegroup_division_board",
                lambda: nodegroup_division_board(
                    material=kwargs["board_material"],
                    tag_support=kwargs.get("tag_support", False),
                    shelf_nodegroup_profile=shelf_nodegroup_profile,
                ),
            )
            division_board = nw.new_node(
                division_board_nodegroup.name,
                input_kwargs={
                    "thickness": division_board_thickness,
                    "width": shelf_cell_width,
                    "depth": shelf_depth,
                    "z_translation": division_board_z_translation,
                    "x_translation": division_board_x_translation,
                    "screw_depth": screw_depth_head,
                    "screw_radius": screw_head_radius,
                    "screw_width_gap": screw_width_gap,
                    "screw_depth_gap": screw_depth_gap,
                },
            )
            division_boards.append(division_board)

    attach_thickness = nw.new_node(Nodes.Value, label="attach_thickness")
    attach_thickness.outputs[0].default_value = kwargs["attach_thickness"]

    attach_length = nw.new_node(Nodes.Value, label="attach_length")
    attach_length.outputs[0].default_value = kwargs["attach_length"]

    attach_z_translation = nw.new_node(Nodes.Value, label="attach_z_translation")
    attach_z_translation.outputs[0].default_value = kwargs["attach_z_translation"]

    attach_gap = nw.new_node(Nodes.Value, label="attach_gap")
    attach_gap.outputs[0].default_value = kwargs["attach_gap"]

    attach_width = nw.new_node(Nodes.Value, label="attach_width")
    attach_width.outputs[0].default_value = kwargs["attach_width"]

    join_geometry_k = nw.new_node(
        Nodes.JoinGeometry, input_kwargs={"Geometry": division_boards}
    )

    set_material_1 = nw.new_node(
        Nodes.SetMaterial,
        input_kwargs={
            "Geometry": join_geometry_k,
            "Material": kwargs["board_material"],
        },
    )

    join_geometry_3 = nw.new_node(
        Nodes.JoinGeometry, input_kwargs={"Geometry": [set_material, set_material_1]}
    )

    realize_instances_3 = nw.new_node(
        Nodes.RealizeInstances, input_kwargs={"Geometry": join_geometry_3}
    )

    triangulate = nw.new_node(
        "GeometryNodeTriangulate", input_kwargs={"Mesh": realize_instances_3}
    )

    transform = nw.new_node(
        Nodes.Transform,
        input_kwargs={"Geometry": triangulate, "Rotation": (0.0000, 0.0000, -1.5708)},
    )

    group_output = nw.new_node(
        Nodes.GroupOutput,
        input_kwargs={"Geometry": transform},
        attrs={"is_active_output": True},
    )


class LargeShelfBaseFactory(AssetFactory):
    def __init__(self, factory_seed, params={}, coarse=False):
        super(LargeShelfBaseFactory, self).__init__(factory_seed, coarse=coarse)
        self.params = {}

    def sample_params(self):
        return self.params.copy()

    def get_asset_params(self, i=0):
        params = self.sample_params()
        if params.get("shelf_depth", None) is None:
            params["shelf_depth"] = np.clip(normal(0.26, 0.03), 0.18, 0.36)
        if params.get("side_board_thickness", None) is None:
            params["side_board_thickness"] = np.clip(normal(0.02, 0.002), 0.015, 0.025)
        if params.get("back_board_thickness", None) is None:
            params["backboard_thickness"] = 0.01
        if params.get("bottom_board_y_gap", None) is None:
            params["bottom_board_y_gap"] = uniform(0.01, 0.05)
        if params.get("bottom_board_height", None) is None:
            params["bottom_board_height"] = np.clip(
                normal(0.083, 0.01), 0.05, 0.11
            ) * np.random.choice([1.0, 0.0], p=[0.8, 0.2])
        if params.get("division_board_thickness", None) is None:
            params["division_board_thickness"] = np.clip(
                normal(0.02, 0.002), 0.015, 0.025
            )
        if params.get("screw_depth_head", None) is None:
            params["screw_depth_head"] = uniform(0.001, 0.004)
        if params.get("screw_head_radius", None) is None:
            params["screw_head_radius"] = uniform(0.001, 0.004)
        if params.get("screw_width_gap", None) is None:
            params["screw_width_gap"] = uniform(0.0, 0.02)
        if params.get("screw_depth_gap", None) is None:
            params["screw_depth_gap"] = uniform(0.025, 0.06)
        if params.get("attach_length", None) is None:
            params["attach_length"] = uniform(0.05, 0.1)
        if params.get("attach_width", None) is None:
            params["attach_width"] = uniform(0.01, 0.025)
        if params.get("attach_thickness", None) is None:
            params["attach_thickness"] = uniform(0.002, 0.005)
        if params.get("attach_gap", None) is None:
            params["attach_gap"] = uniform(0.0, 0.05)
        if params.get("shelf_cell_width", None) is None:
            num_h_cells = randint(1, 4)
            shelf_cell_width = []
            for i in range(num_h_cells):
                shelf_cell_width.append(
                    np.random.choice([0.76, 0.36], p=[0.5, 0.5])
                    * np.clip(normal(1.0, 0.1), 0.75, 1.25)
                )
            params["shelf_cell_width"] = shelf_cell_width
        if params.get("shelf_cell_height", None) is None:
            num_v_cells = randint(3, 8)
            shelf_cell_height = []
            for i in range(num_v_cells):
                shelf_cell_height.append(0.3 * np.clip(normal(1.0, 0.1), 0.75, 1.25))
            params["shelf_cell_height"] = shelf_cell_height

        params = self.update_translation_params(params)
        if params.get("frame_material", None) is None:
            params["frame_material"] = np.random.choice(
                ["white", "black_wood", "wood"], p=[0.4, 0.3, 0.3]
            )
        if params.get("board_material", None) is None:
            params["board_material"] = params["frame_material"]

        params = self.get_material_func(params)
        params["tag_support"] = True
        return params

    def get_material_func(self, params, randomness=True):
        if params["frame_material"] == "white":
            params["frame_material"] = surface.shaderfunc_to_material(
                shader_shelves_white
            )
        elif params["frame_material"] == "black_wood":
            params["frame_material"] = surface.shaderfunc_to_material(
                shader_shelves_black_wood_z
            )
        elif params["frame_material"] == "wood":
            params["frame_material"] = surface.shaderfunc_to_material(
                shader_shelves_wood_z
            )

        if params["board_material"] == "white":
            params["board_material"] = surface.shaderfunc_to_material(
                shader_shelves_white
            )
        elif params["board_material"] == "black_wood":
            params["board_material"] = surface.shaderfunc_to_material(
                shader_shelves_black_wood
            )
        elif params["board_material"] == "wood":
            params["board_material"] = surface.shaderfunc_to_material(
                shader_shelves_wood
            )

        return params

    def update_translation_params(self, params):
        cell_widths = params["shelf_cell_width"]
        cell_heights = params["shelf_cell_height"]
        side_thickness = params["side_board_thickness"]
        div_thickness = params["division_board_thickness"]

        # get shelf_width and shelf_height
        width = (len(cell_widths) - 1) * side_thickness * 2 + (
            len(cell_widths) - 1
        ) * 0.001
        height = (len(cell_heights) + 1) * div_thickness + params["bottom_board_height"]
        for w in cell_widths:
            width += w
        for h in cell_heights:
            height += h

        params["shelf_width"] = width
        params["shelf_height"] = height
        params["attach_z_translation"] = height - div_thickness

        # get side_board_x_translation
        dist = -(width + side_thickness) / 2.0
        side_board_x_translation = [dist]

        for w in cell_widths:
            dist += side_thickness + w
            side_board_x_translation.append(dist)
            dist += side_thickness + 0.001
            side_board_x_translation.append(dist)
        side_board_x_translation = side_board_x_translation[:-1]

        # get division_board_z_translation
        dist = params["bottom_board_height"] + div_thickness / 2.0
        division_board_z_translation = [dist]
        for h in cell_heights:
            dist += h + div_thickness
            division_board_z_translation.append(dist)

        # get division_board_x_translation
        division_board_x_translation = []
        for i in range(len(cell_widths)):
            division_board_x_translation.append(
                (side_board_x_translation[2 * i] + side_board_x_translation[2 * i + 1])
                / 2.0
            )

        params["side_board_x_translation"] = side_board_x_translation
        params["division_board_x_translation"] = division_board_x_translation
        params["division_board_z_translation"] = division_board_z_translation
        params["bottom_gap_x_translation"] = division_board_x_translation

        return params

    def create_asset(self, i=0, **params):
        bpy.ops.mesh.primitive_plane_add(
            size=1,
            enter_editmode=False,
            align="WORLD",
            location=(0, 0, 0),
            scale=(1, 1, 1),
        )
        obj = bpy.context.active_object

        shelf_nodegroup_profile = _begin_shelf_nodegroup_spawn(self, i)
        profile_success = False
        profile_error_type = ""
        try:
            obj_params = self.get_asset_params(i)
            _update_shelf_nodegroup_spawn_context(shelf_nodegroup_profile, obj_params)
            geomod_kwargs = obj_params
            if shelf_nodegroup_profile is not None:
                geomod_kwargs = obj_params.copy()
                geomod_kwargs["shelf_nodegroup_profile"] = shelf_nodegroup_profile
            surface.add_geomod(
                obj, geometry_nodes, attributes=[], apply=True, input_kwargs=geomod_kwargs
            )
            profile_success = True
        except Exception as exc:
            profile_error_type = exc.__class__.__name__
            raise
        finally:
            _finish_shelf_nodegroup_spawn(
                shelf_nodegroup_profile, profile_success, profile_error_type
            )

        if params.get("ret_params", False):
            return obj, obj_params

        tagging.tag_system.relabel_obj(obj)

        return obj


class LargeShelfFactory(LargeShelfBaseFactory):
    def sample_params(self):
        params = dict()
        params["Dimensions"] = (
            uniform(0.25, 0.35),
            uniform(0.3, 2.0),
            uniform(0.9, 2.0),
        )

        params["bottom_board_height"] = 0.083
        params["shelf_depth"] = params["Dimensions"][0] - 0.01
        num_h = int((params["Dimensions"][2] - 0.083) / 0.3)
        params["shelf_cell_height"] = [
            (params["Dimensions"][2] - 0.083) / num_h for _ in range(num_h)
        ]
        num_v = max(int(params["Dimensions"][1] / 0.5), 1)
        params["shelf_cell_width"] = [
            params["Dimensions"][1] / num_v for _ in range(num_v)
        ]
        return params
