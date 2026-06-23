# Copyright (C) 2023, Princeton University.
# This source code is licensed under the BSD 3-Clause license found in the LICENSE file in the root directory of this source tree.

# Authors: Alex Raistrick, Zeyu Ma, Lahav Lipson, Hei Law, Lingjie Mei, Karhan Kayan


import csv
import json
import logging
import os
import re
import sys
import time
from collections import Counter
from contextlib import nullcontext
from itertools import chain, count
from math import prod
from pathlib import Path

# ruff: noqa: I001
# must import bpy before bmesh
import bpy
import gin
import bmesh
import mathutils
import numpy as np
import trimesh
from mathutils import Vector
from tqdm import tqdm

from infinigen.core.nodes.node_info import DATATYPE_DIMS, DATATYPE_FIELDS

from . import math as mutil
from .logging import Suppress

logger = logging.getLogger(__name__)

GC_TIMING_ENV_VAR = "INFINIGEN_PROFILE_GC"
GC_TIMING_CSV_NAME = "infinigen_gc_timing.csv"
DEFAULT_GC_TIMING_CSV = Path("/tmp") / GC_TIMING_CSV_NAME
GC_NODE_GROUP_INTERVAL_ENV_VAR = "INFINIGEN_GC_NODE_GROUP_INTERVAL"
GC_BATCH_REMOVE_NODE_GROUPS_ENV_VAR = "INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS"

GC_TIMING_FIELDNAMES = [
    "row_type",
    "context_id",
    "caller",
    "generator_class",
    "factory_seed",
    "inst_seed",
    "target_count",
    "keep_in_use",
    "keep_orig",
    "enter_total_duration",
    "exit_total_duration",
    "total_duration",
    "success",
    "error_type",
    "phase",
    "target_name",
    "target_len_before",
    "target_len_after",
    "keep_names_count",
    "scanned_count",
    "skipped_in_use_count",
    "skipped_keep_name_count",
    "skipped_no_gc_count",
    "removed_count",
    "removed_name_count",
    "removed_name_prefix_top",
    "removed_name_sample",
    "removed_name_unique_prefix_count",
    "remove_duration",
    "remove_mode",
    "batch_remove_enabled",
    "batch_remove_count",
    "batch_remove_duration",
    "individual_remove_duration",
    "node_group_interval",
    "node_group_cleanup_skipped",
    "node_group_cleanup_due",
    "effective_cleanup",
    "duration",
]

_GC_TIMING_CONTEXT_COUNTER = count(1)
_GC_TIMING_WRITE_FAILED = False
_GC_NODE_GROUP_CLEANUP_COUNTER = 0
_GC_NODE_GROUP_INTERVAL_WARNING_EMITTED = False
_NODE_GROUP_NUMERIC_SUFFIX_RE = re.compile(r"\.\d{3,}$")
GC_REMOVED_NAME_SAMPLE_LIMIT = 20
GC_REMOVED_NAME_PREFIX_LIMIT = 20


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _profile_gc_enabled() -> bool:
    return _env_truthy(GC_TIMING_ENV_VAR) or _env_truthy("INFINIGEN_PROFILE_TIMING")


def _gc_batch_remove_node_groups_enabled() -> bool:
    return _env_truthy(GC_BATCH_REMOVE_NODE_GROUPS_ENV_VAR)


def _gc_node_group_interval() -> int:
    raw_value = os.environ.get(GC_NODE_GROUP_INTERVAL_ENV_VAR)
    if raw_value is None or raw_value.strip() == "":
        return 1

    try:
        interval = int(raw_value)
    except ValueError:
        _warn_invalid_gc_node_group_interval(raw_value)
        return 1

    if interval <= 0:
        _warn_invalid_gc_node_group_interval(raw_value)
        return 1
    return interval


def _warn_invalid_gc_node_group_interval(raw_value):
    global _GC_NODE_GROUP_INTERVAL_WARNING_EMITTED

    if _GC_NODE_GROUP_INTERVAL_WARNING_EMITTED:
        return
    _GC_NODE_GROUP_INTERVAL_WARNING_EMITTED = True
    logger.warning(
        "%s must be a positive integer; got %r. Falling back to 1.",
        GC_NODE_GROUP_INTERVAL_ENV_VAR,
        raw_value,
    )


def _gc_timing_csv_path() -> Path:
    solver_timing = sys.modules.get(
        "infinigen.core.constraints.example_solver.timing"
    )
    if solver_timing is not None:
        current_output_folder = getattr(solver_timing, "current_output_folder", None)
        if current_output_folder is not None:
            output_folder = current_output_folder()
            if output_folder is not None:
                return Path(output_folder) / GC_TIMING_CSV_NAME
    return DEFAULT_GC_TIMING_CSV


def _write_gc_timing_row(row: dict):
    global _GC_TIMING_WRITE_FAILED

    if _GC_TIMING_WRITE_FAILED:
        return

    path = _gc_timing_csv_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        write_header = not path.exists() or path.stat().st_size == 0
        with path.open("a", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=GC_TIMING_FIELDNAMES)
            if write_header:
                writer.writeheader()
            writer.writerow(
                {field: row.get(field, "") for field in GC_TIMING_FIELDNAMES}
            )
    except OSError:
        _GC_TIMING_WRITE_FAILED = True
        logger.exception("Failed to write GarbageCollect timing CSV at %s", path)


def _gc_metadata(
    caller=None,
    generator_class=None,
    factory_seed=None,
    inst_seed=None,
    metadata=None,
):
    row_metadata = {
        "caller": "unknown",
        "generator_class": "",
        "factory_seed": "",
        "inst_seed": "",
    }
    if metadata:
        for field in row_metadata:
            if field in metadata and metadata[field] is not None:
                row_metadata[field] = metadata[field]
    explicit_values = {
        "caller": caller,
        "generator_class": generator_class,
        "factory_seed": factory_seed,
        "inst_seed": inst_seed,
    }
    for field, value in explicit_values.items():
        if value is not None:
            row_metadata[field] = value
    return row_metadata


def _safe_len(value):
    try:
        return len(value)
    except Exception:
        return ""


def _bpy_data_target_name(target) -> str:
    for name in (
        "objects",
        "collections",
        "movieclips",
        "particles",
        "meshes",
        "curves",
        "armatures",
        "node_groups",
        "textures",
        "materials",
        "images",
    ):
        try:
            candidate = getattr(bpy.data, name, None)
            if candidate is target or candidate == target:
                return name
        except Exception:
            continue

    target_name = getattr(target, "name", "")
    if target_name:
        return str(target_name)
    return target.__class__.__name__


def _is_bpy_data_node_groups(target) -> bool:
    try:
        node_groups = bpy.data.node_groups
        return target is node_groups or target == node_groups
    except Exception:
        return False


def _use_batch_remove_for_target(target) -> bool:
    return _gc_batch_remove_node_groups_enabled() and _is_bpy_data_node_groups(target)


def _node_group_cleanup_decision(target, interval):
    global _GC_NODE_GROUP_CLEANUP_COUNTER

    if not _is_bpy_data_node_groups(target):
        return {
            "node_group_cleanup_skipped": False,
            "node_group_cleanup_due": "",
            "effective_cleanup": True,
        }

    if interval <= 1:
        return {
            "node_group_cleanup_skipped": False,
            "node_group_cleanup_due": True,
            "effective_cleanup": True,
        }

    _GC_NODE_GROUP_CLEANUP_COUNTER += 1
    cleanup_due = _GC_NODE_GROUP_CLEANUP_COUNTER % interval == 0
    return {
        "node_group_cleanup_skipped": not cleanup_due,
        "node_group_cleanup_due": cleanup_due,
        "effective_cleanup": cleanup_due,
    }


def _node_group_name_prefix(name: str) -> str:
    return _NODE_GROUP_NUMERIC_SUFFIX_RE.sub("", name)


def _gc_removed_name_summary(prefix_counts, sample):
    if not prefix_counts and not sample:
        return {
            "removed_name_count": 0,
            "removed_name_prefix_top": "",
            "removed_name_sample": "",
            "removed_name_unique_prefix_count": 0,
        }

    return {
        "removed_name_count": sum(prefix_counts.values()),
        "removed_name_prefix_top": json.dumps(
            prefix_counts.most_common(GC_REMOVED_NAME_PREFIX_LIMIT)
        ),
        "removed_name_sample": json.dumps(sample[:GC_REMOVED_NAME_SAMPLE_LIMIT]),
        "removed_name_unique_prefix_count": len(prefix_counts),
    }


def _empty_gc_target_timing_row(
    context_id, phase, target, node_group_interval, metadata=None
):
    row = {
        "row_type": "target",
        "context_id": context_id,
        "phase": phase,
        "target_name": _bpy_data_target_name(target),
        "target_len_before": "",
        "target_len_after": "",
        "keep_names_count": "",
        "scanned_count": 0,
        "skipped_in_use_count": 0,
        "skipped_keep_name_count": 0,
        "skipped_no_gc_count": 0,
        "removed_count": 0,
        "removed_name_count": "",
        "removed_name_prefix_top": "",
        "removed_name_sample": "",
        "removed_name_unique_prefix_count": "",
        "remove_duration": 0.0,
        "remove_mode": "individual",
        "batch_remove_enabled": False,
        "batch_remove_count": 0,
        "batch_remove_duration": 0.0,
        "individual_remove_duration": 0.0,
        "node_group_interval": node_group_interval,
        "node_group_cleanup_skipped": False,
        "node_group_cleanup_due": "",
        "effective_cleanup": "",
        "duration": 0.0,
    }
    if metadata:
        row.update(metadata)
    return row


def _snapshot_gc_targets_timed(targets, context_id, metadata=None):
    names = []
    node_group_interval = _gc_node_group_interval()
    for target in targets:
        row = _empty_gc_target_timing_row(
            context_id, "enter_snapshot", target, node_group_interval, metadata
        )
        row["target_len_before"] = _safe_len(target)
        captured_names = set()
        start_time = time.perf_counter()
        try:
            for obj in target:
                name = obj.name
                captured_names.add(name)
                row["scanned_count"] += 1
            names.append(captured_names)
        finally:
            row["target_len_after"] = _safe_len(target)
            row["keep_names_count"] = len(captured_names)
            row["duration"] = time.perf_counter() - start_time
            _write_gc_timing_row(row)
    return names


def _garbage_collect_timed(
    targets,
    keep_in_use=True,
    keep_names=None,
    verbose=False,
    context_id="",
    metadata=None,
):
    if keep_names is None:
        keep_names = [[]] * len(targets)

    node_group_interval = _gc_node_group_interval()
    for target, orig in zip(targets, keep_names):
        row = _empty_gc_target_timing_row(
            context_id, "exit_cleanup", target, node_group_interval, metadata
        )
        cleanup_decision = _node_group_cleanup_decision(target, node_group_interval)
        row.update(cleanup_decision)
        row["target_len_before"] = _safe_len(target)
        row["keep_names_count"] = _safe_len(orig)
        batch_remove_enabled = _use_batch_remove_for_target(target)
        row["batch_remove_enabled"] = batch_remove_enabled
        if batch_remove_enabled:
            row["remove_mode"] = "batch_remove"
        track_removed_names = row["target_name"] == "node_groups"
        removed_name_prefix_counts = Counter()
        removed_name_sample = []
        to_remove = []
        start_time = time.perf_counter()
        try:
            if row["effective_cleanup"]:
                for obj in target:
                    row["scanned_count"] += 1
                    if keep_in_use and obj.users > 0:
                        row["skipped_in_use_count"] += 1
                        continue
                    name = obj.name
                    if name in orig:
                        row["skipped_keep_name_count"] += 1
                        continue
                    if "(no gc)" in name:
                        row["skipped_no_gc_count"] += 1
                        continue
                    if verbose:
                        print(f"Garbage collecting {obj} from {target}")
                    if track_removed_names:
                        removed_name_prefix_counts[_node_group_name_prefix(name)] += 1
                        if len(removed_name_sample) < GC_REMOVED_NAME_SAMPLE_LIMIT:
                            removed_name_sample.append(name)
                    row["removed_count"] += 1
                    if batch_remove_enabled:
                        to_remove.append(obj)
                    else:
                        remove_start_time = time.perf_counter()
                        try:
                            target.remove(obj)
                        finally:
                            remove_duration = time.perf_counter() - remove_start_time
                            row["individual_remove_duration"] += remove_duration
                            row["remove_duration"] += remove_duration
                if batch_remove_enabled and to_remove:
                    row["batch_remove_count"] = len(to_remove)
                    remove_start_time = time.perf_counter()
                    try:
                        bpy.data.batch_remove(to_remove)
                    finally:
                        remove_duration = time.perf_counter() - remove_start_time
                        row["batch_remove_duration"] += remove_duration
                        row["remove_duration"] += remove_duration
        finally:
            if track_removed_names:
                row.update(
                    _gc_removed_name_summary(
                        removed_name_prefix_counts, removed_name_sample
                    )
                )
            row["target_len_after"] = _safe_len(target)
            row["duration"] = time.perf_counter() - start_time
            _write_gc_timing_row(row)


@gin.configurable("geometry")
def set_geometry_option(material, option="BUMP"):
    if hasattr(material, "displacement_method"):
        material.displacement_method = option
    else:
        material.cycles.displacement_method = option


def deep_clone_obj(obj, keep_modifiers=False, keep_materials=False):
    new_obj = obj.copy()
    new_obj.data = obj.data.copy()
    if not keep_modifiers:
        for mod in new_obj.modifiers:
            new_obj.modifiers.remove(mod)
    if not keep_materials:
        while len(new_obj.data.materials) > 0:
            new_obj.data.materials.pop()
    bpy.context.collection.objects.link(new_obj)
    return new_obj


copy = deep_clone_obj


def get_all_bpy_data_targets():
    D = bpy.data
    return [
        D.objects,
        D.collections,
        D.movieclips,
        D.particles,
        D.meshes,
        D.curves,
        D.armatures,
        D.node_groups,
    ]


class ViewportMode:
    def __init__(self, obj, mode):
        self.obj = obj
        self.mode = mode

    def __enter__(self):
        self.orig_active = bpy.context.active_object
        bpy.context.view_layer.objects.active = self.obj
        self.orig_mode = bpy.context.object.mode
        bpy.ops.object.mode_set(mode=self.mode)

    def __exit__(self, *args):
        bpy.context.view_layer.objects.active = self.obj
        bpy.ops.object.mode_set(mode=self.orig_mode)
        bpy.context.view_layer.objects.active = self.orig_active


class CursorLocation:
    def __init__(self, loc):
        self.loc = loc
        self.saved = None

    def __enter__(self):
        self.saved = bpy.context.scene.cursor.location
        bpy.context.scene.cursor.location = self.loc

    def __exit__(self, *_):
        bpy.context.scene.cursor.location = self.saved


class SelectObjects:
    def __init__(self, objects, active=0):
        self.objects = list(objects) if hasattr(objects, "__iter__") else [objects]
        self.active = active

        self.saved_objs = None
        self.saved_active = None

    def _check_selectable(self):
        unlinked = [o for o in self.objects if o.name not in bpy.context.scene.objects]
        if len(unlinked) > 0:
            raise ValueError(
                f"{SelectObjects.__name__} had objects {unlinked=} which are not in bpy.context.scene.objects and cannot be selected"
            )

        hidden = [o for o in self.objects if o.hide_viewport]
        if len(hidden) > 0:
            raise ValueError(
                f"{SelectObjects.__name__} had objects {hidden=} which are hidden and cannot be selected"
            )

    def _get_intended_active(self):
        if isinstance(self.active, int):
            if self.active >= len(self.objects):
                return None
            else:
                return self.objects[self.active]
        else:
            return self.active

    def _validate(self, error=False):
        if error:

            def msg(str):
                raise ValueError(str)
        else:
            msg = logger.warning

        difference = set(self.objects) - set(bpy.context.selected_objects)
        if len(difference):
            msg(
                f"{SelectObjects.__name__} failed to select {self.objects=}, result was {bpy.context.selected_objects=}. "
                "The most common cause is that the objects are in a collection with col.hide_viewport=True"
            )

        intended = self._get_intended_active()
        if intended is not None and bpy.context.active_object != intended:
            msg(
                f"{SelectObjects.__name__} failed to set active object to {intended=}, result was {bpy.context.active_object=}"
            )

    def __enter__(self):
        self.saved_objects = list(bpy.context.selected_objects)
        self.saved_active = bpy.context.active_object

        select_none()
        select(self.objects)

        intended = self._get_intended_active()
        if intended is not None:
            bpy.context.view_layer.objects.active = intended

        self._validate()

    def __exit__(self, *_):
        # our saved selection / active objects may have been deleted, update them to only include valid ones
        def enforce_not_deleted(o):
            try:
                return o if o.name in bpy.data.objects else None
            except ReferenceError:
                return None

        self.saved_objects = [enforce_not_deleted(o) for o in self.saved_objects]
        self.saved_objects = [o for o in self.saved_objects if o is not None]

        select_none()
        select(self.saved_objects)
        if self.saved_active is not None:
            bpy.context.view_layer.objects.active = enforce_not_deleted(
                self.saved_active
            )


class DisableModifiers:
    def __init__(self, objs, keep=[]):
        self.objs = objs if isinstance(objs, list) else [objs]
        self.keep = keep
        self.modifiers_disabled = []

    def __enter__(self):
        for o in self.objs:
            for m in o.modifiers:
                if not m.show_viewport or m in self.keep:
                    continue
                self.modifiers_disabled.append(m)
                m.show_viewport = False

    def __exit__(self, *_):
        for m in self.modifiers_disabled:
            m.show_viewport = True


class EnableParentCollections:
    def __init__(self, objs, target_key="hide_viewport", target_value=False):
        self.objs = objs
        self.target_key = target_key
        self.target_value = target_value

    def __enter__(self):
        self.enable_cols = set(
            chain.from_iterable([o.users_collection for o in self.objs])
        )
        self.enable_cols_startstate = [
            getattr(c, self.target_key) for c in self.enable_cols
        ]

        for c in self.enable_cols:
            setattr(c, self.target_key, self.target_value)

    def __exit__(self, *_, **__):
        for c, s in zip(self.enable_cols, self.enable_cols_startstate):
            setattr(c, self.target_key, s)


class TemporaryObject:
    def __init__(self, obj):
        self.obj = obj

    def __enter__(self):
        return self.obj

    def __exit__(self, *_):
        if self.obj.name in bpy.data.objects:
            delete(self.obj)


def garbage_collect(targets, keep_in_use=True, keep_names=None, verbose=False):
    if keep_names is None:
        keep_names = [[]] * len(targets)

    if _profile_gc_enabled():
        _garbage_collect_timed(
            targets,
            keep_in_use=keep_in_use,
            keep_names=keep_names,
            verbose=verbose,
            context_id=f"direct-{next(_GC_TIMING_CONTEXT_COUNTER)}",
            metadata=_gc_metadata(caller="garbage_collect"),
        )
        return

    node_group_interval = _gc_node_group_interval()
    throttle_node_groups = node_group_interval > 1
    for t, orig in zip(targets, keep_names):
        if throttle_node_groups and _is_bpy_data_node_groups(t):
            cleanup_decision = _node_group_cleanup_decision(t, node_group_interval)
            if not cleanup_decision["effective_cleanup"]:
                continue
        if _use_batch_remove_for_target(t):
            to_remove = []
            for o in t:
                if keep_in_use and o.users > 0:
                    continue
                if o.name in orig:
                    continue
                if "(no gc)" in o.name:
                    continue
                if verbose:
                    print(f"Garbage collecting {o} from {t}")
                to_remove.append(o)
            if to_remove:
                bpy.data.batch_remove(to_remove)
            continue
        for o in t:
            if keep_in_use and o.users > 0:
                continue
            if o.name in orig:
                continue
            if "(no gc)" in o.name:
                continue
            if verbose:
                print(f"Garbage collecting {o} from {t}")
            t.remove(o)


class GarbageCollect:
    def __init__(
        self,
        targets=None,
        keep_in_use=True,
        keep_orig=True,
        verbose=False,
        caller=None,
        generator_class=None,
        factory_seed=None,
        inst_seed=None,
        metadata=None,
    ):
        self.targets = targets or get_all_bpy_data_targets()
        self.keep_in_use = keep_in_use
        self.keep_orig = keep_orig
        self.verbose = verbose
        self._gc_metadata = _gc_metadata(
            caller=caller,
            generator_class=generator_class,
            factory_seed=factory_seed,
            inst_seed=inst_seed,
            metadata=metadata,
        )
        self.caller = self._gc_metadata["caller"]
        self._gc_timing_enabled = False
        self._gc_context_id = ""
        self._gc_enter_duration = 0.0
        self._gc_exit_duration = 0.0

    def _write_context_timing_row(self, success, error_type=""):
        if not self._gc_timing_enabled:
            return

        total_duration = self._gc_enter_duration + self._gc_exit_duration

        _write_gc_timing_row(
            {
                "row_type": "context",
                "context_id": self._gc_context_id,
                **self._gc_metadata,
                "target_count": _safe_len(self.targets),
                "keep_in_use": self.keep_in_use,
                "keep_orig": self.keep_orig,
                "enter_total_duration": self._gc_enter_duration,
                "exit_total_duration": self._gc_exit_duration,
                "total_duration": total_duration,
                "success": success,
                "error_type": error_type,
                "node_group_interval": _gc_node_group_interval(),
            }
        )

    def __enter__(self):
        self._gc_timing_enabled = _profile_gc_enabled()
        if not self._gc_timing_enabled:
            self.names = [set(o.name for o in t) for t in self.targets]
            return

        self._gc_context_id = next(_GC_TIMING_CONTEXT_COUNTER)
        start_time = time.perf_counter()
        try:
            self.names = _snapshot_gc_targets_timed(
                self.targets, self._gc_context_id, self._gc_metadata
            )
        except BaseException as exc:
            self._gc_enter_duration = time.perf_counter() - start_time
            self._write_context_timing_row(False, exc.__class__.__name__)
            raise
        else:
            self._gc_enter_duration = time.perf_counter() - start_time

    def __exit__(self, exc_type, exc_value, traceback):
        if not self._gc_timing_enabled:
            garbage_collect(
                self.targets,
                keep_in_use=self.keep_in_use,
                keep_names=self.names,
                verbose=self.verbose,
            )
            return

        start_time = time.perf_counter()
        try:
            _garbage_collect_timed(
                self.targets,
                keep_in_use=self.keep_in_use,
                keep_names=self.names,
                verbose=self.verbose,
                context_id=self._gc_context_id,
                metadata=self._gc_metadata,
            )
        except BaseException as exc:
            self._gc_exit_duration = time.perf_counter() - start_time
            self._write_context_timing_row(False, exc.__class__.__name__)
            raise
        else:
            self._gc_exit_duration = time.perf_counter() - start_time
            success = exc_type is None
            error_type = "" if exc_type is None else exc_type.__name__
            self._write_context_timing_row(success, error_type)


def select_none():
    if hasattr(bpy.context, "active_object") and bpy.context.active_object is not None:
        bpy.context.active_object.select_set(False)
    if hasattr(bpy.context, "selected_objects"):
        for obj in bpy.context.selected_objects:
            obj.select_set(False)


def select(objs: bpy.types.Object | list[bpy.types.Object]):
    select_none()
    if not isinstance(objs, list):
        objs = [objs]
    for o in objs:
        if o.name not in bpy.context.scene.objects:
            raise ValueError(f"Object {o.name=} not in scene and cant be selected")
        o.select_set(True)


def delete(objs: bpy.types.Object | list[bpy.types.Object]):
    if not isinstance(objs, list):
        objs = [objs]
    select_none()
    for obj in objs:
        select(obj)
        is_mesh = obj.type == "MESH"
        if is_mesh:
            mesh = obj.data
        with Suppress():
            bpy.ops.object.delete()
        if is_mesh and mesh.users == 0:
            bpy.data.meshes.remove(mesh)


def delete_collection(collection: bpy.types.Collection):
    if collection.name in bpy.data.collections:
        objects = collection.objects
        bpy.data.collections.remove(collection)
        for o in objects:
            delete_collection(o)
    else:
        delete(collection)


def traverse_children(obj, fn):
    fn(obj)
    for obj in obj.children:
        fn(obj)


def iter_object_tree(obj):
    yield obj
    for c in obj.children:
        yield from iter_object_tree(c)


def get_collection(name, reuse=True):
    if reuse and name in bpy.data.collections:
        return bpy.data.collections[name]
    else:
        col = bpy.data.collections.new(name=name)
        bpy.context.scene.collection.children.link(col)
        return col


def unlink(obj):
    if not isinstance(obj, list):
        obj = [obj]
    for o in obj:
        for c in list(bpy.data.collections) + [bpy.context.scene.collection]:
            if o.name in c.objects:
                c.objects.unlink(o)


def put_in_collection(objs, collection, exclusive=True):
    if isinstance(collection, str):
        collection = get_collection(collection)
    if isinstance(objs, bpy.types.Object):
        objs = [objs]
    else:
        objs = list(objs)
    for o in objs:
        if exclusive:
            unlink(o)
        collection.objects.link(o)
    return collection


def group_in_collection(objs, name: str, reuse=True, **kwargs):
    """
    objs: List of (None | Blender Object | List[Blender Object])
    """

    collection = get_collection(name, reuse=reuse)

    for obj in objs:
        if obj is None:
            continue
        if not isinstance(obj, list):
            obj = [obj]
        for child in obj:
            traverse_children(
                child, lambda obj: put_in_collection(obj, collection, **kwargs)
            )

    return collection


def group_toplevel_collections(
    keyword, hide_viewport=False, hide_render=False, reuse=True
):
    scenecol = bpy.context.scene.collection
    matches = [
        c for c in scenecol.children if c.name.startswith(keyword) and keyword != c.name
    ]

    parent = get_collection(keyword, reuse=reuse)
    if parent.name not in scenecol.children:
        scenecol.children.link(parent)

    for c in matches:
        scenecol.children.unlink(c)
        parent.children.link(c)

    parent.hide_viewport = hide_viewport
    parent.hide_render = hide_render


def spawn_empty(name, disp_type="PLAIN_AXES", s=0.1):
    empty = bpy.data.objects.new(name, None)
    bpy.context.scene.collection.objects.link(empty)
    empty.empty_display_size = s
    empty.empty_display_type = disp_type
    return empty


def spawn_point_cloud(name, pts, edges=None):
    if edges is None:
        edges = []

    mesh = bpy.data.meshes.new(name=name)
    mesh.from_pydata(pts, edges, [])
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def spawn_vert(name="vert"):
    return spawn_point_cloud(name, np.zeros((1, 3)))


def spawn_line(name, pts):
    idxs = np.arange(len(pts))
    edges = np.stack([idxs[:-1], idxs[1:]], axis=-1)
    return spawn_point_cloud(name, pts, edges=edges)


def spawn_plane(**kwargs):
    name = kwargs.pop("name", None)
    bpy.ops.mesh.primitive_plane_add(enter_editmode=False, align="WORLD", **kwargs)
    obj = bpy.context.active_object
    if name is not None:
        obj.name = name
    return obj


def spawn_cube(size=1, location=(0, 0, 0), scale=(1, 1, 1), name=None):
    bpy.ops.mesh.primitive_cube_add(
        size=size,
        enter_editmode=False,
        align="WORLD",
        location=location,
        scale=scale,
    )
    obj = bpy.context.active_object
    if name is not None:
        obj.name = name
    return obj


def spawn_cylinder(
    radius=1.0, depth=2.0, location=(0, 0, 0), scale=(1, 1, 1), name=None
):
    bpy.ops.mesh.primitive_cylinder_add(
        radius=radius,
        depth=depth,
        enter_editmode=False,
        align="WORLD",
        location=location,
        scale=scale,
    )
    obj = bpy.context.active_object
    if name is not None:
        obj.name = name
    return obj


def spawn_sphere(radius=1, location=(0, 0, 0), scale=(1, 1, 1), name=None):
    bpy.ops.mesh.primitive_uv_sphere_add(
        radius=radius,
        enter_editmode=False,
        align="WORLD",
        location=location,
        scale=scale,
    )
    obj = bpy.context.active_object
    if name is not None:
        obj.name = name
    return obj


def spawn_icosphere(radius=1, location=(0, 0, 0), scale=(1, 1, 1), name=None):
    bpy.ops.mesh.primitive_ico_sphere_add(
        radius=radius,
        enter_editmode=False,
        align="WORLD",
        location=location,
        scale=scale,
    )
    obj = bpy.context.active_object
    if name is not None:
        obj.name = name
    return obj


def clear_scene(keep=[], targets=None, materials=True):
    D = bpy.data
    if targets is None:
        targets = get_all_bpy_data_targets()

    if materials:
        targets.append(D.materials)

    for t in targets:
        if t in keep:
            continue
        for o in t:
            if o in keep or o.name in keep:
                continue
            t.remove(o)

    with Suppress():
        bpy.ops.ptcache.free_bake_all()


def spawn_capsule(rad, height, us=32, vs=16):
    mesh = bpy.data.meshes.new("Capsule")
    obj = bpy.data.objects.new("Capsule", mesh)
    bpy.context.collection.objects.link(obj)

    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=us, v_segments=vs, radius=rad)

    for v in bm.verts:
        if v.co.z > 0:
            v.co.z += height

    bm.to_mesh(mesh)
    bm.free()

    select_none()
    obj.select_set(True)
    bpy.ops.object.shade_smooth()

    return obj


def to_mesh(object, context=bpy.context):
    deg = context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(object.evaluated_get(deg), depsgraph=deg)

    new_obj = bpy.data.objects.new(object.name + "_mesh", me)
    context.collection.objects.link(new_obj)

    for o in context.selected_objects:
        o.select_set(False)

    new_obj.matrix_world = object.matrix_world
    new_obj.select_set(True)
    context.view_layer.objects.active = new_obj

    return new_obj


def get_camera_res():
    d = np.array(
        [bpy.context.scene.render.resolution_x, bpy.context.scene.render.resolution_y],
        dtype=np.float32,
    )
    d *= bpy.context.scene.render.resolution_percentage / 100.0
    return d


def set_geomod_inputs(mod, inputs: dict):
    assert mod.type == "NODES"
    for k, v in inputs.items():
        inputs = {
            s.name: s
            for s in mod.node_group.interface.items_tree
            if s.in_out == "INPUT"
        }
        if k not in inputs:
            raise KeyError(f"Couldnt find {k=} in {inputs=}")
        soc = inputs[k]

        if not hasattr(soc, "default_value"):
            if v is not None:
                raise ValueError(
                    f"Got non-None value {v=} for {soc.identifier=} which has no default value"
                )
            continue
        elif v is None:
            continue

        if isinstance(soc.default_value, (float, int)):
            v = type(soc.default_value)(v)
        if isinstance(v, np.ndarray):
            v = v.tolist()

        try:
            mod[soc.identifier] = v
        except TypeError as e:
            print(
                f"Error incurred while assigning {v} with {type(v)=} to {soc.identifier=} of {mod.name=}"
            )
            raise e


def modify_mesh(
    obj,
    type,
    apply=True,
    name=None,
    return_mod=False,
    ng_inputs=None,
    show_viewport=None,
    **kwargs,
) -> bpy.types.Object:
    if name is None:
        name = f"modify_mesh({type}, **{kwargs})"
    if show_viewport is None:
        show_viewport = not apply

    mod = obj.modifiers.new(name, type)
    mod.show_viewport = show_viewport

    if mod is None:
        raise ValueError(
            f"modifer.new() returned None, ensure {obj.type=} is valid for modifier {type=}"
        )

    for k, v in kwargs.items():
        setattr(mod, k, v)
    if ng_inputs is not None:
        assert type == "NODES"
        assert "node_group" in kwargs
        set_geomod_inputs(mod, ng_inputs)

    if apply:
        apply_modifiers(obj, mod=mod)

    if return_mod:
        return obj, mod if not apply else None
    else:
        return obj


def constrain_object(obj, type, **kwargs):
    c = obj.constraints.new(type=type)
    for k, v in kwargs.items():
        setattr(c, k, v)
    return c


def apply_transform(obj, loc=False, rot=True, scale=True):
    with SelectObjects(obj):
        bpy.ops.object.transform_apply(location=loc, rotation=rot, scale=scale)


def import_mesh(path, **kwargs):
    path = Path(path)

    ext = path.parts[-1].split(".")[-1]
    ext = ext.lower().strip()

    funcs = {
        "obj": bpy.ops.wm.obj_import,
        "fbx": bpy.ops.import_scene.fbx,
        "stl": bpy.ops.import_mesh.stl,
        "ply": bpy.ops.wm.ply_import,
        "usdc": bpy.ops.wm.usd_import,
    }

    if ext not in funcs:
        raise ValueError(
            f"butil.import_mesh does not yet support extension {ext}, please contact the developer"
        )

    select_none()
    with Suppress():
        funcs[ext](filepath=str(path), **kwargs)

    if len(bpy.context.selected_objects) > 1 if ext != "usdc" else 2:
        print(
            f"Warning: {ext.upper()} Import produced {len(bpy.context.selected_objects)} objects, "
            f"but only the first is returned by import_obj"
        )
    if ext != "usdc":
        return bpy.context.selected_objects[0]
    else:
        return next(o for o in bpy.context.selected_objects if o.type != "EMPTY")


def boolean(objs, mode="UNION", verbose=False):
    keep, *rest = list(objs)

    if verbose:
        rest = tqdm(rest, desc=f"butil.boolean({keep.name}..., {mode=})")

    with SelectObjects(keep):
        for target in rest:
            if len(target.modifiers) != 0:
                raise ValueError(
                    f"Attempted to boolean() with {target=} which still has {len(target.modifiers)=}"
                )

            mod = keep.modifiers.new(type="BOOLEAN", name="butil.boolean()")
            mod.operation = mode
            mod.object = target
            bpy.ops.object.modifier_apply(modifier=mod.name)

    return keep


def split_object(obj, mode="LOOSE"):
    select_none()
    select(obj)
    bpy.ops.mesh.separate(type=mode)
    return list(bpy.context.selected_objects)


def move_modifier(obj, mod, i):
    with SelectObjects(obj):
        bpy.ops.object.modifier_move_to_index(modifier=mod.name, index=i)


def join_objects(objs, check_attributes=False):
    if check_attributes:
        # make sure objs[0] has slots to recieve all the attributes of objs[1:]
        join_target = objs[0]
        for obj in objs:
            for att in obj.data.attributes:
                if att.name in join_target.data.attributes:
                    target_att = join_target.data.attributes[att.name]
                    assert att.data_type == target_att.data_type
                    assert att.domain == target_att.domain
                else:
                    join_target.data.attributes.new(att.name, att.data_type, att.domain)

    empty_objs = [o for o in objs if len(o.data.vertices) == 0]
    objs = [o for o in objs if len(o.data.vertices) > 0]
    delete(empty_objs)

    select(objs)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.object.join()
    return bpy.context.active_object


def clear_mesh(obj):
    with ViewportMode(obj, mode="EDIT"):
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.mesh.delete(type="VERT")


def apply_modifiers(obj, mod=None, quiet=True):
    if mod is None:
        mod = list(obj.modifiers)
    if not isinstance(mod, list):
        mod = [mod]
    for i, v in enumerate(mod):
        if isinstance(v, str):
            mod[i] = obj.modifiers[v]
    con = Suppress() if quiet else nullcontext()
    with SelectObjects(obj), con:
        for m in mod:
            mod_type = m.type
            try:
                bpy.ops.object.modifier_apply(modifier=m.name)
            except RuntimeError as e:
                if mod_type == "NODES":
                    logging.warning(
                        f"apply_modifers on {obj.name=} {m.name=} raised {e}, ignoring and returning empty mesh for pre-3.5 compatibility reasons"
                    )
                    bpy.ops.object.modifier_remove(modifier=m.name)
                    clear_mesh(obj)
                else:
                    raise e

    # geometry nodes occasionally introduces empty material slots in 3.6, we consider this an error and remove them
    purge_empty_materials(obj)

    # geometry nodes occasionally introduces empty material slots in 3.6, we consider this an error and remove them
    purge_empty_materials(obj)


def recalc_normals(obj, inside=False):
    with ViewportMode(obj, mode="EDIT"):
        bpy.ops.mesh.select_all()
        bpy.ops.mesh.normals_make_consistent(inside=inside)


def save_blend(path, autopack=False, verbose=False):
    if verbose:
        print(f"Saving .blend to {path} ({'with' if autopack else 'without'} textures)")

    with Suppress():
        if autopack:
            bpy.ops.file.autopack_toggle()
        bpy.ops.wm.save_as_mainfile(filepath=str(path))
        if autopack:
            bpy.ops.file.autopack_toggle()


def joined_kd(objs, include_origins=False):
    if not isinstance(objs, list):
        objs = objs
    objs = [o for o in objs if o.type == "MESH"]

    size = sum(len(o.data.vertices) for o in objs)
    if include_origins:
        size += len(objs)
    kd = mathutils.kdtree.KDTree(size)

    i = 0
    for o in objs:
        for v in o.data.vertices:
            assert i < size
            kd.insert(o.matrix_world @ v.co, i)
            i += 1
        if include_origins:
            kd.insert(o.location, i)
            i += 1

    kd.balance()

    return kd


def make_instances_real():
    bpy.ops.object.select_all(action="DESELECT")
    for obj in bpy.data.objects:
        if len(obj.particle_systems) == 0:
            continue

        obj.select_set(True)
        bpy.ops.object.duplicates_make_real()
        obj.select_set(False)
    bpy.ops.object.select_all(action="DESELECT")


# faces are required to be triangles now
def objectdata_from_VF(vertices, faces):
    new_mesh = bpy.data.meshes.new("")
    new_mesh.vertices.add(len(vertices))
    new_mesh.vertices.foreach_set("co", vertices.reshape(-1).astype(np.float32))
    new_mesh.polygons.add(len(faces))
    new_mesh.loops.add(len(faces) * 3)
    new_mesh.polygons.foreach_set("loop_total", np.ones(len(faces), np.int32) * 3)
    new_mesh.polygons.foreach_set(
        "loop_start", np.arange(len(faces), dtype=np.int32) * 3
    )
    new_mesh.polygons.foreach_set("vertices", faces.reshape(-1).astype(np.int32))
    new_mesh.update(calc_edges=True)
    return new_mesh


def object_from_VF(vertices, faces, name):
    new_mesh = objectdata_from_VF(vertices, faces)
    new_object = bpy.data.objects.new(name, new_mesh)
    new_object.rotation_euler = (0, 0, 0)
    return new_object


def object_from_trimesh(mesh, name, material=None):
    if name in bpy.data.objects.keys():
        print("replacing original object")
        delete(bpy.data.objects[name])
    new_object = object_from_VF(mesh.vertices, mesh.faces, name)
    for attr_name in mesh.vertex_attributes:
        attr_name_ls = attr_name.lstrip("_")  # this is because of trimesh bug
        if (
            mesh.vertex_attributes[attr_name].ndim == 1
            or mesh.vertex_attributes[attr_name].shape[1] == 1
        ):
            type_key = "FLOAT"
        elif mesh.vertex_attributes[attr_name].shape[1] == 3:
            type_key = "FLOAT_VECTOR"
        elif mesh.vertex_attributes[attr_name].shape[1] == 4:
            type_key = "FLOAT_COLOR"
        else:
            raise Exception(
                f"attribute of shape {mesh.vertex_attributes[attr_name].shape} not supported"
            )
        new_object.data.attributes.new(name=attr_name_ls, type=type_key, domain="POINT")
        new_object.data.attributes[attr_name_ls].data.foreach_set(
            DATATYPE_FIELDS[type_key],
            mesh.vertex_attributes[attr_name].reshape(-1).astype(np.float32),
        )
    if material is not None:
        new_object.data.materials.append(material)
    return new_object


def object_to_vertex_attributes(obj):
    vertex_attributes = {}
    for attr in obj.data.attributes.keys():
        type_key = obj.data.attributes[attr].data_type
        tmp = np.zeros(
            len(obj.data.vertices) * DATATYPE_DIMS[type_key], dtype=np.float32
        )
        obj.data.attributes[attr].data.foreach_get(DATATYPE_FIELDS[type_key], tmp)
        vertex_attributes[attr] = tmp.reshape((len(obj.data.vertices), -1))
    return vertex_attributes


def object_to_trimesh(obj):
    verts_bpy = obj.data.vertices
    faces_bpy = obj.data.polygons
    verts = np.zeros((len(verts_bpy) * 3), dtype=float)
    verts_bpy.foreach_get("co", verts)
    faces = np.zeros((len(faces_bpy) * 3), dtype=np.int32)
    faces_bpy.foreach_get("vertices", faces)
    faces = faces.reshape((-1, 3))
    mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=False)
    vertex_attributes = object_to_vertex_attributes(obj)
    mesh.vertex_attributes.update(vertex_attributes)
    return mesh


def blender_internal_attr(a):
    if hasattr(a, "name"):
        a = a.name
    if a.startswith("."):
        return True
    if a in ["material_index", "uv_map", "UVMap", "sharp_face"]:
        return True
    return False


def merge_by_distance(obj, face_size):
    with SelectObjects(obj), ViewportMode(obj, mode="EDIT"), Suppress():
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.mesh.remove_doubles(threshold=face_size)


def origin_set(objs, mode, **kwargs):
    with SelectObjects(objs):
        bpy.ops.object.origin_set(type=mode, **kwargs)


def apply_geo(obj):
    with SelectObjects(obj):
        for m in obj.modifiers:
            m.show_viewport = False
        for m in obj.modifiers:
            if m.type == "NODES":
                bpy.ops.object.modifier_apply(modifier=m.name)


def avg_approx_vol(objects):
    return np.mean([prod(list(o.dimensions)) for o in objects])


def parent_to(
    a, b, type="OBJECT", keep_transform=False, no_inverse=False, no_transform=False
):
    if a.name == b.name:
        raise ValueError(f"parent_to expects two distinct objects, got {a=} {b=}")

    select_none()
    with SelectObjects([a, b], active=1):
        if no_inverse:
            bpy.ops.object.parent_no_inverse_set(keep_transform=keep_transform)
        else:
            bpy.ops.object.parent_set(type=type, keep_transform=keep_transform)

    if no_transform:
        a.location = (0, 0, 0)
        a.rotation_euler = (0, 0, 0)

    if a.parent is not b:
        raise ValueError(
            f"parent_to({a=}, {b=}) failed, after execution we saw {a.parent=}"
        )


def apply_matrix_world(obj, verts: np.array):
    return mutil.dehomogenize(mutil.homogenize(verts) @ np.array(obj.matrix_world).T)


def surface_area(obj: bpy.types.Object):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    area = sum(f.calc_area() for f in bm.faces)
    bm.free()
    return area


def approve_all_drivers():
    # 'Touch' every driver in the file so that blender trusts them

    n = 0

    for o in bpy.data.objects:
        if o.animation_data is None:
            continue
        for d in o.animation_data.drivers:
            d.driver.expression = d.driver.expression
            n += 1

    logging.warning(
        f"Re-initialized {n} as trusted. Do not run infinigen on untrusted blend files. "
    )


def count_objects():
    count = 0
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        count += 1
    return count


def count_instance():
    depsgraph = bpy.context.evaluated_depsgraph_get()
    return len([inst for inst in depsgraph.object_instances if inst.is_instance])


def bounds(obj):
    points = np.array(obj.bound_box)
    return points.min(axis=0), points.max(axis=0)


def create_noise_plane(size=50, cuts=10, std=3, levels=3):
    bpy.ops.mesh.primitive_grid_add(size=size, x_subdivisions=cuts, y_subdivisions=cuts)
    obj = bpy.context.active_object

    for v in obj.data.vertices:
        v.co[2] = v.co[2] + np.random.normal(0, std)

    return modify_mesh(obj, "SUBSURF", levels=levels)


def purge_empty_materials(obj):
    with SelectObjects(obj):
        for i, m in enumerate(obj.material_slots):
            if m.material is not None:
                continue
            bpy.context.object.active_material_index = i
            bpy.ops.object.material_slot_remove()


def global_polygon_normal(obj, polygon, rev_normal=False):
    loc, rot, scale = obj.matrix_world.decompose()
    rot = rot.to_matrix()
    normal = rot @ polygon.normal
    if rev_normal:
        normal = -normal
    return normal / np.linalg.norm(normal)


def global_vertex_coordinates(obj, local_vertex) -> Vector:
    return obj.matrix_world @ local_vertex.co
