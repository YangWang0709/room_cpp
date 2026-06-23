# Copyright (C) 2023, Princeton University.
# This source code is licensed under the BSD 3-Clause license found in the LICENSE file in the root directory
# of this source tree.

# Authors:
# - Alexander Raistrick: AssetFactory, make_asset_collection
# - Lahav Lipson: quickly_resample


import csv
import logging
import os
import sys
import time
import typing
from pathlib import Path

import bpy
import numpy as np
from tqdm import trange

from infinigen.assets.utils.object import center
from infinigen.core.util import blender as butil
from infinigen.core.util.math import FixedSeed, int_hash

from . import detail

logger = logging.getLogger(__name__)

ASSET_FACTORY_TIMING_ENV_VAR = "INFINIGEN_PROFILE_ASSET_FACTORY"
ASSET_FACTORY_TIMING_CSV_NAME = "infinigen_asset_factory_timing.csv"
DEFAULT_ASSET_FACTORY_TIMING_CSV = (
    Path("/tmp") / ASSET_FACTORY_TIMING_CSV_NAME
)

ASSET_FACTORY_TIMING_FIELDNAMES = [
    "generator_class",
    "factory_seed",
    "inst_seed",
    "user_provided_placeholder",
    "distance",
    "vis_distance",
    "spawn_placeholder_duration",
    "finalize_placeholders_duration",
    "asset_parameters_duration",
    "create_asset_duration",
    "parent_or_transform_duration",
    "delete_placeholder_duration",
    "garbage_collect_context_duration",
    "total_duration",
    "success",
    "error_type",
]

_ASSET_FACTORY_TIMING_WRITE_FAILED = False


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _profile_asset_factory_enabled() -> bool:
    return (
        _env_truthy(ASSET_FACTORY_TIMING_ENV_VAR)
        or _env_truthy("INFINIGEN_PROFILE_TIMING")
    )


def _asset_factory_timing_csv_path() -> Path:
    solver_timing = sys.modules.get(
        "infinigen.core.constraints.example_solver.timing"
    )
    if solver_timing is not None:
        current_output_folder = getattr(
            solver_timing, "current_output_folder", None
        )
        if current_output_folder is not None:
            output_folder = current_output_folder()
            if output_folder is not None:
                return Path(output_folder) / ASSET_FACTORY_TIMING_CSV_NAME
    return DEFAULT_ASSET_FACTORY_TIMING_CSV


def _write_asset_factory_timing_row(row: dict):
    global _ASSET_FACTORY_TIMING_WRITE_FAILED

    if _ASSET_FACTORY_TIMING_WRITE_FAILED:
        return

    path = _asset_factory_timing_csv_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        write_header = not path.exists() or path.stat().st_size == 0
        with path.open("a", newline="") as handle:
            writer = csv.DictWriter(
                handle, fieldnames=ASSET_FACTORY_TIMING_FIELDNAMES
            )
            if write_header:
                writer.writeheader()
            writer.writerow(
                {
                    field: row.get(field, "")
                    for field in ASSET_FACTORY_TIMING_FIELDNAMES
                }
            )
    except OSError:
        _ASSET_FACTORY_TIMING_WRITE_FAILED = True
        logger.exception("Failed to write asset factory timing CSV at %s", path)


def _record_duration(row: dict, field: str, start_time: float):
    row[field] = row.get(field, 0.0) + time.perf_counter() - start_time


def _empty_asset_factory_timing_row(
    factory: "AssetFactory",
    inst_seed: int,
    placeholder,
    distance,
    vis_distance,
):
    return {
        "generator_class": factory.__class__.__name__,
        "factory_seed": getattr(factory, "factory_seed", ""),
        "inst_seed": inst_seed,
        "user_provided_placeholder": placeholder is not None,
        "distance": "" if distance is None else distance,
        "vis_distance": vis_distance,
        "spawn_placeholder_duration": 0.0,
        "finalize_placeholders_duration": 0.0,
        "asset_parameters_duration": 0.0,
        "create_asset_duration": 0.0,
        "parent_or_transform_duration": 0.0,
        "delete_placeholder_duration": 0.0,
        "garbage_collect_context_duration": 0.0,
        "total_duration": 0.0,
        "success": False,
        "error_type": "",
    }


def _gc_attribution_kwargs(factory: "AssetFactory", inst_seed: int) -> dict:
    if not butil._profile_gc_enabled():
        return {}
    return {
        "generator_class": factory.__class__.__name__,
        "factory_seed": getattr(factory, "factory_seed", ""),
        "inst_seed": inst_seed,
    }


class AssetFactory:
    def __init__(self, factory_seed=None, coarse=False):
        self.factory_seed = factory_seed
        if self.factory_seed is None:
            self.factory_seed = np.random.randint(1e9)

        self.coarse = coarse

        logger.debug(f"{self}.__init__()")

    def __repr__(self):
        return f"{self.__class__.__name__}({self.factory_seed})"

    @staticmethod
    def quickly_resample(obj):
        assert obj.type == "EMPTY", obj.type
        obj.rotation_euler[2] = np.random.uniform(-np.pi, np.pi)

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        # Optionally, override this function to decide what will be used as a placeholder for your asset
        return butil.spawn_cube(size=2)

    def finalize_placeholders(self, placeholders: typing.List[bpy.types.Object]):
        # Optionally, override this function to perform any operations on all the placeholders at once
        # eg joint space colonization, placing vines between trees
        pass

    def asset_parameters(self, distance: float, vis_distance: float) -> dict:
        # Optionally, override to determine the **params input of create_asset w.r.t. camera distance
        return {
            "face_size": detail.target_face_size(distance),
            "distance": distance,
            "vis_distance": vis_distance,
        }

    def create_asset(self, **params) -> bpy.types.Object:
        # Override this function to produce a high detail asset
        raise NotImplementedError

    def finalize_assets(self, assets):
        # Optionally, override this function to perform any operations on all the assets at once
        # eg any cleanup / grouping
        pass

    def spawn_placeholder(self, i, loc, rot):
        # Not intended to be overridden - override create_placeholder instead

        logger.debug(f"{self}.spawn_placeholder({i}...)")

        with FixedSeed(int_hash((self.factory_seed, i))):
            obj = self.create_placeholder(i=i, loc=loc, rot=rot)

        has_sensitive_constraint = any(
            c.type in ["FOLLOW_PATH"] for c in obj.constraints
        )

        if not has_sensitive_constraint:
            obj.location = loc
            obj.rotation_euler = rot
        else:
            logger.debug(
                f"Not assigning placeholder {obj.name=} location due to presence of"
                "location-sensitive constraint, typically a follow curve"
            )
        obj.name = f"{repr(self)}.spawn_placeholder({i})"

        if obj.parent is not None:
            logger.warning(
                f"{obj.name=} has no-none parent {obj.parent.name=}, this may cause it not to get populated"
            )

        return obj

    def spawn_asset(
        self,
        i,
        placeholder=None,
        distance=None,
        vis_distance=0,
        loc=(0, 0, 0),
        rot=(0, 0, 0),
        **kwargs,
    ):
        if not isinstance(i, int):
            raise TypeError(f"{i=} {type(i)=}, expected int")
        # Not intended to be overridden - override create_asset instead

        logger.debug(f"{self}.spawn_asset({i}...)")

        if _profile_asset_factory_enabled():
            return self._spawn_asset_timed(
                i,
                placeholder=placeholder,
                distance=distance,
                vis_distance=vis_distance,
                loc=loc,
                rot=rot,
                **kwargs,
            )

        if distance is None:
            distance = detail.scatter_res_distance()

        if self.coarse:
            raise ValueError(
                "Attempted to spawn_asset() on an AssetFactory(coarse=True)"
            )

        user_provided_placeholder = placeholder is not None

        if user_provided_placeholder:
            assert loc == (0, 0, 0) and rot == (0, 0, 0)
        else:
            placeholder = self.spawn_placeholder(i=i, loc=loc, rot=rot)
            self.finalize_placeholders([placeholder])

        gc_targets = [
            bpy.data.meshes,
            bpy.data.textures,
            bpy.data.node_groups,
            bpy.data.materials,
        ]

        export_path = None
        with (
            FixedSeed(int_hash((self.factory_seed, i))),
            butil.GarbageCollect(
                gc_targets,
                verbose=False,
                caller="AssetFactory.spawn_asset",
                **_gc_attribution_kwargs(self, i),
            ),
        ):
            params = self.asset_parameters(distance, vis_distance)
            params.update(kwargs)
            obj = self.create_asset(i=i, placeholder=placeholder, **params)
            # TODO: clean this up
            if "export" in params and params["export"]:
                obj, export_path, semantic_mapping = obj
                assert export_path

        obj.name = f"{repr(self)}.spawn_asset({i})"

        if user_provided_placeholder:
            if obj is not placeholder:
                if obj.parent is None:
                    butil.parent_to(obj, placeholder, no_inverse=True)
            else:
                obj.hide_render = False
        else:
            obj.parent = None
            obj.location = placeholder.location
            obj.rotation_euler = placeholder.rotation_euler
            butil.delete(placeholder)

        if export_path is not None:
            return obj, export_path, semantic_mapping
        return obj

    def _spawn_asset_timed(
        self,
        i,
        placeholder=None,
        distance=None,
        vis_distance=0,
        loc=(0, 0, 0),
        rot=(0, 0, 0),
        **kwargs,
    ):
        row = _empty_asset_factory_timing_row(
            self, i, placeholder, distance, vis_distance
        )
        total_start_time = time.perf_counter()
        export_path = None

        try:
            if distance is None:
                distance = detail.scatter_res_distance()
            row["distance"] = distance

            if self.coarse:
                raise ValueError(
                    "Attempted to spawn_asset() on an AssetFactory(coarse=True)"
                )

            user_provided_placeholder = placeholder is not None

            if user_provided_placeholder:
                assert loc == (0, 0, 0) and rot == (0, 0, 0)
            else:
                step_start_time = time.perf_counter()
                try:
                    placeholder = self.spawn_placeholder(i=i, loc=loc, rot=rot)
                finally:
                    _record_duration(
                        row, "spawn_placeholder_duration", step_start_time
                    )

                step_start_time = time.perf_counter()
                try:
                    self.finalize_placeholders([placeholder])
                finally:
                    _record_duration(
                        row,
                        "finalize_placeholders_duration",
                        step_start_time,
                    )

            gc_targets = [
                bpy.data.meshes,
                bpy.data.textures,
                bpy.data.node_groups,
                bpy.data.materials,
            ]

            fixed_seed = FixedSeed(int_hash((self.factory_seed, i)))
            gc_context = butil.GarbageCollect(
                gc_targets,
                verbose=False,
                caller="AssetFactory.spawn_asset",
                **_gc_attribution_kwargs(self, i),
            )

            with fixed_seed:
                step_start_time = time.perf_counter()
                try:
                    gc_context.__enter__()
                finally:
                    _record_duration(
                        row,
                        "garbage_collect_context_duration",
                        step_start_time,
                    )

                try:
                    step_start_time = time.perf_counter()
                    try:
                        params = self.asset_parameters(distance, vis_distance)
                        params.update(kwargs)
                    finally:
                        _record_duration(
                            row, "asset_parameters_duration", step_start_time
                        )

                    step_start_time = time.perf_counter()
                    try:
                        obj = self.create_asset(
                            i=i, placeholder=placeholder, **params
                        )
                        # TODO: clean this up
                        if "export" in params and params["export"]:
                            obj, export_path, semantic_mapping = obj
                            assert export_path
                    finally:
                        _record_duration(
                            row, "create_asset_duration", step_start_time
                        )
                except BaseException:
                    exc_info = sys.exc_info()
                    step_start_time = time.perf_counter()
                    try:
                        suppress = gc_context.__exit__(*exc_info)
                    finally:
                        _record_duration(
                            row,
                            "garbage_collect_context_duration",
                            step_start_time,
                        )
                    if not suppress:
                        raise
                else:
                    step_start_time = time.perf_counter()
                    try:
                        gc_context.__exit__(None, None, None)
                    finally:
                        _record_duration(
                            row,
                            "garbage_collect_context_duration",
                            step_start_time,
                        )

            step_start_time = time.perf_counter()
            try:
                obj.name = f"{repr(self)}.spawn_asset({i})"

                if user_provided_placeholder:
                    if obj is not placeholder:
                        if obj.parent is None:
                            butil.parent_to(obj, placeholder, no_inverse=True)
                    else:
                        obj.hide_render = False
                else:
                    obj.parent = None
                    obj.location = placeholder.location
                    obj.rotation_euler = placeholder.rotation_euler
            finally:
                _record_duration(
                    row, "parent_or_transform_duration", step_start_time
                )

            if not user_provided_placeholder:
                step_start_time = time.perf_counter()
                try:
                    butil.delete(placeholder)
                finally:
                    _record_duration(
                        row, "delete_placeholder_duration", step_start_time
                    )

            row["success"] = True
            if export_path is not None:
                return obj, export_path, semantic_mapping
            return obj
        except BaseException as exc:
            row["error_type"] = exc.__class__.__name__
            raise
        finally:
            row["total_duration"] = time.perf_counter() - total_start_time
            _write_asset_factory_timing_row(row)

    __call__ = spawn_asset  # for convinience

    def post_init(self):
        pass


def make_asset_collection(
    spawn_fns,
    n,
    name=None,
    weights=None,
    as_list=False,
    verbose=True,
    centered=False,
    **kwargs,
):
    if not isinstance(spawn_fns, list):
        spawn_fns = [spawn_fns]
    if weights is None:
        weights = np.ones(len(spawn_fns))
    weights /= sum(weights)

    if name is None:
        name = ",".join([repr(f) for f in spawn_fns])

    if verbose:
        logger.info(f"Generating collection of {n} assets from {name}")

    objs = [[] for _ in range(len(spawn_fns))]
    r = trange(n) if verbose else range(n)
    for i in r:
        fn_idx = np.random.choice(np.arange(len(spawn_fns)), p=weights)
        obj = spawn_fns[fn_idx](i=i, **kwargs)
        if centered:
            obj.location = -center(obj)
            butil.apply_transform(obj, True)
        objs[fn_idx].append(obj)

    for os, f in zip(objs, spawn_fns):
        if hasattr(f, "finalize_assets"):
            f.finalize_assets(os)

    objs = sum(objs, start=[])

    if as_list:
        return objs
    else:
        col = butil.group_in_collection(objs, name=f"assets:{name}", reuse=False)
        col.hide_viewport = True
        col.hide_render = True
        return col
