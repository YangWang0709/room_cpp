#!/usr/bin/env python3
"""Summarize BookStack / BookColumn populate timing CSV output."""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path


DEFAULT_CSV = Path("/tmp/infinigen_bookstack_timing.csv")
DURATION_FIELD = "create_asset_total_duration"
COUNT_FIELDS = [
    "created_material_count",
    "created_texture_count",
    "created_node_group_count",
    "created_mesh_count",
    "created_object_count",
    "created_image_count",
]
STAGE_FIELDS = [
    "geometry_duration",
    "material_duration",
    "font_text_duration",
    "book_create_duration",
    "placement_duration",
    "join_duration",
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


def aggregate_by_factory(rows: list[dict]) -> dict[str, dict]:
    by_factory = defaultdict(lambda: defaultdict(float))
    for row in rows:
        factory = row.get("factory_class") or "(unknown)"
        stats = by_factory[factory]
        stats["count"] += 1
        stats["total_duration"] += as_float(row, DURATION_FIELD)
        stats["max_duration"] = max(
            stats["max_duration"], as_float(row, DURATION_FIELD)
        )
        for field in STAGE_FIELDS + COUNT_FIELDS:
            stats[field] += as_float(row, field)
    return by_factory


def print_factory_summary(by_factory: dict[str, dict]) -> None:
    print("factory_class duration summary")
    print("-" * 38)
    print(
        "factory_class,count,total,avg,max,geometry,material,font_text,"
        "book_create,placement,join,materials,textures,node_groups,meshes,"
        "objects,images"
    )
    for factory, stats in sorted(
        by_factory.items(), key=lambda item: item[1]["total_duration"], reverse=True
    ):
        count = stats["count"]
        print(
            f"{factory},"
            f"{int(count)},"
            f"{stats['total_duration']:.6f},"
            f"{stats['total_duration'] / count if count else 0.0:.6f},"
            f"{stats['max_duration']:.6f},"
            f"{stats['geometry_duration']:.6f},"
            f"{stats['material_duration']:.6f},"
            f"{stats['font_text_duration']:.6f},"
            f"{stats['book_create_duration']:.6f},"
            f"{stats['placement_duration']:.6f},"
            f"{stats['join_duration']:.6f},"
            f"{int(stats['created_material_count'])},"
            f"{int(stats['created_texture_count'])},"
            f"{int(stats['created_node_group_count'])},"
            f"{int(stats['created_mesh_count'])},"
            f"{int(stats['created_object_count'])},"
            f"{int(stats['created_image_count'])}"
        )
    print()


def print_slowest(rows: list[dict], limit: int = 20) -> None:
    print("slowest samples top 20")
    print("-" * 38)
    for row in sorted(rows, key=lambda item: as_float(item, DURATION_FIELD), reverse=True)[
        :limit
    ]:
        dominant_stage = max(STAGE_FIELDS, key=lambda field: as_float(row, field))
        print(
            f"{fmt_seconds(as_float(row, DURATION_FIELD))} "
            f"factory={row.get('factory_class', ''):22s} "
            f"seed={row.get('factory_seed', ''):>10s} "
            f"inst={row.get('inst_seed', ''):>8s} "
            f"n_books={as_int(row, 'n_books'):3d} "
            f"materials={as_int(row, 'created_material_count'):3d} "
            f"textures={as_int(row, 'created_texture_count'):3d} "
            f"images={as_int(row, 'created_image_count'):3d} "
            f"dominant={dominant_stage}"
        )
    print()


def print_count_summary(rows: list[dict], by_factory: dict[str, dict]) -> None:
    print("material/texture/image creation summary")
    print("-" * 38)
    for field in COUNT_FIELDS:
        total = sum(as_int(row, field) for row in rows)
        max_value = max((as_int(row, field) for row in rows), default=0)
        print(f"{field:30s} total={total:6d} max={max_value:5d}")
    print()

    for field in (
        "created_material_count",
        "created_texture_count",
        "created_image_count",
        "created_node_group_count",
    ):
        print(f"{field} by factory top 20")
        for factory, stats in sorted(
            by_factory.items(), key=lambda item: item[1][field], reverse=True
        )[:20]:
            if stats[field] == 0:
                continue
            print(
                f"  {factory:24s} total={int(stats[field]):6d} "
                f"count={int(stats['count']):5d}"
            )
        print()


def print_font_text_summary(rows: list[dict]) -> None:
    font_total = sum(as_float(row, "font_text_duration") for row in rows)
    image_total = sum(as_int(row, "created_image_count") for row in rows)
    print("font/text cost summary")
    print("-" * 38)
    print(f"font_text_duration_total: {fmt_seconds(font_total)}")
    print(f"created_image_count_total: {image_total}")
    if font_total <= 0 and image_total <= 0:
        print(
            "No direct create_asset-time font/text image creation was observed. "
            "Book cover Text materials are constructed in BookFactory.__init__, "
            "so init-time profiling is the next step if font warnings dominate."
        )
    else:
        print(
            "Font/text or image creation appeared during measured create_asset "
            "calls; material/font/template reuse is worth a separate opt-in "
            "investigation."
        )
    print()


def print_recommendation(rows: list[dict], by_factory: dict[str, dict]) -> None:
    print("reuse recommendation")
    print("-" * 38)
    if not rows:
        print("No successful rows were found.")
        return

    top_factory = max(by_factory, key=lambda name: by_factory[name]["total_duration"])
    material_total = sum(as_int(row, "created_material_count") for row in rows)
    texture_total = sum(as_int(row, "created_texture_count") for row in rows)
    image_total = sum(as_int(row, "created_image_count") for row in rows)
    print(f"Top duration factory: {top_factory}")
    if material_total or texture_total or image_total:
        print(
            "Material/font/template reuse is a plausible next investigation, "
            "but keep it opt-in because covers depend on random colors, text, "
            "font choices, barcode/patch layout, and wear settings."
        )
    else:
        print(
            "This sample did not show material/texture/image growth during "
            "create_asset; prioritize geometry, placement, or factory-init "
            "attribution before reuse."
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", nargs="?", type=Path, default=DEFAULT_CSV)
    args = parser.parse_args()

    if not args.csv_path.exists():
        raise SystemExit(f"CSV not found: {args.csv_path}")

    rows = read_rows(args.csv_path)
    successful = successful_rows(rows)
    failed = failed_rows(rows)
    durations = [as_float(row, DURATION_FIELD) for row in successful]
    total = sum(durations)

    print("BookStack timing summary")
    print("=" * 38)
    print(f"csv_rows: {len(rows)}")
    print(f"successful_rows: {len(successful)}")
    print(f"failed_rows: {len(failed)}")
    print(f"total_duration: {fmt_seconds(total)}")
    print(f"avg_duration:   {fmt_seconds(total / len(successful) if successful else 0.0)}")
    print(f"max_duration:   {fmt_seconds(max(durations, default=0.0))}")
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
    print_factory_summary(by_factory)
    print_count_summary(successful, by_factory)
    print_font_text_summary(successful)
    print_slowest(successful)
    print_recommendation(successful, by_factory)


if __name__ == "__main__":
    main()
