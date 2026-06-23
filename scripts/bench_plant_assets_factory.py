#!/usr/bin/env python3
"""Targeted PlantContainerFactory / LargePlantContainerFactory benchmark."""

from __future__ import annotations

import argparse
import contextlib
import os
import signal
import sys
import time
from pathlib import Path

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

CSV_NAME = "infinigen_plant_assets_timing.csv"
PROFILE_ENV_VAR = "INFINIGEN_PROFILE_PLANT_ASSETS"
CSV_ENV_VAR = "INFINIGEN_PLANT_ASSETS_TIMING_CSV"
GC_TARGET_NAMES = ["objects", "meshes", "textures", "node_groups", "materials", "images"]


def raise_timeout(_signum, _frame):
    raise TimeoutError("sample timed out")


@contextlib.contextmanager
def sample_timeout(seconds: float):
    if seconds <= 0:
        yield
        return
    old_handler = signal.signal(signal.SIGALRM, raise_timeout)
    old_timer = signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old_handler)
        if old_timer[0] > 0:
            signal.setitimer(signal.ITIMER_REAL, old_timer[0], old_timer[1])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=30)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--factory-class",
        choices=("LargePlantContainerFactory", "PlantContainerFactory"),
        default="LargePlantContainerFactory",
    )
    parser.add_argument(
        "--output_folder",
        type=Path,
        default=Path("outputs/bench_plant_assets"),
    )
    parser.add_argument("--csv-path", type=Path, default=None)
    parser.add_argument("--max-factory-seed", type=int, default=100_000_000)
    parser.add_argument("--max-filter-attempts", type=int, default=5000)
    parser.add_argument("--concrete-plant-filter", default="")
    parser.add_argument("--sample_timeout_seconds", type=float, default=300.0)
    return parser.parse_args()


def live_object(obj, bpy_module) -> bool:
    return obj is not None and getattr(obj, "name", "") in bpy_module.data.objects


def delete_object_tree(root, bpy_module, butil_module) -> None:
    if not live_object(root, bpy_module):
        return
    for obj in reversed(list(butil_module.iter_object_tree(root))):
        if live_object(obj, bpy_module):
            butil_module.delete(obj)


def parse_concrete_plant_filter(value: str) -> set[str]:
    return {part.strip() for part in value.split(",") if part.strip()}


def concrete_plant_factory_name(factory) -> str:
    plant_factory = getattr(factory, "plant_factory", None)
    concrete_factory = getattr(plant_factory, "factory", None)
    if concrete_factory is None:
        return ""
    return concrete_factory.__class__.__name__


def benchmark(args: argparse.Namespace) -> int:
    import bpy

    from infinigen.assets.objects.tableware.plant_container import (
        LargePlantContainerFactory,
        PlantContainerFactory,
    )
    from infinigen.core.util import blender as butil

    if args.samples <= 0:
        raise ValueError("--samples must be positive")
    if args.max_factory_seed <= 0:
        raise ValueError("--max-factory-seed must be positive")
    if args.max_filter_attempts <= 0:
        raise ValueError("--max-filter-attempts must be positive")

    factory_classes = {
        "LargePlantContainerFactory": LargePlantContainerFactory,
        "PlantContainerFactory": PlantContainerFactory,
    }
    factory_class = factory_classes[args.factory_class]
    concrete_filter = parse_concrete_plant_filter(args.concrete_plant_filter)
    output_folder = args.output_folder
    output_folder.mkdir(parents=True, exist_ok=True)
    csv_path = args.csv_path or (output_folder / CSV_NAME)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    if csv_path.exists():
        csv_path.unlink()

    os.environ[PROFILE_ENV_VAR] = "1"
    os.environ[CSV_ENV_VAR] = str(csv_path)

    butil.clear_scene()
    rng = np.random.default_rng(args.seed)
    gc_targets = [getattr(bpy.data, name) for name in GC_TARGET_NAMES]
    failures = 0
    total_start = time.perf_counter()

    print("Plant asset targeted benchmark")
    print(f"samples: {args.samples}")
    print(f"seed: {args.seed}")
    print(f"factory_class: {args.factory_class}")
    print(f"output_folder: {output_folder}")
    print(f"timing_csv: {csv_path}")
    print(f"max_factory_seed: {args.max_factory_seed}")
    print(f"concrete_plant_filter: {','.join(sorted(concrete_filter)) or '(none)'}")
    print(f"sample_timeout_seconds: {args.sample_timeout_seconds}")

    sample_index = 0
    attempts = 0
    skipped_by_filter = 0
    while sample_index < args.samples:
        attempts += 1
        if attempts > args.max_filter_attempts:
            raise RuntimeError(
                f"Reached --max-filter-attempts={args.max_filter_attempts} "
                f"with {sample_index}/{args.samples} accepted samples."
            )
        factory_seed = int(rng.integers(0, args.max_factory_seed))
        inst_seed = int(rng.integers(0, 10_000_000))
        factory = None
        placeholder = None
        asset = None
        sample_start = time.perf_counter()

        try:
            with butil.GarbageCollect(
                gc_targets,
                caller="bench_plant_assets_factory",
                generator_class=args.factory_class,
                factory_seed=factory_seed,
                inst_seed=inst_seed,
            ):
                factory = factory_class(factory_seed)
                concrete_name = concrete_plant_factory_name(factory)
                if concrete_filter and concrete_name not in concrete_filter:
                    skipped_by_filter += 1
                    print(
                        f"skip attempt {attempts:03d}: "
                        f"factory_seed={factory_seed} concrete={concrete_name}",
                        flush=True,
                    )
                    continue

                sample_index += 1
                print(
                    f"sample {sample_index:03d}/{args.samples:03d} "
                    f"factory_seed={factory_seed} inst_seed={inst_seed} "
                    f"concrete={concrete_name} starting",
                    flush=True,
                )
                placeholder = factory.spawn_placeholder(
                    inst_seed, loc=(0, 0, 0), rot=(0, 0, 0)
                )
                with sample_timeout(args.sample_timeout_seconds):
                    asset = factory.spawn_asset(inst_seed, placeholder=placeholder)
                delete_object_tree(asset, bpy, butil)
                delete_object_tree(placeholder, bpy, butil)
        except Exception as exc:
            failures += 1
            delete_object_tree(asset, bpy, butil)
            delete_object_tree(placeholder, bpy, butil)
            print(
                f"sample {sample_index:03d}/{args.samples:03d} "
                f"factory_seed={factory_seed} inst_seed={inst_seed} "
                f"failed={exc.__class__.__name__}: {exc}"
            )
        else:
            print(
                f"sample {sample_index:03d}/{args.samples:03d} "
                f"duration={time.perf_counter() - sample_start:.3f}s"
            )

    butil.garbage_collect(gc_targets, keep_in_use=True)
    print(f"total_duration: {time.perf_counter() - total_start:.3f}s")
    print(f"failures: {failures}")
    print(f"attempts: {attempts}")
    print(f"skipped_by_filter: {skipped_by_filter}")
    print(f"timing_csv: {csv_path}")
    return 0


def main() -> None:
    raise SystemExit(benchmark(parse_args()))


if __name__ == "__main__":
    main()
