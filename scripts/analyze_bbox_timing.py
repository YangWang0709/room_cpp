#!/usr/bin/env python3
"""Summarize bbox_mesh_from_hipoly timing CSV output."""

from __future__ import annotations

import argparse
import csv
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Iterable


DEFAULT_TIMING_CSV = Path("/tmp/infinigen_bbox_timing.csv")
SUMMARY_LIMIT = 20
SLOW_CALL_LIMIT = 50

DURATION_COLUMNS = (
    "spawn_placeholder_duration",
    "spawn_asset_duration",
    "union_all_bbox_duration",
    "box_from_corners_duration",
    "cleanup_collect_duration",
    "delete_duration",
    "total_duration",
)

SLOW_CALL_COLUMNS = (
    "generator_class",
    "factory_seed",
    "inst_seed",
    "use_pholder",
    "total_duration",
    "spawn_placeholder_duration",
    "spawn_asset_duration",
    "union_all_bbox_duration",
    "box_from_corners_duration",
    "cleanup_collect_duration",
    "delete_duration",
    "success",
    "error_type",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze infinigen_bbox_timing.csv rows from bbox_mesh_from_hipoly."
    )
    parser.add_argument(
        "csv_path",
        nargs="?",
        default=DEFAULT_TIMING_CSV,
        type=Path,
        help=f"Path to infinigen_bbox_timing.csv. Default: {DEFAULT_TIMING_CSV}",
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


def as_bool(row: dict[str, str], key: str) -> bool:
    return (row.get(key) or "").strip().lower() in {"1", "true", "yes", "y"}


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

    print("  " + "  ".join(header.ljust(widths[index]) for index, header in enumerate(headers)))
    print("  " + "  ".join("-" * width for width in widths))
    for row in rows:
        print("  " + "  ".join(value.ljust(widths[index]) for index, value in enumerate(row)))


def median(values: list[float]) -> float:
    if not values:
        return 0.0
    return float(statistics.median(values))


def load_rows(csv_path: Path) -> list[dict[str, str]]:
    if not csv_path.exists():
        raise SystemExit(f"BBox timing CSV does not exist: {csv_path}")
    with csv_path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def summarize_by_generator(
    rows: list[dict[str, str]], duration_column: str
) -> list[dict[str, object]]:
    groups: dict[str, dict[str, object]] = defaultdict(
        lambda: {"values": [], "success": 0, "failed": 0}
    )
    for row in rows:
        label = clean_label(row.get("generator_class"))
        group = groups[label]
        values = group["values"]
        assert isinstance(values, list)
        values.append(as_float(row, duration_column))
        if as_bool(row, "success"):
            group["success"] = int(group["success"]) + 1
        else:
            group["failed"] = int(group["failed"]) + 1

    summary = []
    for label, group in groups.items():
        values = group["values"]
        assert isinstance(values, list)
        total = sum(values)
        summary.append(
            {
                "generator_class": label,
                "count": len(values),
                "total": total,
                "mean": total / len(values) if values else 0.0,
                "median": median(values),
                "max": max(values) if values else 0.0,
                "success": int(group["success"]),
                "failed": int(group["failed"]),
            }
        )
    return sorted(summary, key=lambda item: float(item["total"]), reverse=True)


def print_duration_summary(
    title: str, duration_column: str, rows: list[dict[str, str]]
) -> None:
    print(f"\n{title}")
    print_table(
        (
            "generator_class",
            "count",
            "total",
            "mean",
            "median",
            "max",
            "success",
            "failed",
        ),
        (
            (
                item["generator_class"],
                item["count"],
                item["total"],
                item["mean"],
                item["median"],
                item["max"],
                item["success"],
                item["failed"],
            )
            for item in summarize_by_generator(rows, duration_column)[:SUMMARY_LIMIT]
        ),
    )


def slow_calls(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    calls = []
    for row in rows:
        item: dict[str, object] = {
            column: row.get(column, "") for column in SLOW_CALL_COLUMNS
        }
        for column in DURATION_COLUMNS:
            item[column] = as_float(row, column)
        item["generator_class"] = clean_label(row.get("generator_class"))
        calls.append(item)
    return sorted(calls, key=lambda item: float(item["total_duration"]), reverse=True)


def print_slow_calls(rows: list[dict[str, str]]) -> None:
    print("\nE. Slowest bbox_mesh_from_hipoly calls (top 50 by total_duration)")
    print_table(
        SLOW_CALL_COLUMNS,
        ((item[column] for column in SLOW_CALL_COLUMNS) for item in slow_calls(rows)[:SLOW_CALL_LIMIT]),
    )


def print_totals(rows: list[dict[str, str]]) -> None:
    print("\nF. Duration totals")
    totals = {column: sum(as_float(row, column) for row in rows) for column in DURATION_COLUMNS}
    total_duration = totals["total_duration"]
    print_table(
        ("duration_column", "total", "pct_total"),
        (
            (
                column,
                total,
                total / total_duration if total_duration else 0.0,
            )
            for column, total in totals.items()
        ),
    )


def print_union_guidance(rows: list[dict[str, str]]) -> None:
    total_duration = sum(as_float(row, "total_duration") for row in rows)
    union_total = sum(as_float(row, "union_all_bbox_duration") for row in rows)
    ratio = union_total / total_duration if total_duration else 0.0

    print("\nG. C++ bbox_min_max guidance")
    print(f"  union_all_bbox_total: {union_total:.3f}s")
    print(f"  bbox_mesh_from_hipoly_total: {total_duration:.3f}s")
    print(f"  union_all_bbox_share: {ratio:.3%}")

    if total_duration == 0.0:
        print("  Recommendation: no timing signal yet; collect a bbox timing run first.")
    elif ratio < 0.10:
        print(
            "  Recommendation: do not prioritize C++ bbox_min_max integration yet; "
            "union_all_bbox is a small share of bbox_mesh_from_hipoly time."
        )
    elif ratio >= 0.25:
        print(
            "  Recommendation: union_all_bbox is large enough to consider an opt-in "
            "C++ bbox experiment, guarded by same seed/gin/task A/B."
        )
    else:
        print(
            "  Recommendation: union_all_bbox is noticeable but not dominant; profile "
            "more before choosing it over spawn/delete work."
        )


def main() -> None:
    args = parse_args()
    rows = load_rows(args.csv_path)

    print(f"BBox timing CSV: {args.csv_path}")
    print(f"Rows: {len(rows)}")

    print_duration_summary(
        "A. total_duration by generator_class (top 20)", "total_duration", rows
    )
    print_duration_summary(
        "B. spawn_asset_duration by generator_class (top 20)",
        "spawn_asset_duration",
        rows,
    )
    print_duration_summary(
        "C. union_all_bbox_duration by generator_class (top 20)",
        "union_all_bbox_duration",
        rows,
    )
    print_duration_summary(
        "D. delete_duration by generator_class (top 20)", "delete_duration", rows
    )
    print_slow_calls(rows)
    print_totals(rows)
    print_union_guidance(rows)


if __name__ == "__main__":
    main()
