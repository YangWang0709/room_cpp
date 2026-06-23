#!/usr/bin/env python3
"""Summarize AssetFactory.spawn_asset timing CSV output."""

from __future__ import annotations

import argparse
import csv
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Iterable


DEFAULT_TIMING_CSV = Path("/tmp/infinigen_asset_factory_timing.csv")
SUMMARY_LIMIT = 20
SLOW_CALL_LIMIT = 50

DURATION_COLUMNS = (
    "spawn_placeholder_duration",
    "finalize_placeholders_duration",
    "asset_parameters_duration",
    "create_asset_duration",
    "parent_or_transform_duration",
    "delete_placeholder_duration",
    "garbage_collect_context_duration",
    "total_duration",
)

GUIDANCE_COLUMNS = (
    "create_asset_duration",
    "delete_placeholder_duration",
    "finalize_placeholders_duration",
    "garbage_collect_context_duration",
)

SLOW_CALL_COLUMNS = (
    "generator_class",
    "factory_seed",
    "inst_seed",
    "user_provided_placeholder",
    "distance",
    "vis_distance",
    "total_duration",
    "spawn_placeholder_duration",
    "finalize_placeholders_duration",
    "asset_parameters_duration",
    "create_asset_duration",
    "parent_or_transform_duration",
    "delete_placeholder_duration",
    "garbage_collect_context_duration",
    "success",
    "error_type",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Analyze infinigen_asset_factory_timing.csv rows from "
            "AssetFactory.spawn_asset."
        )
    )
    parser.add_argument(
        "csv_path",
        nargs="?",
        default=DEFAULT_TIMING_CSV,
        type=Path,
        help=(
            "Path to infinigen_asset_factory_timing.csv. "
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

    print(
        "  "
        + "  ".join(
            header.ljust(widths[index]) for index, header in enumerate(headers)
        )
    )
    print("  " + "  ".join("-" * width for width in widths))
    for row in rows:
        print("  " + "  ".join(value.ljust(widths[index]) for index, value in enumerate(row)))


def median(values: list[float]) -> float:
    if not values:
        return 0.0
    return float(statistics.median(values))


def load_rows(csv_path: Path) -> list[dict[str, str]]:
    if not csv_path.exists():
        raise SystemExit(f"Asset factory timing CSV does not exist: {csv_path}")
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
    print("\nE. Slowest AssetFactory.spawn_asset calls (top 50 by total_duration)")
    print_table(
        SLOW_CALL_COLUMNS,
        (
            (item[column] for column in SLOW_CALL_COLUMNS)
            for item in slow_calls(rows)[:SLOW_CALL_LIMIT]
        ),
    )


def duration_totals(rows: list[dict[str, str]]) -> dict[str, float]:
    return {
        column: sum(as_float(row, column) for row in rows)
        for column in DURATION_COLUMNS
    }


def print_totals(rows: list[dict[str, str]]) -> None:
    print("\nF. Duration totals")
    totals = duration_totals(rows)
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


def print_guidance(rows: list[dict[str, str]]) -> None:
    totals = duration_totals(rows)
    total_duration = totals["total_duration"]
    dominant_column = max(GUIDANCE_COLUMNS, key=lambda column: totals[column])
    dominant_total = totals[dominant_column]
    dominant_share = dominant_total / total_duration if total_duration else 0.0

    print("\nG. Spawn asset guidance")
    print(f"  total_duration: {total_duration:.3f}s")
    for column in GUIDANCE_COLUMNS:
        share = totals[column] / total_duration if total_duration else 0.0
        print(f"  {column}: {totals[column]:.3f}s ({share:.3%})")

    if total_duration == 0.0:
        print("  Recommendation: no timing signal yet; collect a timing run first.")
    elif dominant_column == "create_asset_duration":
        print(
            "  Recommendation: create_asset_duration is dominant; inspect the "
            "slowest factory create_asset implementations next."
        )
    elif dominant_column == "delete_placeholder_duration":
        print(
            "  Recommendation: delete_placeholder_duration is dominant; consider "
            "an opt-in batch delete or deferred delete experiment, guarded by "
            "same seed/gin/task A/B."
        )
    elif dominant_column == "finalize_placeholders_duration":
        print(
            "  Recommendation: finalize_placeholders_duration is dominant; inspect "
            "placeholder finalization work before asset creation."
        )
    elif dominant_column == "garbage_collect_context_duration":
        print(
            "  Recommendation: garbage_collect_context_duration is dominant; inspect "
            "GarbageCollect target scanning and cleanup strategy."
        )
    else:
        print(
            "  Recommendation: no single requested stage dominates; inspect the "
            "slowest generator classes and per-call rows."
        )

    print(
        f"  Dominant requested stage: {dominant_column} "
        f"({dominant_total:.3f}s, {dominant_share:.3%})"
    )


def main() -> None:
    args = parse_args()
    rows = load_rows(args.csv_path)

    print(f"Asset factory timing CSV: {args.csv_path}")
    print(f"Rows: {len(rows)}")

    print_duration_summary(
        "A. total_duration by generator_class (top 20)", "total_duration", rows
    )
    print_duration_summary(
        "B. create_asset_duration by generator_class (top 20)",
        "create_asset_duration",
        rows,
    )
    print_duration_summary(
        "C. delete_placeholder_duration by generator_class (top 20)",
        "delete_placeholder_duration",
        rows,
    )
    print_duration_summary(
        "D. finalize_placeholders_duration by generator_class (top 20)",
        "finalize_placeholders_duration",
        rows,
    )
    print_slow_calls(rows)
    print_totals(rows)
    print_guidance(rows)


if __name__ == "__main__":
    main()
