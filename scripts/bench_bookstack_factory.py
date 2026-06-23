#!/usr/bin/env python3
"""Targeted BookStackFactory / BookColumnFactory create_asset benchmark."""

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

CSV_NAME = "infinigen_bookstack_timing.csv"
PROFILE_ENV_VAR = "INFINIGEN_PROFILE_BOOKSTACK"
CSV_ENV_VAR = "INFINIGEN_BOOKSTACK_TIMING_CSV"
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
        choices=("BookStackFactory", "BookColumnFactory"),
        default="BookStackFactory",
    )
    parser.add_argument(
        "--output_folder",
        type=Path,
        default=Path("outputs/bench_bookstack"),
    )
    parser.add_argument("--csv-path", type=Path, default=None)
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


def benchmark(args: argparse.Namespace) -> int:
    import bpy

    from infinigen.assets.objects.table_decorations.book import (
        BookColumnFactory,
        BookStackFactory,
    )
    from infinigen.core.util import blender as butil

    if args.samples <= 0:
        raise ValueError("--samples must be positive")

    factory_classes = {
        "BookStackFactory": BookStackFactory,
        "BookColumnFactory": BookColumnFactory,
    }
    factory_class = factory_classes[args.factory_class]
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

    print("BookStack targeted benchmark")
    print(f"samples: {args.samples}")
    print(f"seed: {args.seed}")
    print(f"factory_class: {args.factory_class}")
    print(f"output_folder: {output_folder}")
    print(f"timing_csv: {csv_path}")
    print(f"sample_timeout_seconds: {args.sample_timeout_seconds}")

    for sample_index in range(args.samples):
        factory_seed = int(rng.integers(0, 1_000_000_000))
        inst_seed = int(rng.integers(0, 10_000_000))
        factory = factory_class(factory_seed)
        placeholder = None
        asset = None
        sample_start = time.perf_counter()

        try:
            with butil.GarbageCollect(
                gc_targets,
                caller="bench_bookstack_factory",
                generator_class=args.factory_class,
                factory_seed=factory_seed,
                inst_seed=inst_seed,
            ):
                print(
                    f"sample {sample_index + 1:03d}/{args.samples:03d} "
                    f"factory_seed={factory_seed} inst_seed={inst_seed} starting",
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
                f"sample {sample_index + 1:03d}/{args.samples:03d} "
                f"factory_seed={factory_seed} inst_seed={inst_seed} "
                f"failed={exc.__class__.__name__}: {exc}"
            )
        else:
            print(
                f"sample {sample_index + 1:03d}/{args.samples:03d} "
                f"duration={time.perf_counter() - sample_start:.3f}s"
            )

    butil.garbage_collect(gc_targets, keep_in_use=True)
    print(f"total_duration: {time.perf_counter() - total_start:.3f}s")
    print(f"failures: {failures}")
    print(f"timing_csv: {csv_path}")
    return 0


def main() -> None:
    raise SystemExit(benchmark(parse_args()))


if __name__ == "__main__":
    main()
