#!/usr/bin/env python3
"""Summarize indoor solver proposal timing CSV output."""

from __future__ import annotations

import argparse
import csv
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Iterable


DEFAULT_TIMING_CSV = Path(
    "outputs/profile_indoor_baseline/coarse/indoor_solver_timing.csv"
)
SUMMARY_LIMIT = 20
SLOW_ATTEMPT_LIMIT = 50

ADDITION_DURATION_COLUMNS = (
    "addition_sample_placeholder_duration",
    "addition_spawn_placeholder_duration",
    "addition_placeholder_finalize_duration",
    "addition_parse_scene_duration",
    "addition_state_update_duration",
    "addition_constraint_duration",
)

SLOW_ATTEMPT_COLUMNS = (
    "iteration",
    "attempt_index",
    "attempt_count",
    "move_type",
    "generator_class",
    "proposal_succeeded",
    "proposal_accepted",
    "attempt_duration",
    "apply_duration",
    "evaluate_duration",
    "revert_duration",
    "garbage_collect_duration",
    "total_step_duration",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze indoor_solver_timing.csv proposal timing rows."
    )
    parser.add_argument(
        "csv_path",
        nargs="?",
        default=DEFAULT_TIMING_CSV,
        type=Path,
        help=f"Path to indoor_solver_timing.csv. Default: {DEFAULT_TIMING_CSV}",
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


def percentile_median(values: list[float]) -> float:
    if not values:
        return 0.0
    return float(statistics.median(values))


def load_rows(csv_path: Path) -> list[dict[str, str]]:
    if not csv_path.exists():
        raise SystemExit(f"Timing CSV does not exist: {csv_path}")
    with csv_path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def summarize_by_generator(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    groups: dict[str, dict[str, object]] = defaultdict(
        lambda: {
            "values": [],
            "failed": 0,
            "accepted": 0,
        }
    )
    for row in rows:
        label = clean_label(row.get("generator_class"))
        group = groups[label]
        values = group["values"]
        assert isinstance(values, list)
        values.append(as_float(row, "apply_duration"))
        if not as_bool(row, "proposal_succeeded"):
            group["failed"] = int(group["failed"]) + 1
        if as_bool(row, "proposal_accepted"):
            group["accepted"] = int(group["accepted"]) + 1

    summary = []
    for label, group in groups.items():
        values = group["values"]
        assert isinstance(values, list)
        summary.append(
            {
                "generator_class": label,
                "count": len(values),
                "total": sum(values),
                "mean": sum(values) / len(values) if values else 0.0,
                "median": percentile_median(values),
                "max": max(values) if values else 0.0,
                "failed": int(group["failed"]),
                "accepted": int(group["accepted"]),
            }
        )
    return sorted(summary, key=lambda item: float(item["total"]), reverse=True)


def summarize_addition(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    groups: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: {column: [] for column in ADDITION_DURATION_COLUMNS}
    )
    for row in rows:
        label = clean_label(row.get("generator_class"))
        for column in ADDITION_DURATION_COLUMNS:
            groups[label][column].append(as_float(row, column))

    summary = []
    for label, group in groups.items():
        item: dict[str, object] = {"generator_class": label}
        total_all = 0.0
        for column in ADDITION_DURATION_COLUMNS:
            values = group[column]
            total = sum(values)
            total_all += total
            item[f"{column}_total"] = total
            item[f"{column}_mean"] = total / len(values) if values else 0.0
            item[f"{column}_max"] = max(values) if values else 0.0
        item["addition_total"] = total_all
        summary.append(item)
    return sorted(summary, key=lambda item: float(item["addition_total"]), reverse=True)


def summarize_by_move_type(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    groups: dict[str, dict[str, float]] = defaultdict(
        lambda: {
            "count": 0.0,
            "apply_duration": 0.0,
            "evaluate_duration": 0.0,
            "revert_duration": 0.0,
            "accept_duration": 0.0,
        }
    )
    for row in rows:
        label = clean_label(row.get("move_type"))
        group = groups[label]
        group["count"] += 1
        for column in (
            "apply_duration",
            "evaluate_duration",
            "revert_duration",
            "accept_duration",
        ):
            group[column] += as_float(row, column)

    summary = []
    for label, group in groups.items():
        summary.append(
            {
                "move_type": label,
                "count": int(group["count"]),
                "apply_duration": group["apply_duration"],
                "evaluate_duration": group["evaluate_duration"],
                "revert_duration": group["revert_duration"],
                "accept_duration": group["accept_duration"],
            }
        )
    return sorted(summary, key=lambda item: float(item["apply_duration"]), reverse=True)


def slow_attempts(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    attempts = []
    for row in rows:
        attempt_duration = as_float(row, "attempt_duration")
        if attempt_duration == 0.0:
            attempt_duration = (
                as_float(row, "apply_duration")
                + as_float(row, "evaluate_duration")
                + as_float(row, "revert_duration")
                + as_float(row, "accept_duration")
            )
        item: dict[str, object] = {column: row.get(column, "") for column in SLOW_ATTEMPT_COLUMNS}
        item["generator_class"] = clean_label(row.get("generator_class"))
        item["attempt_duration"] = attempt_duration
        item["apply_duration"] = as_float(row, "apply_duration")
        item["evaluate_duration"] = as_float(row, "evaluate_duration")
        item["revert_duration"] = as_float(row, "revert_duration")
        item["garbage_collect_duration"] = as_float(row, "garbage_collect_duration")
        item["total_step_duration"] = as_float(row, "total_step_duration")
        attempts.append(item)
    return sorted(attempts, key=lambda item: float(item["attempt_duration"]), reverse=True)


def failure_clusters(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    groups: dict[str, dict[str, float]] = defaultdict(
        lambda: {"attempts": 0.0, "failed": 0.0, "wasted_apply": 0.0}
    )
    for row in rows:
        label = clean_label(row.get("generator_class"))
        group = groups[label]
        group["attempts"] += 1
        if not as_bool(row, "proposal_succeeded"):
            group["failed"] += 1
            group["wasted_apply"] += as_float(row, "apply_duration")

    summary = []
    for label, group in groups.items():
        attempts = int(group["attempts"])
        failed = int(group["failed"])
        summary.append(
            {
                "generator_class": label,
                "attempts": attempts,
                "failed": failed,
                "failure_rate": failed / attempts if attempts else 0.0,
                "wasted_apply": group["wasted_apply"],
            }
        )
    return sorted(
        summary,
        key=lambda item: (int(item["failed"]), float(item["wasted_apply"])),
        reverse=True,
    )


def print_generator_apply(summary: list[dict[str, object]]) -> None:
    print("\nA. apply_duration by generator_class (top 20 by total)")
    print_table(
        (
            "generator_class",
            "count",
            "total",
            "mean",
            "median",
            "max",
            "failed",
            "accepted",
        ),
        (
            (
                item["generator_class"],
                item["count"],
                item["total"],
                item["mean"],
                item["median"],
                item["max"],
                item["failed"],
                item["accepted"],
            )
            for item in summary[:SUMMARY_LIMIT]
        ),
    )


def print_addition(summary: list[dict[str, object]]) -> None:
    print("\nB. Addition breakdown by generator_class (top 20 by component total)")
    headers = (
        "generator_class",
        "sample_total",
        "sample_mean",
        "sample_max",
        "spawn_total",
        "spawn_mean",
        "spawn_max",
        "finalize_total",
        "finalize_mean",
        "finalize_max",
        "parse_total",
        "parse_mean",
        "parse_max",
        "state_total",
        "state_mean",
        "state_max",
        "constraint_total",
        "constraint_mean",
        "constraint_max",
    )
    rows = []
    for item in summary[:SUMMARY_LIMIT]:
        rows.append(
            (
                item["generator_class"],
                item["addition_sample_placeholder_duration_total"],
                item["addition_sample_placeholder_duration_mean"],
                item["addition_sample_placeholder_duration_max"],
                item["addition_spawn_placeholder_duration_total"],
                item["addition_spawn_placeholder_duration_mean"],
                item["addition_spawn_placeholder_duration_max"],
                item["addition_placeholder_finalize_duration_total"],
                item["addition_placeholder_finalize_duration_mean"],
                item["addition_placeholder_finalize_duration_max"],
                item["addition_parse_scene_duration_total"],
                item["addition_parse_scene_duration_mean"],
                item["addition_parse_scene_duration_max"],
                item["addition_state_update_duration_total"],
                item["addition_state_update_duration_mean"],
                item["addition_state_update_duration_max"],
                item["addition_constraint_duration_total"],
                item["addition_constraint_duration_mean"],
                item["addition_constraint_duration_max"],
            )
        )
    print_table(headers, rows)


def print_move_type(summary: list[dict[str, object]]) -> None:
    print("\nC. Durations by move_type")
    print_table(
        (
            "move_type",
            "count",
            "apply_total",
            "evaluate_total",
            "revert_total",
            "accept_total",
        ),
        (
            (
                item["move_type"],
                item["count"],
                item["apply_duration"],
                item["evaluate_duration"],
                item["revert_duration"],
                item["accept_duration"],
            )
            for item in summary
        ),
    )


def print_slow_attempts(summary: list[dict[str, object]]) -> None:
    print("\nD. Slowest proposal attempts (top 50 by attempt_duration)")
    print_table(
        SLOW_ATTEMPT_COLUMNS,
        ((item[column] for column in SLOW_ATTEMPT_COLUMNS) for item in summary[:SLOW_ATTEMPT_LIMIT]),
    )


def print_failures(summary: list[dict[str, object]]) -> None:
    print("\nE. Failed proposal clusters by generator_class (top 20 by failed attempts)")
    print_table(
        ("generator_class", "attempts", "failed", "failure_rate", "wasted_apply"),
        (
            (
                item["generator_class"],
                item["attempts"],
                item["failed"],
                item["failure_rate"],
                item["wasted_apply"],
            )
            for item in summary[:SUMMARY_LIMIT]
        ),
    )


def print_cpp_candidates() -> None:
    print("\nF. C++ rewrite candidates to consider after behavior-preserving Python work")
    print("  Good candidates:")
    print("  - bbox min/max reductions over mesh vertices or placeholder bounds")
    print("  - AABB overlap and broad-phase collision checks")
    print("  - bounds and containment checks that operate on numeric arrays")
    print("  - collision matrix construction for many boxes or sampled candidates")
    print("  - constraint loss aggregation when inputs are already numeric arrays")
    print("  Avoid as first C++ rewrite targets:")
    print("  - bpy object creation/deletion")
    print("  - spawn_asset or asset factory orchestration")
    print("  - material/node generation")
    print("  - the simulated annealing solver control flow")


def main() -> None:
    args = parse_args()
    rows = load_rows(args.csv_path)

    print(f"Timing CSV: {args.csv_path}")
    print(f"Rows: {len(rows)}")
    print(
        "Note: garbage_collect_duration and total_step_duration are step-level fields "
        "and may repeat across retry-attempt rows."
    )

    print_generator_apply(summarize_by_generator(rows))
    print_addition(summarize_addition(rows))
    print_move_type(summarize_by_move_type(rows))
    print_slow_attempts(slow_attempts(rows))
    print_failures(failure_clusters(rows))
    print_cpp_candidates()


if __name__ == "__main__":
    main()
