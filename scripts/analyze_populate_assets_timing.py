#!/usr/bin/env python3
"""Summarize populate_assets timing CSV output."""

from __future__ import annotations

import argparse
import csv
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Iterable


DEFAULT_TIMING_CSV = Path("/tmp/infinigen_populate_assets_timing.csv")
SUMMARY_LIMIT = 20
SLOW_ITEM_LIMIT = 50

COUNT_COLUMNS = (
    "created_material_count",
    "created_texture_count",
    "created_node_group_count",
    "created_mesh_count",
    "created_object_count",
)

DURATION_COLUMNS = (
    "spawn_asset_duration",
    "finalize_assets_duration",
    "collection_duration",
    "cutter_duration",
    "total_duration",
)

SLOW_ITEM_COLUMNS = (
    "index",
    "total_count",
    "placeholder_name",
    "factory_class",
    "placeholder_type",
    "total_duration",
    "spawn_asset_duration",
    "created_material_count",
    "created_texture_count",
    "created_node_group_count",
    "created_mesh_count",
    "created_object_count",
    "success",
    "error_type",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Analyze infinigen_populate_assets_timing.csv rows from the "
            "final indoor populate_assets stage."
        )
    )
    parser.add_argument(
        "csv_path",
        nargs="?",
        default=DEFAULT_TIMING_CSV,
        type=Path,
        help=(
            "Path to infinigen_populate_assets_timing.csv. "
            f"Default: {DEFAULT_TIMING_CSV}"
        ),
    )
    return parser.parse_args()


def as_float(row: dict[str, str], key: str) -> float:
    value = (row.get(key) or "").strip()
    if not value:
        return 0.0
    try:
        return float(value)
    except ValueError:
        return 0.0


def as_int(row: dict[str, str], key: str) -> int:
    value = (row.get(key) or "").strip()
    if not value:
        return 0
    try:
        return int(float(value))
    except ValueError:
        return 0


def as_bool(row: dict[str, str], key: str) -> bool:
    return (row.get(key) or "").strip().lower() in {"1", "true", "yes", "on"}


def clean_label(value: str | None) -> str:
    value = (value or "").strip()
    return value if value else "(unknown)"


def fmt(value: object) -> str:
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def print_table(headers: tuple[str, ...], rows: Iterable[Iterable[object]]) -> None:
    rows = [tuple(fmt(value) for value in row) for row in rows]
    widths = [len(header) for header in headers]
    for row in rows:
        for index, value in enumerate(row):
            widths[index] = max(widths[index], len(value))

    print(
        "  "
        + "  ".join(
            header.ljust(widths[index]) for index, header in enumerate(headers)
        )
    )
    print("  " + "  ".join("-" * width for width in widths))
    for row in rows:
        print(
            "  "
            + "  ".join(value.ljust(widths[index]) for index, value in enumerate(row))
        )


def median(values: list[float]) -> float:
    if not values:
        return 0.0
    return float(statistics.median(values))


def load_rows(csv_path: Path) -> list[dict[str, str]]:
    if not csv_path.exists():
        raise SystemExit(f"Populate assets timing CSV does not exist: {csv_path}")
    with csv_path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def summarize_by_factory(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    groups: dict[str, dict[str, object]] = defaultdict(
        lambda: {
            "durations": [],
            "success": 0,
            "failed": 0,
            **{column: 0 for column in COUNT_COLUMNS},
        }
    )

    for row in rows:
        label = clean_label(row.get("factory_class"))
        group = groups[label]
        durations = group["durations"]
        assert isinstance(durations, list)
        durations.append(as_float(row, "total_duration"))
        if as_bool(row, "success"):
            group["success"] = int(group["success"]) + 1
        else:
            group["failed"] = int(group["failed"]) + 1
        for column in COUNT_COLUMNS:
            group[column] = int(group[column]) + as_int(row, column)

    summary = []
    for label, group in groups.items():
        durations = group["durations"]
        assert isinstance(durations, list)
        total_duration = sum(durations)
        count = len(durations)
        summary.append(
            {
                "factory_class": label,
                "count": count,
                "total_duration": total_duration,
                "mean_duration": total_duration / count if count else 0.0,
                "median_duration": median(durations),
                "max_duration": max(durations) if durations else 0.0,
                "success": int(group["success"]),
                "failed": int(group["failed"]),
                **{column: int(group[column]) for column in COUNT_COLUMNS},
            }
        )
    return summary


def factory_summary_rows(
    summary: list[dict[str, object]], sort_key: str
) -> list[dict[str, object]]:
    return sorted(
        summary,
        key=lambda item: (-float(item[sort_key]), -int(item["count"]), item["factory_class"]),
    )


def print_factory_summary(
    title: str, summary: list[dict[str, object]], sort_key: str
) -> None:
    print(f"\n{title}")
    print_table(
        (
            "factory_class",
            "count",
            sort_key,
            "total_duration",
            "mean_duration",
            "max_duration",
            "success",
            "failed",
        ),
        (
            (
                item["factory_class"],
                item["count"],
                item[sort_key],
                item["total_duration"],
                item["mean_duration"],
                item["max_duration"],
                item["success"],
                item["failed"],
            )
            for item in factory_summary_rows(summary, sort_key)[:SUMMARY_LIMIT]
        ),
    )


def slow_items(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    items = []
    for row in rows:
        item: dict[str, object] = {
            column: row.get(column, "") for column in SLOW_ITEM_COLUMNS
        }
        item["factory_class"] = clean_label(row.get("factory_class"))
        for column in DURATION_COLUMNS:
            item[column] = as_float(row, column)
        for column in COUNT_COLUMNS:
            item[column] = as_int(row, column)
        items.append(item)
    return sorted(items, key=lambda item: float(item["total_duration"]), reverse=True)


def print_slow_items(rows: list[dict[str, str]], limit: int = SLOW_ITEM_LIMIT) -> None:
    print(f"\nF. Slowest populate items (top {limit} by total_duration)")
    print_table(
        SLOW_ITEM_COLUMNS,
        (
            (item[column] for column in SLOW_ITEM_COLUMNS)
            for item in slow_items(rows)[:limit]
        ),
    )


def print_reuse_candidates(summary: list[dict[str, object]]) -> None:
    candidates = []
    for item in summary:
        count = int(item["count"])
        material_texture = int(item["created_material_count"]) + int(
            item["created_texture_count"]
        )
        node_groups = int(item["created_node_group_count"])
        if count < 2 or material_texture <= 0:
            continue
        candidates.append(
            {
                **item,
                "material_texture_total": material_texture,
                "avg_material_texture_per_item": material_texture / count,
                "avg_node_groups_per_item": node_groups / count,
            }
        )
    candidates.sort(
        key=lambda item: (
            -int(item["material_texture_total"]),
            -float(item["total_duration"]),
            item["factory_class"],
        )
    )

    print("\nG. Material/texture reuse candidates")
    if not candidates:
        print("  No repeated material/texture creation candidates found.")
        return
    print_table(
        (
            "factory_class",
            "count",
            "total_duration",
            "created_material_count",
            "created_texture_count",
            "created_node_group_count",
            "material_texture_total",
            "avg_material_texture_per_item",
            "avg_node_groups_per_item",
        ),
        (
            (
                item["factory_class"],
                item["count"],
                item["total_duration"],
                item["created_material_count"],
                item["created_texture_count"],
                item["created_node_group_count"],
                item["material_texture_total"],
                item["avg_material_texture_per_item"],
                item["avg_node_groups_per_item"],
            )
            for item in candidates[:SUMMARY_LIMIT]
        ),
    )


def print_few_slow_factories(summary: list[dict[str, object]]) -> None:
    rows = []
    for item in summary:
        count = int(item["count"])
        total_duration = float(item["total_duration"])
        max_duration = float(item["max_duration"])
        if not total_duration:
            continue
        max_share = max_duration / total_duration
        material_texture = int(item["created_material_count"]) + int(
            item["created_texture_count"]
        )
        if count <= 2 or max_share >= 0.75:
            rows.append(
                {
                    **item,
                    "max_share": max_share,
                    "material_texture_total": material_texture,
                }
            )
    rows.sort(
        key=lambda item: (
            -float(item["total_duration"]),
            -float(item["max_share"]),
            item["factory_class"],
        )
    )

    print("\nH. Few-slow factories, lower reuse priority")
    if not rows:
        print("  No obvious few-slow factories found.")
        return
    print_table(
        (
            "factory_class",
            "count",
            "total_duration",
            "max_duration",
            "max_share",
            "created_material_count",
            "created_texture_count",
            "created_node_group_count",
            "material_texture_total",
        ),
        (
            (
                item["factory_class"],
                item["count"],
                item["total_duration"],
                item["max_duration"],
                item["max_share"],
                item["created_material_count"],
                item["created_texture_count"],
                item["created_node_group_count"],
                item["material_texture_total"],
            )
            for item in rows[:SUMMARY_LIMIT]
        ),
    )


def print_totals(rows: list[dict[str, str]]) -> None:
    print("\nI. Overall totals")
    duration_totals = {
        column: sum(as_float(row, column) for row in rows)
        for column in DURATION_COLUMNS
    }
    count_totals = {
        column: sum(as_int(row, column) for row in rows) for column in COUNT_COLUMNS
    }
    print_table(
        ("metric", "value"),
        (
            ("rows", len(rows)),
            *((column, value) for column, value in duration_totals.items()),
            *((column, value) for column, value in count_totals.items()),
        ),
    )


def main() -> None:
    args = parse_args()
    rows = load_rows(args.csv_path)
    summary = summarize_by_factory(rows)

    print(f"CSV: {args.csv_path}")
    print(f"Rows: {len(rows)}")

    print_factory_summary(
        "A. Factory total_duration top 20",
        summary,
        "total_duration",
    )
    print_factory_summary(
        "B. Factory created_material_count top 20",
        summary,
        "created_material_count",
    )
    print_factory_summary(
        "C. Factory created_texture_count top 20",
        summary,
        "created_texture_count",
    )
    print_factory_summary(
        "D. Factory created_node_group_count top 20",
        summary,
        "created_node_group_count",
    )
    print_factory_summary(
        "E. Factory created_mesh_count top 20",
        summary,
        "created_mesh_count",
    )
    print_slow_items(rows)
    print_reuse_candidates(summary)
    print_few_slow_factories(summary)
    print_totals(rows)


if __name__ == "__main__":
    main()
