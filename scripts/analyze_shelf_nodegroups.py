#!/usr/bin/env python3
"""Summarize LargeShelfFactory shelf node group timing CSV output."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable


DEFAULT_TIMING_CSV = Path("/tmp/infinigen_shelf_nodegroup_timing.csv")
PREFIX_LIMIT = 50
SPAWN_LIMIT = 100


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Analyze infinigen_shelf_nodegroup_timing.csv rows from "
            "LargeShelfFactory node group creation instrumentation."
        )
    )
    parser.add_argument(
        "csv_path",
        nargs="?",
        default=DEFAULT_TIMING_CSV,
        type=Path,
        help=(
            "Path to infinigen_shelf_nodegroup_timing.csv. "
            f"Default: {DEFAULT_TIMING_CSV}"
        ),
    )
    parser.add_argument(
        "--spawn-limit",
        default=SPAWN_LIMIT,
        type=int,
        help=f"Maximum spawn summary rows to print. Default: {SPAWN_LIMIT}",
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


def parse_counter(value: str | None) -> Counter[str]:
    value = (value or "").strip()
    if not value:
        return Counter()
    try:
        loaded = json.loads(value)
    except json.JSONDecodeError:
        return Counter()
    if not isinstance(loaded, dict):
        return Counter()
    return Counter({str(key): int(count) for key, count in loaded.items()})


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


def load_rows(csv_path: Path) -> list[dict[str, str]]:
    if not csv_path.exists():
        raise SystemExit(f"Shelf node group timing CSV does not exist: {csv_path}")
    with csv_path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def prefix_rows(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    groups: dict[str, dict[str, object]] = defaultdict(
        lambda: {
            "count": 0,
            "duration": 0.0,
            "created_count": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "cache_keyed_calls": 0,
        }
    )
    for row in rows:
        if row.get("event") != "nodegroup_create":
            continue
        prefix = clean_label(row.get("prefix"))
        group = groups[prefix]
        group["count"] = int(group["count"]) + 1
        group["duration"] = float(group["duration"]) + as_float(row, "duration")
        group["created_count"] = int(group["created_count"]) + as_int(
            row, "created_count"
        )
        if (row.get("cache_key") or "").strip():
            group["cache_keyed_calls"] = int(group["cache_keyed_calls"]) + 1
        if as_bool(row, "reuse_enabled") and (row.get("cache_key") or "").strip():
            if as_bool(row, "cache_hit"):
                group["cache_hits"] = int(group["cache_hits"]) + 1
            else:
                group["cache_misses"] = int(group["cache_misses"]) + 1

    summary = []
    for prefix, group in groups.items():
        count = int(group["count"])
        duration = float(group["duration"])
        cache_hits = int(group["cache_hits"])
        cache_misses = int(group["cache_misses"])
        cache_enabled_calls = cache_hits + cache_misses
        summary.append(
            {
                "prefix": prefix,
                "count": count,
                "total_duration": duration,
                "mean_duration": duration / count if count else 0.0,
                "created_count_inclusive": int(group["created_count"]),
                "cache_keyed_calls": int(group["cache_keyed_calls"]),
                "cache_hits": cache_hits,
                "cache_misses": cache_misses,
                "cache_hit_rate": (
                    cache_hits / cache_enabled_calls if cache_enabled_calls else 0.0
                ),
            }
        )
    summary.sort(
        key=lambda item: (-item["total_duration"], -item["count"], item["prefix"])
    )
    return summary


def spawn_rows(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    summaries = []
    for row in rows:
        if row.get("event") != "spawn_summary":
            continue
        call_counts = parse_counter(row.get("call_prefix_counts"))
        actual_prefix_counts = parse_counter(row.get("created_prefix_counts"))
        summaries.append(
            {
                "spawn_id": as_int(row, "spawn_id"),
                "factory_class": clean_label(row.get("factory_class")),
                "created_count": as_int(row, "created_count"),
                "duration": as_float(row, "duration"),
                "shelf_cell_count": as_int(row, "shelf_cell_count"),
                "division_level_count": as_int(row, "division_level_count"),
                "side_board_count": as_int(row, "side_board_count"),
                "call_counts": call_counts,
                "actual_prefix_counts": actual_prefix_counts,
            }
        )
    summaries.sort(key=lambda item: item["spawn_id"])
    return summaries


def cache_summary_rows(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    groups: dict[str, dict[str, object]] = defaultdict(
        lambda: {
            "calls": 0,
            "reuse_enabled_calls": 0,
            "hits": 0,
            "misses": 0,
            "duration": 0.0,
            "created_count": 0,
            "cache_keys": set(),
            "returned_names": set(),
        }
    )
    for row in rows:
        if row.get("event") != "nodegroup_create":
            continue
        cache_key = (row.get("cache_key") or "").strip()
        if not cache_key:
            continue
        prefix = clean_label(row.get("prefix"))
        group = groups[prefix]
        group["calls"] = int(group["calls"]) + 1
        group["duration"] = float(group["duration"]) + as_float(row, "duration")
        group["created_count"] = int(group["created_count"]) + as_int(
            row, "created_count"
        )
        group["cache_keys"].add(cache_key)
        returned_name = (row.get("returned_nodegroup_name") or "").strip()
        if returned_name:
            group["returned_names"].add(returned_name)
        if as_bool(row, "reuse_enabled"):
            group["reuse_enabled_calls"] = int(group["reuse_enabled_calls"]) + 1
            if as_bool(row, "cache_hit"):
                group["hits"] = int(group["hits"]) + 1
            else:
                group["misses"] = int(group["misses"]) + 1

    summary = []
    for prefix, group in groups.items():
        calls = int(group["calls"])
        hits = int(group["hits"])
        misses = int(group["misses"])
        enabled_calls = hits + misses
        duration = float(group["duration"])
        summary.append(
            {
                "prefix": prefix,
                "calls": calls,
                "reuse_enabled_calls": int(group["reuse_enabled_calls"]),
                "hits": hits,
                "misses": misses,
                "hit_rate": hits / enabled_calls if enabled_calls else 0.0,
                "total_duration": duration,
                "mean_duration": duration / calls if calls else 0.0,
                "created_count_inclusive": int(group["created_count"]),
                "unique_cache_keys": len(group["cache_keys"]),
                "unique_returned_names": len(group["returned_names"]),
            }
        )
    summary.sort(key=lambda item: (-item["hits"], -item["calls"], item["prefix"]))
    return summary


def repeated_template_rows(
    prefixes: list[dict[str, object]], spawns: list[dict[str, object]]
) -> list[tuple[object, ...]]:
    spawn_count = len(spawns)
    if spawn_count == 0:
        return []
    rows = []
    for item in prefixes:
        count = int(item["count"])
        per_spawn = count / spawn_count
        if count <= 1 and per_spawn <= 1.0:
            continue
        signal = "yes" if count > spawn_count or per_spawn > 1.0 else "maybe"
        rows.append(
            (
                item["prefix"],
                count,
                per_spawn,
                item["total_duration"],
                signal,
            )
        )
    rows.sort(key=lambda row: (-float(row[3]), -int(row[1]), str(row[0])))
    return rows


def print_prefix_summary(prefixes: list[dict[str, object]]) -> None:
    print("\nNode group prefix creation calls:")
    if not prefixes:
        print("  No nodegroup_create rows found.")
        return
    print_table(
        (
            "prefix",
            "calls",
            "total_duration",
            "mean_duration",
            "inclusive_created",
            "cache_hits",
            "cache_misses",
        ),
        (
            (
                item["prefix"],
                item["count"],
                item["total_duration"],
                item["mean_duration"],
                item["created_count_inclusive"],
                item["cache_hits"],
                item["cache_misses"],
            )
            for item in prefixes[:PREFIX_LIMIT]
        ),
    )


def print_spawn_summary(spawns: list[dict[str, object]], limit: int) -> None:
    print("\nLargeShelfFactory spawn node group counts:")
    if not spawns:
        print("  No spawn_summary rows found.")
        return
    print_table(
        (
            "spawn_id",
            "created_count",
            "duration",
            "cells",
            "levels",
            "side_boards",
            "call_prefix_counts",
            "actual_created_prefix_counts",
        ),
        (
            (
                item["spawn_id"],
                item["created_count"],
                item["duration"],
                item["shelf_cell_count"],
                item["division_level_count"],
                item["side_board_count"],
                json.dumps(dict(item["call_counts"]), sort_keys=True),
                json.dumps(dict(item["actual_prefix_counts"]), sort_keys=True),
            )
            for item in spawns[:limit]
        ),
    )
    if len(spawns) > limit:
        print(f"  ... omitted {len(spawns) - limit} spawn rows")


def print_aggregate_summary(
    rows: list[dict[str, str]], spawns: list[dict[str, object]]
) -> None:
    nodegroup_create_rows = [
        row for row in rows if row.get("event") == "nodegroup_create"
    ]
    spawn_created_total = sum(int(item["created_count"]) for item in spawns)
    nodegroup_created_total = sum(
        as_int(row, "created_count") for row in nodegroup_create_rows
    )
    total_spawn_duration = sum(float(item["duration"]) for item in spawns)
    mean_created = spawn_created_total / len(spawns) if spawns else 0.0
    mean_duration = total_spawn_duration / len(spawns) if spawns else 0.0

    print("\nAggregate spawn summary:")
    print(f"  actual_node_groups_created_total: {spawn_created_total}")
    print(f"  mean_actual_node_groups_created_per_spawn: {mean_created:.3f}")
    print(f"  total_spawn_summary_duration: {total_spawn_duration:.3f}s")
    print(f"  mean_spawn_summary_duration: {mean_duration:.3f}s")
    print(f"  nodegroup_create_inclusive_created_total: {nodegroup_created_total}")


def print_cache_summary(
    rows: list[dict[str, str]], cache_rows: list[dict[str, object]]
) -> None:
    keyed_rows = [
        row
        for row in rows
        if row.get("event") == "nodegroup_create"
        and (row.get("cache_key") or "").strip()
    ]
    enabled_rows = [row for row in keyed_rows if as_bool(row, "reuse_enabled")]
    hit_count = sum(1 for row in enabled_rows if as_bool(row, "cache_hit"))
    miss_count = len(enabled_rows) - hit_count
    hit_rate = hit_count / len(enabled_rows) if enabled_rows else 0.0

    print("\nLargeShelf child node group reuse cache:")
    print(f"  cache_keyed_call_rows: {len(keyed_rows)}")
    print(f"  cache_enabled_call_rows: {len(enabled_rows)}")
    print(f"  cache_hit_count: {hit_count}")
    print(f"  cache_miss_count: {miss_count}")
    print(f"  cache_hit_rate: {hit_rate:.3%}")
    print(f"  estimated_saved_create_calls: {hit_count}")

    print("\nReused prefix summary:")
    if not cache_rows:
        print("  No cache-keyed nodegroup_create rows found.")
        return
    print_table(
        (
            "prefix",
            "calls",
            "enabled_calls",
            "hits",
            "misses",
            "hit_rate",
            "total_duration",
            "mean_duration",
            "inclusive_created",
            "cache_keys",
            "returned_names",
        ),
        (
            (
                item["prefix"],
                item["calls"],
                item["reuse_enabled_calls"],
                item["hits"],
                item["misses"],
                item["hit_rate"],
                item["total_duration"],
                item["mean_duration"],
                item["created_count_inclusive"],
                item["unique_cache_keys"],
                item["unique_returned_names"],
            )
            for item in cache_rows
        ),
    )


def print_repeated_templates(
    prefixes: list[dict[str, object]], spawns: list[dict[str, object]]
) -> None:
    print("\nObvious repeated templates:")
    rows = repeated_template_rows(prefixes, spawns)
    if not rows:
        print("  No repeated prefix signal found in this CSV.")
        return
    print_table(
        ("prefix", "calls", "calls_per_spawn", "total_duration", "repeat_signal"),
        rows,
    )


def main() -> int:
    args = parse_args()
    rows = load_rows(args.csv_path)
    prefixes = prefix_rows(rows)
    spawns = spawn_rows(rows)
    cache_rows = cache_summary_rows(rows)

    print(f"Shelf node group timing CSV: {args.csv_path}")
    print(f"rows: {len(rows)}")
    nodegroup_create_count = sum(
        1 for row in rows if row.get("event") == "nodegroup_create"
    )
    print(f"nodegroup_create rows: {nodegroup_create_count}")
    print(f"spawn_summary rows: {len(spawns)}")
    print_aggregate_summary(rows, spawns)
    print_prefix_summary(prefixes)
    print_cache_summary(rows, cache_rows)
    print_spawn_summary(spawns, args.spawn_limit)
    print_repeated_templates(prefixes, spawns)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
