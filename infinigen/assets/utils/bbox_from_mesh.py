# Copyright (C) 2023, Princeton University.
# This source code is licensed under the BSD 3-Clause license found in the LICENSE file in the root directory
# of this source tree.

# Authors: Alexander Raistrick

import csv
import logging
import os
import time
from pathlib import Path

import bpy
import numpy as np

from infinigen.core.constraints.example_solver import timing as solver_timing
from infinigen.core.nodes import node_utils
from infinigen.core.nodes.node_wrangler import Nodes, NodeWrangler
from infinigen.core.placement.factory import AssetFactory
from infinigen.core.util import blender as butil

logger = logging.getLogger(__name__)

BBOX_TIMING_ENV_VAR = "INFINIGEN_PROFILE_BBOX"
BBOX_TIMING_CSV_NAME = "infinigen_bbox_timing.csv"
DEFAULT_BBOX_TIMING_CSV = Path("/tmp") / BBOX_TIMING_CSV_NAME

BBOX_TIMING_FIELDNAMES = [
    "generator_class",
    "factory_seed",
    "inst_seed",
    "use_pholder",
    "spawn_placeholder_duration",
    "spawn_asset_duration",
    "union_all_bbox_duration",
    "box_from_corners_duration",
    "cleanup_collect_duration",
    "delete_duration",
    "total_duration",
    "success",
    "error_type",
]

_BBOX_TIMING_WRITE_FAILED = False


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _profile_bbox_enabled() -> bool:
    return _env_truthy(BBOX_TIMING_ENV_VAR) or solver_timing.PROFILE_TIMING_ENABLED


def _bbox_timing_csv_path() -> Path:
    output_folder = solver_timing.current_output_folder()
    if output_folder is not None:
        return Path(output_folder) / BBOX_TIMING_CSV_NAME
    return DEFAULT_BBOX_TIMING_CSV


def _write_bbox_timing_row(row: dict):
    global _BBOX_TIMING_WRITE_FAILED

    if _BBOX_TIMING_WRITE_FAILED:
        return

    path = _bbox_timing_csv_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        write_header = not path.exists() or path.stat().st_size == 0
        with path.open("a", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=BBOX_TIMING_FIELDNAMES)
            if write_header:
                writer.writeheader()
            writer.writerow(
                {field: row.get(field, "") for field in BBOX_TIMING_FIELDNAMES}
            )
    except OSError:
        _BBOX_TIMING_WRITE_FAILED = True
        logger.exception("Failed to write bbox timing CSV at %s", path)


def _empty_bbox_timing_row(gen: AssetFactory, inst_seed: int, use_pholder: bool):
    return {
        "generator_class": gen.__class__.__name__,
        "factory_seed": getattr(gen, "factory_seed", ""),
        "inst_seed": inst_seed,
        "use_pholder": use_pholder,
        "spawn_placeholder_duration": 0.0,
        "spawn_asset_duration": 0.0,
        "union_all_bbox_duration": 0.0,
        "box_from_corners_duration": 0.0,
        "cleanup_collect_duration": 0.0,
        "delete_duration": 0.0,
        "total_duration": 0.0,
        "success": False,
        "error_type": "",
    }


def _record_duration(row: dict, field: str, start_time: float):
    row[field] = time.perf_counter() - start_time


@node_utils.to_nodegroup("nodegroup_cube_from_corners", singleton=True)
def nodegroup_cube_from_corners(nw: NodeWrangler):
    # Code generated using version 2.6.5 of the node_transpiler

    group_input = nw.new_node(
        Nodes.GroupInput,
        expose_input=[
            ("NodeSocketVector", "min_corner", (0.0000, 0.0000, 0.0000)),
            ("NodeSocketVector", "max_corner", (0.0000, 0.0000, 0.0000)),
        ],
    )

    subtract = nw.new_node(
        Nodes.VectorMath,
        input_kwargs={
            0: group_input.outputs["max_corner"],
            1: group_input.outputs["min_corner"],
        },
        attrs={"operation": "SUBTRACT"},
    )

    cube = nw.new_node(
        Nodes.MeshCube, input_kwargs={"Size": subtract.outputs["Vector"]}
    )

    mix = nw.new_node(
        Nodes.Mix,
        input_kwargs={
            4: group_input.outputs["min_corner"],
            5: group_input.outputs["max_corner"],
        },
        attrs={"data_type": "VECTOR"},
    )

    transform_geometry = nw.new_node(
        Nodes.Transform,
        input_kwargs={"Geometry": cube.outputs["Mesh"], "Translation": mix.outputs[1]},
    )

    group_output = nw.new_node(
        Nodes.GroupOutput, input_kwargs={"Geometry": transform_geometry}
    )


def union_all_bbox(obj: bpy.types.Object):
    mins, maxs = None, None
    for oc in butil.iter_object_tree(obj):
        if not oc.type == "MESH":
            continue
        points = butil.apply_matrix_world(oc, np.array(oc.bound_box))
        pmins, pmaxs = points.min(axis=0), points.max(axis=0)
        mins = pmins if mins is None else np.minimum(pmins, mins)
        maxs = pmaxs if maxs is None else np.maximum(pmins, mins)

    return mins, maxs


def box_from_corners(min_corner, max_corner):
    bbox = butil.modify_mesh(
        butil.spawn_vert(),
        "NODES",
        apply=True,
        node_group=nodegroup_cube_from_corners(),
        ng_inputs=dict(min_corner=min_corner, max_corner=max_corner),
    )

    return bbox


def bbox_mesh_from_hipoly(gen: AssetFactory, inst_seed: int, use_pholder=False):
    if _profile_bbox_enabled():
        return _bbox_mesh_from_hipoly_timed(gen, inst_seed, use_pholder)

    objs = []
    objs.append(gen.spawn_placeholder(inst_seed, loc=(0, 0, 0), rot=(0, 0, 0)))
    if not use_pholder:
        objs.append(gen.spawn_asset(inst_seed, placeholder=objs[-1]))

    min_corner, max_corner = union_all_bbox(objs[-1])

    if (
        min_corner is None
        or max_corner is None
        or np.abs(min_corner - max_corner).sum() < 1e-5
    ):
        raise ValueError(
            f"{gen} spawned {objs[-1].name=} with total bbox {min_corner, max_corner}, invalid"
        )

    bbox = box_from_corners(min_corner, max_corner)

    cleanup = set()
    for o in objs:
        cleanup.update(butil.iter_object_tree(o))
    butil.delete(list(cleanup))

    bbox.name = (
        f"{gen.__class__.__name__}({gen.factory_seed}).bbox_placeholder({inst_seed})"
    )
    return bbox


def _bbox_mesh_from_hipoly_timed(
    gen: AssetFactory, inst_seed: int, use_pholder=False
):
    row = _empty_bbox_timing_row(gen, inst_seed, use_pholder)
    total_start_time = time.perf_counter()
    objs = []

    try:
        step_start_time = time.perf_counter()
        objs.append(gen.spawn_placeholder(inst_seed, loc=(0, 0, 0), rot=(0, 0, 0)))
        _record_duration(row, "spawn_placeholder_duration", step_start_time)

        if not use_pholder:
            step_start_time = time.perf_counter()
            objs.append(gen.spawn_asset(inst_seed, placeholder=objs[-1]))
            _record_duration(row, "spawn_asset_duration", step_start_time)

        step_start_time = time.perf_counter()
        min_corner, max_corner = union_all_bbox(objs[-1])
        _record_duration(row, "union_all_bbox_duration", step_start_time)

        if (
            min_corner is None
            or max_corner is None
            or np.abs(min_corner - max_corner).sum() < 1e-5
        ):
            raise ValueError(
                f"{gen} spawned {objs[-1].name=} with total bbox {min_corner, max_corner}, invalid"
            )

        step_start_time = time.perf_counter()
        bbox = box_from_corners(min_corner, max_corner)
        _record_duration(row, "box_from_corners_duration", step_start_time)

        step_start_time = time.perf_counter()
        cleanup = set()
        for o in objs:
            cleanup.update(butil.iter_object_tree(o))
        _record_duration(row, "cleanup_collect_duration", step_start_time)

        step_start_time = time.perf_counter()
        butil.delete(list(cleanup))
        _record_duration(row, "delete_duration", step_start_time)

        bbox.name = (
            f"{gen.__class__.__name__}({gen.factory_seed}).bbox_placeholder({inst_seed})"
        )
        row["success"] = True
        return bbox
    except BaseException as exc:
        row["error_type"] = exc.__class__.__name__
        raise
    finally:
        row["total_duration"] = time.perf_counter() - total_start_time
        _write_bbox_timing_row(row)
