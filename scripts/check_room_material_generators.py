#!/usr/bin/env python3
"""Validate room material assignment entries resolve to callable generators."""

import argparse
import importlib
import os
import sys
import types


def _missing_runtime_modules():
    missing = []
    for module_name in ("numpy", "gin", "bpy"):
        try:
            importlib.import_module(module_name)
        except ImportError:
            missing.append(module_name)
    return missing


def _maybe_reexec_in_infinigen_env():
    missing = _missing_runtime_modules()
    if not missing or os.environ.get("INFINIGEN_ROOM_MATERIAL_CHECK_REEXECED") == "1":
        return

    candidates = [
        os.environ.get("INFINIGEN_PYTHON"),
        "/home/ubuntu22/miniconda3/envs/infinigen/bin/python",
        "/root/miniconda3/envs/infinigen/bin/python",
        "/opt/conda/envs/infinigen/bin/python",
    ]
    current = os.path.realpath(sys.executable)
    for python in candidates:
        if not python:
            continue
        python = os.path.realpath(os.path.expanduser(python))
        if python == current or not os.path.exists(python):
            continue
        env = os.environ.copy()
        env["INFINIGEN_ROOM_MATERIAL_CHECK_REEXECED"] = "1"
        os.execve(python, [python, *sys.argv], env)


_maybe_reexec_in_infinigen_env()

import numpy as np

from infinigen.core.constraints.example_solver.room.decorate import (
    resolve_material_generator,
    room_ceiling_fns,
    room_floor_fns,
    room_wall_fns,
)
from infinigen.core.util.random import weighted_sample


def _room_label(room_key):
    return getattr(room_key, "name", str(room_key))


def _generator_label(obj):
    if isinstance(obj, types.ModuleType):
        return obj.__name__
    module = getattr(obj, "__module__", None)
    name = getattr(obj, "__name__", None)
    if module and name:
        return f"{module}.{name}"
    return repr(obj)


def _object_type(obj):
    if isinstance(obj, types.ModuleType):
        return "module"
    return type(obj).__name__


def _iter_room_registries(mapping):
    yield "__default__", mapping.default_factory()
    for room_key, registry in sorted(mapping.items(), key=lambda item: _room_label(item[0])):
        yield _room_label(room_key), registry


def _check_one(collection_name, room_name, source, sampled_obj):
    context = f"{collection_name}:{room_name}:{source}"
    resolved = resolve_material_generator(sampled_obj, context=context)
    print(
        "\t".join(
            [
                collection_name,
                room_name,
                source,
                _object_type(sampled_obj),
                _generator_label(sampled_obj),
                _generator_label(resolved),
            ]
        )
    )


def check_registry(collection_name, mapping, samples_per_room):
    failures = []
    checked = 0
    for room_name, registry in _iter_room_registries(mapping):
        for index, (entry, _weight) in enumerate(registry):
            try:
                _check_one(collection_name, room_name, f"entry:{index}", entry)
                checked += 1
            except Exception as exc:
                failures.append((collection_name, room_name, f"entry:{index}", exc))

        for index in range(samples_per_room):
            sampled = weighted_sample(registry)
            try:
                _check_one(collection_name, room_name, f"sample:{index}", sampled)
                checked += 1
            except Exception as exc:
                failures.append((collection_name, room_name, f"sample:{index}", exc))

    return checked, failures


def main():
    parser = argparse.ArgumentParser(
        description="Check room floor/wall/ceiling material generators resolve to callables."
    )
    parser.add_argument("--samples-per-room", type=int, default=8)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    np.random.seed(args.seed)

    print(
        "\t".join(
            [
                "collection",
                "room_type",
                "source",
                "sampled_object_type",
                "sampled_object",
                "resolved_callable",
            ]
        )
    )

    registries = [
        ("room_floor_fns", room_floor_fns),
        ("room_wall_fns", room_wall_fns),
        ("room_ceiling_fns", room_ceiling_fns),
    ]
    total_checked = 0
    failures = []
    for collection_name, mapping in registries:
        checked, registry_failures = check_registry(
            collection_name, mapping, args.samples_per_room
        )
        total_checked += checked
        failures.extend(registry_failures)

    if failures:
        print("\nUnresolved room material generators:", file=sys.stderr)
        for collection_name, room_name, source, exc in failures:
            print(
                f"- {collection_name} {room_name} {source}: {type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
        return 1

    print(f"\nResolved {total_checked} room material generator checks.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
