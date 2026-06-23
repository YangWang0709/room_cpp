#!/usr/bin/env python3
"""Analyze global populate datablock growth attribution CSV output."""

from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from pathlib import Path


DEFAULT_CSV = Path("/tmp/infinigen_datablock_growth_timing.csv")
DURATION_FIELD = "duration"
COUNT_FIELDS = [
    "created_material_count",
    "created_texture_count",
    "created_node_group_count",
    "created_mesh_count",
    "created_object_count",
    "created_image_count",
]
PREFIX_FIELDS = [
    ("material", "created_material_prefix_top"),
    ("texture", "created_texture_prefix_top"),
    ("node_group", "created_node_group_prefix_top"),
    ("mesh", "created_mesh_prefix_top"),
    ("image", "created_image_prefix_top"),
]


def as_float(row: dict, field: str) -> float:
    value = row.get(field, "")
    if value in ("", None):
        return 0.0
    return float(value)


def as_int(row: dict, field: str) -> int:
    value = row.get(field, "")
    if value in ("", None):
        return 0
    return int(float(value))


def fmt_seconds(value: float) -> str:
    return f"{value:9.3f}s"


def read_rows(path: Path) -> list[dict]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def successful_rows(rows: list[dict]) -> list[dict]:
    return [row for row in rows if str(row.get("success", "")).lower() == "true"]


def failed_rows(rows: list[dict]) -> list[dict]:
    return [row for row in rows if str(row.get("success", "")).lower() != "true"]


def parse_prefix_top(value: str) -> Counter:
    counts = Counter()
    if not value:
        return counts
    for item in value.split(";"):
        if not item:
            continue
        prefix, _, count = item.rpartition(":")
        if not prefix or not count:
            continue
        try:
            counts[prefix] += int(count)
        except ValueError:
            continue
    return counts


def aggregate_by_factory(rows: list[dict]) -> dict[str, dict]:
    by_factory = defaultdict(lambda: defaultdict(float))
    for row in rows:
        factory = row.get("factory_class") or "(unknown)"
        stats = by_factory[factory]
        stats["count"] += 1
        stats["duration"] += as_float(row, DURATION_FIELD)
        stats["max_duration"] = max(stats["max_duration"], as_float(row, DURATION_FIELD))
        for field in COUNT_FIELDS:
            stats[field] += as_int(row, field)
    return by_factory


def print_factory_top(by_factory: dict[str, dict], field: str, title: str) -> None:
    print(title)
    print("-" * 38)
    print("factory_class,count,total_created,avg_created,duration,avg_duration")
    for factory, stats in sorted(
        by_factory.items(), key=lambda item: item[1][field], reverse=True
    )[:20]:
        if stats[field] == 0:
            continue
        count = stats["count"]
        print(
            f"{factory},"
            f"{int(count)},"
            f"{int(stats[field])},"
            f"{stats[field] / count if count else 0.0:.3f},"
            f"{stats['duration']:.6f},"
            f"{stats['duration'] / count if count else 0.0:.6f}"
        )
    print()


def print_prefix_tops(rows: list[dict]) -> None:
    print("datablock prefix top")
    print("-" * 38)
    for label, field in PREFIX_FIELDS:
        counts = Counter()
        for row in rows:
            counts.update(parse_prefix_top(row.get(field, "")))
        print(f"{label} prefix top 50")
        for prefix, count in counts.most_common(50):
            print(f"  {prefix:48s} {count:7d}")
        print()


def print_slowest(rows: list[dict], limit: int = 20) -> None:
    print("slowest populate rows top")
    print("-" * 38)
    for row in sorted(rows, key=lambda item: as_float(item, DURATION_FIELD), reverse=True)[
        :limit
    ]:
        print(
            f"{fmt_seconds(as_float(row, DURATION_FIELD))} "
            f"factory={row.get('factory_class', ''):30s} "
            f"materials={as_int(row, 'created_material_count'):4d} "
            f"textures={as_int(row, 'created_texture_count'):4d} "
            f"node_groups={as_int(row, 'created_node_group_count'):4d} "
            f"meshes={as_int(row, 'created_mesh_count'):4d} "
            f"objects={as_int(row, 'created_object_count'):4d} "
            f"images={as_int(row, 'created_image_count'):4d}"
        )
    print()


def print_candidates(by_factory: dict[str, dict]) -> None:
    print("reuse candidates")
    print("-" * 38)
    mat_tex = []
    nodegroup = []
    high_growth_low_time = []
    for factory, stats in by_factory.items():
        material_texture = (
            stats["created_material_count"]
            + stats["created_texture_count"]
            + stats["created_image_count"]
        )
        node_count = stats["created_node_group_count"]
        total_growth = sum(stats[field] for field in COUNT_FIELDS)
        avg_duration = stats["duration"] / stats["count"] if stats["count"] else 0.0
        if material_texture:
            mat_tex.append((material_texture, factory, stats))
        if node_count:
            nodegroup.append((node_count, factory, stats))
        if total_growth >= 20 and avg_duration < 2.0:
            high_growth_low_time.append((total_growth, factory, stats))

    print("material/texture reuse candidates")
    for total, factory, stats in sorted(mat_tex, reverse=True)[:20]:
        print(
            f"  {factory:30s} mat_tex_img={int(total):6d} "
            f"duration={stats['duration']:.3f}s count={int(stats['count'])}"
        )
    print()

    print("nodegroup reuse candidates")
    for total, factory, stats in sorted(nodegroup, reverse=True)[:20]:
        print(
            f"  {factory:30s} node_groups={int(total):6d} "
            f"duration={stats['duration']:.3f}s count={int(stats['count'])}"
        )
    print()

    print("high datablock growth but low duration")
    for total, factory, stats in sorted(high_growth_low_time, reverse=True)[:20]:
        print(
            f"  {factory:30s} total_growth={int(total):6d} "
            f"duration={stats['duration']:.3f}s count={int(stats['count'])}"
        )
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", nargs="?", type=Path, default=DEFAULT_CSV)
    args = parser.parse_args()

    if not args.csv_path.exists():
        raise SystemExit(f"CSV not found: {args.csv_path}")

    rows = read_rows(args.csv_path)
    successful = successful_rows(rows)
    failed = failed_rows(rows)
    total_duration = sum(as_float(row, DURATION_FIELD) for row in successful)

    print("Datablock growth summary")
    print("=" * 38)
    print(f"csv_rows: {len(rows)}")
    print(f"successful_rows: {len(successful)}")
    print(f"failed_rows: {len(failed)}")
    print(f"total_duration: {fmt_seconds(total_duration)}")
    print(
        f"avg_duration:   "
        f"{fmt_seconds(total_duration / len(successful) if successful else 0.0)}"
    )
    print()

    if failed:
        print("failure summary")
        print("-" * 38)
        for row in failed[:20]:
            print(
                f"factory={row.get('factory_class', '')} "
                f"error={row.get('error_type', '')}"
            )
        print()

    by_factory = aggregate_by_factory(successful)
    print_factory_top(
        by_factory,
        "created_material_count",
        "factory_class created_material_count top 20",
    )
    print_factory_top(
        by_factory,
        "created_texture_count",
        "factory_class created_texture_count top 20",
    )
    print_factory_top(
        by_factory,
        "created_node_group_count",
        "factory_class created_node_group_count top 20",
    )
    print_factory_top(
        by_factory,
        "created_image_count",
        "factory_class created_image_count top 20",
    )
    print_prefix_tops(successful)
    print_slowest(successful)
    print_candidates(by_factory)


if __name__ == "__main__":
    main()
