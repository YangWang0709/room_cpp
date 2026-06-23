#!/usr/bin/env python3
"""Targeted NatureShelfTrinketsFactory create_asset benchmark."""

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

CSV_NAME = "infinigen_nature_shelf_trinkets_timing.csv"
PROFILE_ENV_VAR = "INFINIGEN_PROFILE_NATURE_SHELF_TRINKETS"
CSV_ENV_VAR = "INFINIGEN_NATURE_SHELF_TRINKETS_TIMING_CSV"
FAST_STABLE_POSE_ENV_VAR = "INFINIGEN_FAST_NATURE_TRINKET_STABLE_POSE"
GC_TARGET_NAMES = ["objects", "meshes", "textures", "node_groups", "materials"]


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


def parse_bool(value: str) -> bool:
    value = value.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise argparse.ArgumentTypeError(
        "expected one of true/false, yes/no, on/off, or 1/0"
    )


def parse_base_factory_filter(value: str | None) -> set[str]:
    if not value:
        return set()
    return {item.strip() for item in value.split(",") if item.strip()}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate isolated NatureShelfTrinketsFactory samples and collect "
            "per-create_asset timing rows."
        )
    )
    parser.add_argument("--samples", type=int, default=100)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--output_folder",
        type=Path,
        default=Path("outputs/bench_nature_shelf_trinkets"),
    )
    parser.add_argument(
        "--base-factory-filter",
        default="",
        help=(
            "Optional comma-separated wrapped base factory class names, for "
            "example CoralFactory,ClamFactory,MusselFactory. The benchmark "
            "uses seed rejection and does not override NatureShelfTrinkets "
            "base-factory selection."
        ),
    )
    parser.add_argument(
        "--keep-blend",
        type=parse_bool,
        default=False,
        help=(
            "Save a .blend with the last successful sample left in the scene. "
            "Defaults to false."
        ),
    )
    parser.add_argument(
        "--csv-path",
        type=Path,
        default=None,
        help=(
            "Optional explicit timing CSV path. Defaults to "
            "<output_folder>/infinigen_nature_shelf_trinkets_timing.csv."
        ),
    )
    parser.add_argument(
        "--sample_timeout_seconds",
        type=float,
        default=300.0,
        help=(
            "Per-sample wall-clock timeout. Use 0 to disable. Timeouts are "
            "recorded as failed timing rows and the benchmark continues."
        ),
    )
    return parser.parse_args()


def live_object(obj, bpy_module) -> bool:
    return obj is not None and getattr(obj, "name", "") in bpy_module.data.objects


def delete_object_tree(root, bpy_module, butil_module) -> None:
    if not live_object(root, bpy_module):
        return
    objects = list(butil_module.iter_object_tree(root))
    for obj in reversed(objects):
        if live_object(obj, bpy_module):
            butil_module.delete(obj)


def place_visual_sample(asset, placeholder, sample_index: int) -> None:
    columns = 6
    spacing = 0.35
    offset = (
        (sample_index % columns) * spacing,
        (sample_index // columns) * spacing,
        0.0,
    )
    for root in (asset, placeholder):
        if root is None:
            continue
        root.location.x += offset[0]
        root.location.y += offset[1]
    if placeholder is not None:
        placeholder.display_type = "WIRE"
        placeholder.hide_render = True


def benchmark(args: argparse.Namespace) -> int:
    # Import bpy-dependent modules only after argparse so py_compile remains simple
    # and the script can show argument help without Blender side effects.
    import bpy

    from infinigen.assets.objects.elements.nature_shelf_trinkets.generate import (
        NatureShelfTrinketsFactory,
    )
    from infinigen.core.util import blender as butil
    from infinigen.core.util.math import FixedSeed, int_hash

    if args.samples <= 0:
        raise ValueError("--samples must be positive")

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
    base_factory_filter = parse_base_factory_filter(args.base_factory_filter)
    if base_factory_filter:
        available_base_factories = {
            factory_class.__name__
            for factory_class in NatureShelfTrinketsFactory.factories
        }
        unknown_base_factories = base_factory_filter - available_base_factories
        if unknown_base_factories:
            raise ValueError(
                "Unknown --base-factory-filter entries: "
                f"{', '.join(sorted(unknown_base_factories))}. "
                f"Available: {', '.join(sorted(available_base_factories))}"
            )

    failures = 0
    skipped = 0
    total_start = time.perf_counter()
    kept_any = False

    print("NatureShelfTrinketsFactory targeted benchmark")
    print(f"samples: {args.samples}")
    print(f"seed: {args.seed}")
    print(f"output_folder: {output_folder}")
    print(f"timing_csv: {csv_path}")
    print(
        "base_factory_filter: "
        f"{','.join(sorted(base_factory_filter)) if base_factory_filter else '(none)'}"
    )
    print(f"fast_stable_pose_env: {os.environ.get(FAST_STABLE_POSE_ENV_VAR, '')}")
    print(f"keep_blend: {args.keep_blend}")
    print(f"sample_timeout_seconds: {args.sample_timeout_seconds}")

    sample_index = 0
    attempts = 0
    max_attempts = args.samples * 1000
    while sample_index < args.samples:
        attempts += 1
        if attempts > max_attempts:
            raise RuntimeError(
                "Exceeded maximum seed attempts while applying "
                "--base-factory-filter"
            )

        factory_seed = int(rng.integers(0, 1_000_000_000))
        inst_seed = int(rng.integers(0, 10_000_000))
        factory = NatureShelfTrinketsFactory(factory_seed)
        base_factory_class = factory.base_factory.__class__.__name__
        if base_factory_filter and base_factory_class not in base_factory_filter:
            skipped += 1
            continue

        placeholder = None
        asset = None
        sample_start = time.perf_counter()

        try:
            with butil.GarbageCollect(
                gc_targets,
                caller="bench_nature_shelf_trinkets_factory",
                generator_class="NatureShelfTrinketsFactory",
                factory_seed=factory_seed,
                inst_seed=inst_seed,
            ):
                print(
                    f"sample {sample_index + 1:03d}/{args.samples:03d} "
                    f"factory_seed={factory_seed} inst_seed={inst_seed} "
                    f"base_factory={base_factory_class} "
                    "starting",
                    flush=True,
                )
                placeholder = factory.spawn_placeholder(
                    inst_seed, loc=(0, 0, 0), rot=(0, 0, 0)
                )
                with (
                    sample_timeout(args.sample_timeout_seconds),
                    FixedSeed(int_hash((factory.factory_seed, inst_seed))),
                ):
                    asset = factory.create_asset(inst_seed, placeholder=placeholder)
                if args.keep_blend:
                    place_visual_sample(asset, placeholder, sample_index)
                    kept_any = True
                else:
                    delete_object_tree(asset, bpy, butil)
                    delete_object_tree(placeholder, bpy, butil)
        except Exception as exc:
            failures += 1
            delete_object_tree(asset, bpy, butil)
            delete_object_tree(placeholder, bpy, butil)
            print(
                f"sample {sample_index + 1:03d}/{args.samples:03d} "
                f"factory_seed={factory_seed} inst_seed={inst_seed} "
                f"failed={exc.__class__.__name__}: {exc}"
            )
        else:
            print(
                f"sample {sample_index + 1:03d}/{args.samples:03d} "
                f"factory_seed={factory_seed} inst_seed={inst_seed} "
                f"base_factory={base_factory_class} "
                f"duration={time.perf_counter() - sample_start:.3f}s"
            )
        finally:
            sample_index += 1

    if args.keep_blend and kept_any:
        blend_path = output_folder / "nature_shelf_trinkets_bench.blend"
        bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
        print(f"blend_path: {blend_path}")

    butil.garbage_collect(gc_targets, keep_in_use=True)
    print(f"total_duration: {time.perf_counter() - total_start:.3f}s")
    print(f"failures: {failures}")
    print(f"skipped_by_filter: {skipped}")
    print(f"timing_csv: {csv_path}")
    return 0


def main() -> None:
    raise SystemExit(benchmark(parse_args()))


if __name__ == "__main__":
    main()
