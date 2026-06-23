#!/usr/bin/env python3
"""Summarize GarbageCollect target-level timing CSV output."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable


DEFAULT_TIMING_CSV = Path("/tmp/infinigen_gc_timing.csv")
TARGET_LIMIT = 20
SLOW_ROW_LIMIT = 50
ZERO_REMOVE_LIMIT = 20
NODE_GROUP_GENERATOR_LIMIT = 20
NODE_GROUP_PREFIX_LIMIT = 50
NODE_GROUP_SLOW_REMOVE_LIMIT = 50

PHASES = ("enter_snapshot", "exit_cleanup")

TARGET_TABLE_COLUMNS = (
    "context_id",
    "phase",
    "target_name",
    "target_len_before",
    "target_len_after",
    "keep_names_count",
    "scanned_count",
    "skipped_in_use_count",
    "skipped_keep_name_count",
    "skipped_no_gc_count",
    "removed_count",
    "remove_duration",
    "remove_mode",
    "batch_remove_enabled",
    "batch_remove_count",
    "batch_remove_duration",
    "individual_remove_duration",
    "node_group_interval",
    "node_group_cleanup_skipped",
    "node_group_cleanup_due",
    "effective_cleanup",
    "duration",
)

NODE_GROUP_SLOW_REMOVE_COLUMNS = (
    "context_id",
    "generator_class",
    "removed_count",
    "remove_duration",
    "target_len_before",
    "target_len_after",
    "removed_name_prefix_top",
    "removed_name_sample",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Analyze infinigen_gc_timing.csv rows from "
            "infinigen.core.util.blender.GarbageCollect."
        )
    )
    parser.add_argument(
        "csv_path",
        nargs="?",
        default=DEFAULT_TIMING_CSV,
        type=Path,
        help=f"Path to infinigen_gc_timing.csv. Default: {DEFAULT_TIMING_CSV}",
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
    return (row.get(key) or "").strip().lower() in {"1", "true", "yes", "y"}


def has_value(row: dict[str, str], key: str) -> bool:
    return bool((row.get(key) or "").strip())


def cleanup_skipped(row: dict[str, str]) -> bool:
    return as_bool(row, "node_group_cleanup_skipped")


def cleanup_effective(row: dict[str, str]) -> bool:
    if has_value(row, "effective_cleanup"):
        return as_bool(row, "effective_cleanup")
    return row.get("phase") == "exit_cleanup"


def cleanup_due(row: dict[str, str]) -> bool:
    if has_value(row, "node_group_cleanup_due"):
        return as_bool(row, "node_group_cleanup_due")
    return cleanup_effective(row)


def batch_remove_enabled(row: dict[str, str]) -> bool:
    return as_bool(row, "batch_remove_enabled")


def remove_mode(row: dict[str, str]) -> str:
    value = clean_label(row.get("remove_mode"))
    if value != "(unknown)":
        return value
    if as_float(row, "batch_remove_duration") > 0.0 or batch_remove_enabled(row):
        return "batch_remove"
    return "individual"


def individual_remove_duration(row: dict[str, str]) -> float:
    if has_value(row, "individual_remove_duration"):
        return as_float(row, "individual_remove_duration")
    if remove_mode(row) == "individual":
        return as_float(row, "remove_duration")
    return 0.0


def batch_remove_duration(row: dict[str, str]) -> float:
    return as_float(row, "batch_remove_duration")


def as_optional_int(row: dict[str, str], key: str) -> int | None:
    value = (row.get(key) or "").strip()
    if not value:
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


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
            + "  ".join(
                value.ljust(widths[index]) for index, value in enumerate(row)
            )
        )


def load_rows(csv_path: Path) -> list[dict[str, str]]:
    if not csv_path.exists():
        raise SystemExit(f"GC timing CSV does not exist: {csv_path}")
    with csv_path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def is_context_row(row: dict[str, str]) -> bool:
    return row.get("row_type") == "context"


def is_target_row(row: dict[str, str]) -> bool:
    return row.get("row_type") == "target" or row.get("phase") in PHASES


def context_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [row for row in rows if is_context_row(row)]


def target_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [row for row in rows if is_target_row(row)]


def phase_duration(rows: list[dict[str, str]], phase: str) -> float:
    return sum(
        as_float(row, "duration") for row in rows if row.get("phase") == phase
    )


def print_context_summary(contexts: list[dict[str, str]], targets: list[dict[str, str]]):
    print("\nA. GC context summary")
    context_total = len(contexts)
    success_count = sum(1 for row in contexts if as_bool(row, "success"))
    failed_count = context_total - success_count
    enter_target_total = phase_duration(targets, "enter_snapshot")
    exit_target_total = phase_duration(targets, "exit_cleanup")
    enter_context_total = sum(as_float(row, "enter_total_duration") for row in contexts)
    exit_context_total = sum(as_float(row, "exit_total_duration") for row in contexts)
    total_context_duration = sum(as_float(row, "total_duration") for row in contexts)

    print_table(
        (
            "context_count",
            "success",
            "failed",
            "context_total",
            "context_enter",
            "context_exit",
            "target_enter",
            "target_exit",
        ),
        (
            (
                context_total,
                success_count,
                failed_count,
                total_context_duration,
                enter_context_total,
                exit_context_total,
                enter_target_total,
                exit_target_total,
            ),
        ),
    )


def summarize_targets(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    groups: dict[str, dict[str, object]] = defaultdict(
        lambda: {
            "rows": 0,
            "duration": 0.0,
            "enter_duration": 0.0,
            "exit_duration": 0.0,
            "remove_duration": 0.0,
            "scanned_count": 0,
            "removed_count": 0,
            "skipped_in_use_count": 0,
            "skipped_keep_name_count": 0,
            "skipped_no_gc_count": 0,
        }
    )

    for row in rows:
        target_name = clean_label(row.get("target_name"))
        group = groups[target_name]
        duration = as_float(row, "duration")
        group["rows"] = int(group["rows"]) + 1
        group["duration"] = float(group["duration"]) + duration
        group["remove_duration"] = float(group["remove_duration"]) + as_float(
            row, "remove_duration"
        )
        if row.get("phase") == "enter_snapshot":
            group["enter_duration"] = float(group["enter_duration"]) + duration
        elif row.get("phase") == "exit_cleanup":
            group["exit_duration"] = float(group["exit_duration"]) + duration
        for count_key in (
            "scanned_count",
            "removed_count",
            "skipped_in_use_count",
            "skipped_keep_name_count",
            "skipped_no_gc_count",
        ):
            group[count_key] = int(group[count_key]) + as_int(row, count_key)

    summary = []
    for target_name, group in groups.items():
        summary.append({"target_name": target_name, **group})
    return sorted(summary, key=lambda item: float(item["duration"]), reverse=True)


def print_target_duration_summary(targets: list[dict[str, str]]) -> None:
    print("\nB. Duration by target_name (top 20)")
    print_table(
        (
            "target_name",
            "rows",
            "duration",
            "enter_duration",
            "exit_duration",
            "remove_duration",
        ),
        (
            (
                item["target_name"],
                item["rows"],
                item["duration"],
                item["enter_duration"],
                item["exit_duration"],
                item["remove_duration"],
            )
            for item in summarize_targets(targets)[:TARGET_LIMIT]
        ),
    )


def print_target_count_summary(targets: list[dict[str, str]]) -> None:
    print("\nC. Scanned and removed counts by target_name")
    summary = sorted(
        summarize_targets(targets),
        key=lambda item: (int(item["scanned_count"]), int(item["removed_count"])),
        reverse=True,
    )
    print_table(
        (
            "target_name",
            "scanned_count",
            "removed_count",
            "skipped_in_use",
            "skipped_keep_name",
            "skipped_no_gc",
            "duration",
        ),
        (
            (
                item["target_name"],
                item["scanned_count"],
                item["removed_count"],
                item["skipped_in_use_count"],
                item["skipped_keep_name_count"],
                item["skipped_no_gc_count"],
                item["duration"],
            )
            for item in summary[:TARGET_LIMIT]
        ),
    )


def slow_target_rows(targets: list[dict[str, str]]) -> list[dict[str, object]]:
    rows = []
    for row in targets:
        item: dict[str, object] = {
            column: row.get(column, "") for column in TARGET_TABLE_COLUMNS
        }
        for key in (
            "target_len_before",
            "target_len_after",
            "keep_names_count",
            "scanned_count",
            "skipped_in_use_count",
            "skipped_keep_name_count",
            "skipped_no_gc_count",
            "removed_count",
            "batch_remove_count",
        ):
            item[key] = as_int(row, key)
        item["remove_duration"] = as_float(row, "remove_duration")
        item["remove_mode"] = remove_mode(row)
        item["batch_remove_enabled"] = batch_remove_enabled(row)
        item["batch_remove_duration"] = batch_remove_duration(row)
        item["individual_remove_duration"] = individual_remove_duration(row)
        interval = as_optional_int(row, "node_group_interval")
        item["node_group_interval"] = "" if interval is None else interval
        item["node_group_cleanup_skipped"] = cleanup_skipped(row)
        item["node_group_cleanup_due"] = cleanup_due(row)
        item["effective_cleanup"] = cleanup_effective(row)
        item["duration"] = as_float(row, "duration")
        item["target_name"] = clean_label(row.get("target_name"))
        rows.append(item)
    return sorted(rows, key=lambda item: float(item["duration"]), reverse=True)


def print_slow_target_rows(targets: list[dict[str, str]]) -> None:
    print("\nD. Slowest target-level GC rows (top 50)")
    print_table(
        TARGET_TABLE_COLUMNS,
        (
            (item[column] for column in TARGET_TABLE_COLUMNS)
            for item in slow_target_rows(targets)[:SLOW_ROW_LIMIT]
        ),
    )


def print_zero_remove_rows(targets: list[dict[str, str]]) -> None:
    print("\nE. exit_cleanup rows with removed_count=0 but high duration (top 20)")
    zero_remove = [
        item
        for item in slow_target_rows(targets)
        if item["phase"] == "exit_cleanup" and int(item["removed_count"]) == 0
    ]
    print_table(
        TARGET_TABLE_COLUMNS,
        (
            (item[column] for column in TARGET_TABLE_COLUMNS)
            for item in zero_remove[:ZERO_REMOVE_LIMIT]
        ),
    )


def node_group_exit_rows(targets: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        row
        for row in targets
        if row.get("phase") == "exit_cleanup"
        and clean_label(row.get("target_name")) == "node_groups"
    ]


def summarize_remove_modes(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    groups: dict[str, dict[str, object]] = defaultdict(
        lambda: {
            "rows": 0,
            "remove_duration": 0.0,
            "individual_remove_duration": 0.0,
            "batch_remove_duration": 0.0,
            "batch_remove_count": 0,
            "removed_count": 0,
        }
    )

    for row in rows:
        if row.get("phase") != "exit_cleanup":
            continue
        mode = remove_mode(row)
        group = groups[mode]
        group["rows"] = int(group["rows"]) + 1
        group["remove_duration"] = float(group["remove_duration"]) + as_float(
            row, "remove_duration"
        )
        group["individual_remove_duration"] = float(
            group["individual_remove_duration"]
        ) + individual_remove_duration(row)
        group["batch_remove_duration"] = float(
            group["batch_remove_duration"]
        ) + batch_remove_duration(row)
        group["batch_remove_count"] = int(group["batch_remove_count"]) + as_int(
            row, "batch_remove_count"
        )
        group["removed_count"] = int(group["removed_count"]) + as_int(
            row, "removed_count"
        )

    summary = []
    for mode, group in groups.items():
        summary.append({"remove_mode": mode, **group})
    return sorted(summary, key=lambda item: float(item["remove_duration"]), reverse=True)


def print_remove_mode_summary(targets: list[dict[str, str]]) -> None:
    print("\nF. Remove mode summary")
    print_table(
        (
            "remove_mode",
            "rows",
            "remove_duration",
            "individual_remove",
            "batch_remove",
            "batch_remove_count",
            "removed_count",
        ),
        (
            (
                item["remove_mode"],
                item["rows"],
                item["remove_duration"],
                item["individual_remove_duration"],
                item["batch_remove_duration"],
                item["batch_remove_count"],
                item["removed_count"],
            )
            for item in summarize_remove_modes(targets)
        ),
    )


def print_node_group_remove_mode_summary(targets: list[dict[str, str]]) -> None:
    print("\nG. node_groups remove_duration by remove_mode")
    node_rows = node_group_exit_rows(targets)
    print_table(
        (
            "remove_mode",
            "rows",
            "remove_duration",
            "individual_remove",
            "batch_remove",
            "batch_remove_count",
            "removed_count",
        ),
        (
            (
                item["remove_mode"],
                item["rows"],
                item["remove_duration"],
                item["individual_remove_duration"],
                item["batch_remove_duration"],
                item["batch_remove_count"],
                item["removed_count"],
            )
            for item in summarize_remove_modes(node_rows)
        ),
    )


def print_batch_remove_summary(targets: list[dict[str, str]]) -> None:
    batch_rows = [
        row
        for row in node_group_exit_rows(targets)
        if batch_remove_enabled(row) or remove_mode(row) == "batch_remove"
    ]
    if not batch_rows:
        return

    batch_call_rows = [row for row in batch_rows if as_int(row, "batch_remove_count")]
    batch_count_total = sum(as_int(row, "batch_remove_count") for row in batch_rows)
    batch_duration_total = sum(batch_remove_duration(row) for row in batch_rows)
    average_batch_size = (
        batch_count_total / len(batch_call_rows) if batch_call_rows else 0.0
    )
    max_batch_size = max(
        (as_int(row, "batch_remove_count") for row in batch_rows), default=0
    )

    print("\nH. node_groups batch_remove summary")
    print_table(
        (
            "batch_enabled_rows",
            "batch_call_rows",
            "batch_remove_duration",
            "batch_remove_count",
            "average_batch_size",
            "max_batch_size",
        ),
        (
            (
                len(batch_rows),
                len(batch_call_rows),
                batch_duration_total,
                batch_count_total,
                average_batch_size,
                max_batch_size,
            ),
        ),
    )


def parse_removed_name_prefix_top(row: dict[str, str]) -> list[tuple[str, int]]:
    value = (row.get("removed_name_prefix_top") or "").strip()
    if not value:
        return []

    try:
        data = json.loads(value)
    except json.JSONDecodeError:
        pairs = []
        for item in value.split(";"):
            if not item:
                continue
            if "=" in item:
                prefix, count = item.rsplit("=", 1)
            elif ":" in item:
                prefix, count = item.rsplit(":", 1)
            else:
                continue
            try:
                pairs.append((clean_label(prefix), int(float(count))))
            except ValueError:
                continue
        return pairs

    pairs = []
    if not isinstance(data, list):
        return pairs
    for item in data:
        if not isinstance(item, list | tuple) or len(item) < 2:
            continue
        try:
            pairs.append((clean_label(str(item[0])), int(float(item[1]))))
        except (TypeError, ValueError):
            continue
    return pairs


def summarize_node_groups_by_generator(
    targets: list[dict[str, str]]
) -> list[dict[str, object]]:
    groups: dict[str, dict[str, object]] = defaultdict(
        lambda: {
            "rows": 0,
            "remove_duration": 0.0,
            "removed_count": 0,
            "target_duration": 0.0,
        }
    )

    for row in node_group_exit_rows(targets):
        generator_class = clean_label(row.get("generator_class"))
        group = groups[generator_class]
        group["rows"] = int(group["rows"]) + 1
        group["remove_duration"] = float(group["remove_duration"]) + as_float(
            row, "remove_duration"
        )
        group["removed_count"] = int(group["removed_count"]) + as_int(
            row, "removed_count"
        )
        group["target_duration"] = float(group["target_duration"]) + as_float(
            row, "duration"
        )

    summary = []
    for generator_class, group in groups.items():
        summary.append({"generator_class": generator_class, **group})
    return summary


def print_node_group_generator_duration_summary(
    targets: list[dict[str, str]]
) -> None:
    print("\nI. node_groups remove_duration by generator_class (top 20)")
    summary = sorted(
        summarize_node_groups_by_generator(targets),
        key=lambda item: float(item["remove_duration"]),
        reverse=True,
    )
    print_table(
        (
            "generator_class",
            "rows",
            "remove_duration",
            "removed_count",
            "target_duration",
        ),
        (
            (
                item["generator_class"],
                item["rows"],
                item["remove_duration"],
                item["removed_count"],
                item["target_duration"],
            )
            for item in summary[:NODE_GROUP_GENERATOR_LIMIT]
        ),
    )


def print_node_group_generator_removed_count_summary(
    targets: list[dict[str, str]]
) -> None:
    print("\nJ. node_groups removed_count by generator_class (top 20)")
    summary = sorted(
        summarize_node_groups_by_generator(targets),
        key=lambda item: (int(item["removed_count"]), float(item["remove_duration"])),
        reverse=True,
    )
    print_table(
        (
            "generator_class",
            "removed_count",
            "remove_duration",
            "rows",
            "target_duration",
        ),
        (
            (
                item["generator_class"],
                item["removed_count"],
                item["remove_duration"],
                item["rows"],
                item["target_duration"],
            )
            for item in summary[:NODE_GROUP_GENERATOR_LIMIT]
        ),
    )


def removed_name_prefix_counts(targets: list[dict[str, str]]) -> Counter[str]:
    prefix_counts: Counter[str] = Counter()
    for row in node_group_exit_rows(targets):
        for prefix, count in parse_removed_name_prefix_top(row):
            prefix_counts[prefix] += count
    return prefix_counts


def print_removed_name_prefix_summary(targets: list[dict[str, str]]) -> None:
    print("\nK. Removed node_group name prefixes (top 50)")
    prefix_counts = removed_name_prefix_counts(targets)
    print_table(
        ("removed_name_prefix", "removed_count"),
        (
            (prefix, count)
            for prefix, count in prefix_counts.most_common(NODE_GROUP_PREFIX_LIMIT)
        ),
    )


def slow_node_group_remove_rows(
    targets: list[dict[str, str]]
) -> list[dict[str, object]]:
    rows = []
    for row in node_group_exit_rows(targets):
        item: dict[str, object] = {
            "context_id": row.get("context_id", ""),
            "generator_class": clean_label(row.get("generator_class")),
            "removed_count": as_int(row, "removed_count"),
            "remove_duration": as_float(row, "remove_duration"),
            "target_len_before": as_int(row, "target_len_before"),
            "target_len_after": as_int(row, "target_len_after"),
            "removed_name_prefix_top": row.get("removed_name_prefix_top", ""),
            "removed_name_sample": row.get("removed_name_sample", ""),
        }
        rows.append(item)
    return sorted(rows, key=lambda item: float(item["remove_duration"]), reverse=True)


def print_slow_node_group_remove_rows(targets: list[dict[str, str]]) -> None:
    print("\nL. Slowest node_groups remove rows (top 50)")
    print_table(
        NODE_GROUP_SLOW_REMOVE_COLUMNS,
        (
            (item[column] for column in NODE_GROUP_SLOW_REMOVE_COLUMNS)
            for item in slow_node_group_remove_rows(targets)[
                :NODE_GROUP_SLOW_REMOVE_LIMIT
            ]
        ),
    )


def print_node_group_throttling_summary(targets: list[dict[str, str]]) -> None:
    print("\nM. Node group throttling summary")
    node_rows = node_group_exit_rows(targets)
    intervals = sorted(
        {
            interval
            for interval in (
                as_optional_int(row, "node_group_interval") for row in node_rows
            )
            if interval is not None
        }
    )
    interval_label = ",".join(str(interval) for interval in intervals) or "1"

    skipped_rows = [row for row in node_rows if cleanup_skipped(row)]
    executed_rows = [
        row for row in node_rows if not cleanup_skipped(row) and cleanup_effective(row)
    ]
    node_duration = sum(as_float(row, "duration") for row in node_rows)
    node_remove_duration = sum(as_float(row, "remove_duration") for row in node_rows)
    executed_duration = sum(as_float(row, "duration") for row in executed_rows)
    executed_remove_duration = sum(
        as_float(row, "remove_duration") for row in executed_rows
    )
    skipped_duration = sum(as_float(row, "duration") for row in skipped_rows)
    estimated_saved_time = (
        executed_remove_duration / len(executed_rows) * len(skipped_rows)
        if executed_rows
        else 0.0
    )
    max_node_group_count = 0
    for row in node_rows:
        max_node_group_count = max(
            max_node_group_count,
            as_int(row, "target_len_before"),
            as_int(row, "target_len_after"),
        )

    print_table(
        (
            "interval",
            "node_group_exit_rows",
            "skipped_cleanup",
            "executed_cleanup",
            "node_groups_duration",
            "node_groups_remove",
            "executed_duration",
            "executed_remove",
            "skipped_duration",
            "estimated_saved_time",
            "max_node_groups",
        ),
        (
            (
                interval_label,
                len(node_rows),
                len(skipped_rows),
                len(executed_rows),
                node_duration,
                node_remove_duration,
                executed_duration,
                executed_remove_duration,
                skipped_duration,
                estimated_saved_time,
                max_node_group_count,
            ),
        ),
    )
    if skipped_rows:
        print(
            "  Note: estimated_saved_time is a naive skipped-count estimate; "
            "compare raw node_groups_remove totals and A/B output before "
            "treating throttling as a speedup."
        )


def print_guidance(targets: list[dict[str, str]]) -> None:
    print("\nN. GC guidance")
    enter_total = phase_duration(targets, "enter_snapshot")
    exit_total = phase_duration(targets, "exit_cleanup")
    remove_total = sum(as_float(row, "remove_duration") for row in targets)
    exit_scan_total = max(exit_total - remove_total, 0.0)
    scanned_total = sum(
        as_int(row, "scanned_count")
        for row in targets
        if row.get("phase") == "exit_cleanup"
    )
    removed_total = sum(
        as_int(row, "removed_count")
        for row in targets
        if row.get("phase") == "exit_cleanup"
    )
    removed_rate = removed_total / scanned_total if scanned_total else 0.0
    total = enter_total + exit_total
    target_summary = summarize_targets(targets)
    top_target = target_summary[0] if target_summary else None
    top_target_share = (
        float(top_target["duration"]) / total if top_target and total else 0.0
    )

    print(f"  enter_snapshot_duration: {enter_total:.3f}s")
    print(f"  exit_cleanup_duration: {exit_total:.3f}s")
    print(f"  exit_cleanup_scan_duration_estimate: {exit_scan_total:.3f}s")
    print(f"  remove_duration: {remove_total:.3f}s")
    print(f"  exit_cleanup_scanned_count: {scanned_total}")
    print(f"  exit_cleanup_removed_count: {removed_total}")
    print(f"  exit_cleanup_removed_rate: {removed_rate:.3%}")

    node_rows = node_group_exit_rows(targets)
    skipped_node_groups = sum(1 for row in node_rows if cleanup_skipped(row))
    executed_node_groups = sum(
        1
        for row in node_rows
        if not cleanup_skipped(row) and cleanup_effective(row)
    )
    if skipped_node_groups:
        print(f"  node_group_cleanup_skipped_count: {skipped_node_groups}")
        print(f"  node_group_cleanup_executed_count: {executed_node_groups}")

    batch_node_rows = [
        row
        for row in node_rows
        if batch_remove_enabled(row) or remove_mode(row) == "batch_remove"
    ]
    if batch_node_rows:
        batch_count_total = sum(as_int(row, "batch_remove_count") for row in node_rows)
        batch_duration_total = sum(batch_remove_duration(row) for row in node_rows)
        print(f"  node_group_batch_remove_duration: {batch_duration_total:.3f}s")
        print(f"  node_group_batch_remove_count: {batch_count_total}")

    if top_target:
        print(
            "  top_target: "
            f"{top_target['target_name']} "
            f"{float(top_target['duration']):.3f}s ({top_target_share:.3%})"
        )

    if enter_total >= max(exit_scan_total, remove_total):
        print(
            "  Judgment: enter_snapshot is dominant; next consider an opt-in "
            "snapshot scope or target-reduction experiment."
        )
    elif remove_total >= exit_scan_total and remove_total >= enter_total:
        print(
            "  Judgment: remove calls dominate; inspect attribution first, "
            "then consider opt-in target-specific cleanup, reuse, or cache "
            "experiments."
        )
    elif exit_scan_total >= enter_total and removed_rate < 0.01:
        print(
            "  Judgment: exit_cleanup scanning dominates while removals are "
            "rare; next consider opt-in less-frequent or deferred cleanup."
        )
    elif exit_scan_total >= enter_total:
        print(
            "  Judgment: exit_cleanup scanning is the larger stage; inspect "
            "the slow target rows before changing cleanup cadence."
        )
    else:
        print(
            "  Judgment: no single GC phase clearly dominates in this sample; "
            "compare the top target rows before designing an experiment."
        )

    if top_target and top_target_share >= 0.4:
        print(
            "  Target note: one target_name dominates the sample; keep the next "
            "opt-in experiment scoped around that target first."
        )

    generator_summary = sorted(
        summarize_node_groups_by_generator(targets),
        key=lambda item: float(item["remove_duration"]),
        reverse=True,
    )
    known_generator_summary = [
        item
        for item in generator_summary
        if item["generator_class"] != "(unknown)"
    ]
    node_remove_total = sum(
        as_float(row, "remove_duration") for row in node_group_exit_rows(targets)
    )
    if known_generator_summary and node_remove_total:
        top3_duration = sum(
            float(item["remove_duration"]) for item in known_generator_summary[:3]
        )
        top3_share = top3_duration / node_remove_total
        if top3_share >= 0.5:
            print(
                "  Attribution judgment: a small set of factories dominates "
                "node_groups remove cost; next inspect those factories' "
                "create_asset paths and node tree generation."
            )
        else:
            print(
                "  Attribution judgment: node_groups remove cost is spread "
                "across factories; use slow rows plus prefix totals before "
                "choosing an optimization target."
            )
    elif node_remove_total:
        print(
            "  Attribution judgment: generator_class metadata is missing for "
            "these node_groups rows; collect a fresh attribution sample before "
            "choosing factory-specific work."
        )

    prefix_counts = removed_name_prefix_counts(targets)
    if prefix_counts:
        prefix_total = sum(prefix_counts.values())
        top_prefix, top_prefix_count = prefix_counts.most_common(1)[0]
        top_prefix_share = top_prefix_count / prefix_total if prefix_total else 0.0
        if top_prefix_share >= 0.05:
            print(
                "  Prefix judgment: repeated node_group prefixes are visible; "
                "next consider whether those node groups can be reused, cached, "
                "or created fewer times without changing behavior."
            )
        else:
            print(
                "  Prefix judgment: removed node_group names are highly "
                "distributed in this sample; if inspection confirms they are "
                "not reusable, continue toward a finer cleanup strategy instead "
                "of broad deferred cleanup."
            )
        print(
            "  Top removed_name_prefix: "
            f"{top_prefix} ({top_prefix_count}/{prefix_total}, "
            f"{top_prefix_share:.3%})"
        )


def main() -> None:
    args = parse_args()
    rows = load_rows(args.csv_path)
    contexts = context_rows(rows)
    targets = target_rows(rows)

    print(f"GC timing CSV: {args.csv_path}")
    print(f"Total CSV rows: {len(rows)}")
    print(f"Context rows: {len(contexts)}")
    print(f"Target rows: {len(targets)}")

    print_context_summary(contexts, targets)
    print_target_duration_summary(targets)
    print_target_count_summary(targets)
    print_slow_target_rows(targets)
    print_zero_remove_rows(targets)
    print_remove_mode_summary(targets)
    print_node_group_remove_mode_summary(targets)
    print_batch_remove_summary(targets)
    print_node_group_generator_duration_summary(targets)
    print_node_group_generator_removed_count_summary(targets)
    print_removed_name_prefix_summary(targets)
    print_slow_node_group_remove_rows(targets)
    print_node_group_throttling_summary(targets)
    print_guidance(targets)


if __name__ == "__main__":
    main()
