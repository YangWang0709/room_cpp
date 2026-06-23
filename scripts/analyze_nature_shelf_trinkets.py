#!/usr/bin/env python3
"""Summarize NatureShelfTrinketsFactory timing CSV output."""

from __future__ import annotations

import argparse
import csv
import re
from collections import Counter, defaultdict
from pathlib import Path


DEFAULT_CSV = Path("/tmp/infinigen_nature_shelf_trinkets_timing.csv")

DURATION_FIELD = "create_asset_total_duration"
COUNT_FIELDS = [
    "created_material_count",
    "created_texture_count",
    "created_node_group_count",
    "created_mesh_count",
    "created_object_count",
]
SUBSTAGE_FIELDS = [
    "base_factory_spawn_duration",
    "join_children_duration",
    "apply_initial_transform_duration",
    "apply_modifiers_duration",
    "obj2trimesh_duration",
    "stable_pose_duration",
    "fast_stable_pose_duration",
    "apply_rotation_transform_duration",
    "scale_and_position_duration",
    "apply_final_location_transform_duration",
]
NAME_FIELDS = [
    ("material", "created_material_names"),
    ("texture", "created_texture_names"),
    ("node_group", "created_node_group_names"),
]

BASE_FACTORY_STAGE_FIELDS = [
    DURATION_FIELD,
    "base_factory_spawn_duration",
    "obj2trimesh_duration",
    "stable_pose_duration",
    "fast_stable_pose_duration",
    "apply_modifiers_duration",
]

MESH_FIELDS = [
    "mesh_vertex_count",
    "mesh_face_count",
    "mesh_edge_count",
]
BBOX_EXTENT_FIELDS = [
    "bbox_extent_x",
    "bbox_extent_y",
    "bbox_extent_z",
]
CACHE_KEY_FIELD = "stable_pose_cache_candidate_key"
FAST_COUNT_FIELDS = [
    "fast_stable_pose_used",
    "skipped_compute_stable_poses",
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


def as_bool(row: dict, field: str) -> bool:
    return str(row.get(field, "")).strip().lower() in {"1", "true", "yes", "on"}


def split_names(value: str) -> list[str]:
    if not value:
        return []
    return [name for name in value.split(";") if name]


def normalize_blender_name(name: str) -> str:
    return re.sub(r"\.\d{3,}$", "", name)


def fmt_seconds(seconds: float) -> str:
    return f"{seconds:9.3f}s"


def fmt_count(value: float) -> str:
    return f"{value:9.1f}"


def ratio(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return numerator / denominator


def read_rows(path: Path) -> list[dict]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def empty_base_stats() -> dict:
    stats = {
        "count": 0,
    }
    for field in BASE_FACTORY_STAGE_FIELDS:
        stats[f"{field}_total"] = 0.0
        stats[f"{field}_max"] = 0.0
    for field in COUNT_FIELDS:
        stats[field] = 0
    for field in FAST_COUNT_FIELDS:
        stats[field] = 0
    for field in MESH_FIELDS:
        stats[f"{field}_total"] = 0.0
        stats[f"{field}_max"] = 0
    stats["mesh_complexity_count"] = 0
    return stats


def build_base_factory_stats(rows: list[dict]) -> dict[str, dict]:
    by_base = defaultdict(empty_base_stats)
    for row in rows:
        base_factory = row.get("base_factory_class") or "(unknown)"
        stats = by_base[base_factory]
        stats["count"] += 1
        for field in BASE_FACTORY_STAGE_FIELDS:
            value = as_float(row, field)
            stats[f"{field}_total"] += value
            stats[f"{field}_max"] = max(stats[f"{field}_max"], value)
        for field in COUNT_FIELDS:
            stats[field] += as_int(row, field)
        for field in FAST_COUNT_FIELDS:
            stats[field] += int(as_bool(row, field))
        if any(as_int(row, field) > 0 for field in MESH_FIELDS):
            stats["mesh_complexity_count"] += 1
            for field in MESH_FIELDS:
                value = as_int(row, field)
                stats[f"{field}_total"] += value
                stats[f"{field}_max"] = max(stats[f"{field}_max"], value)
    return by_base


def average(stats: dict, total_field: str) -> float:
    if stats["count"] == 0:
        return 0.0
    return stats[total_field] / stats["count"]


def print_base_factory_top(by_base: dict[str, dict], limit: int = 20) -> None:
    print("Slowest base_factory_class top 20")
    print("-" * 38)
    print(
        "base_factory_class,count,total,avg,max,"
        "spawn_total,spawn_avg,spawn_max,"
        "obj2trimesh_total,obj2trimesh_avg,obj2trimesh_max,"
        "stable_total,stable_avg,stable_max,"
        "fast_total,fast_avg,fast_max,fast_used,skipped_compute,"
        "modifiers_total,modifiers_avg,modifiers_max,"
        "materials,textures,node_groups,meshes,objects"
    )
    for base_factory, stats in sorted(
        by_base.items(),
        key=lambda item: item[1][f"{DURATION_FIELD}_total"],
        reverse=True,
    )[:limit]:
        print(
            f"{base_factory},"
            f"{stats['count']},"
            f"{stats[f'{DURATION_FIELD}_total']:.6f},"
            f"{average(stats, f'{DURATION_FIELD}_total'):.6f},"
            f"{stats[f'{DURATION_FIELD}_max']:.6f},"
            f"{stats['base_factory_spawn_duration_total']:.6f},"
            f"{average(stats, 'base_factory_spawn_duration_total'):.6f},"
            f"{stats['base_factory_spawn_duration_max']:.6f},"
            f"{stats['obj2trimesh_duration_total']:.6f},"
            f"{average(stats, 'obj2trimesh_duration_total'):.6f},"
            f"{stats['obj2trimesh_duration_max']:.6f},"
            f"{stats['stable_pose_duration_total']:.6f},"
            f"{average(stats, 'stable_pose_duration_total'):.6f},"
            f"{stats['stable_pose_duration_max']:.6f},"
            f"{stats['fast_stable_pose_duration_total']:.6f},"
            f"{average(stats, 'fast_stable_pose_duration_total'):.6f},"
            f"{stats['fast_stable_pose_duration_max']:.6f},"
            f"{stats['fast_stable_pose_used']},"
            f"{stats['skipped_compute_stable_poses']},"
            f"{stats['apply_modifiers_duration_total']:.6f},"
            f"{average(stats, 'apply_modifiers_duration_total'):.6f},"
            f"{stats['apply_modifiers_duration_max']:.6f},"
            f"{stats['created_material_count']},"
            f"{stats['created_texture_count']},"
            f"{stats['created_node_group_count']},"
            f"{stats['created_mesh_count']},"
            f"{stats['created_object_count']}"
        )
    print()


def mesh_average(stats: dict, field: str) -> float:
    count = stats.get("mesh_complexity_count", 0)
    if count == 0:
        return 0.0
    return stats[f"{field}_total"] / count


def print_base_mesh_complexity(by_base: dict[str, dict], limit: int = 20) -> None:
    print("Mesh complexity by base_factory_class top 20")
    print("-" * 38)
    print(
        "base_factory_class,count,mesh_rows,avg_vertices,avg_faces,avg_edges,"
        "max_vertices,max_faces,max_edges,stable_total,stable_avg"
    )
    for base_factory, stats in sorted(
        by_base.items(),
        key=lambda item: item[1]["stable_pose_duration_total"],
        reverse=True,
    )[:limit]:
        mesh_rows = stats.get("mesh_complexity_count", 0)
        stable_avg = (
            stats["stable_pose_duration_total"] / stats["count"]
            if stats["count"]
            else 0.0
        )
        print(
            f"{base_factory},"
            f"{stats['count']},"
            f"{mesh_rows},"
            f"{mesh_average(stats, 'mesh_vertex_count'):.3f},"
            f"{mesh_average(stats, 'mesh_face_count'):.3f},"
            f"{mesh_average(stats, 'mesh_edge_count'):.3f},"
            f"{stats['mesh_vertex_count_max']},"
            f"{stats['mesh_face_count_max']},"
            f"{stats['mesh_edge_count_max']},"
            f"{stats['stable_pose_duration_total']:.6f},"
            f"{stable_avg:.6f}"
        )
    print()


def print_count_top(by_base: dict[str, dict], field: str, title: str) -> None:
    print(title)
    print("-" * 38)
    for base_factory, stats in sorted(
        by_base.items(), key=lambda item: item[1][field], reverse=True
    )[:20]:
        if stats[field] == 0:
            continue
        avg = stats[field] / stats["count"] if stats["count"] else 0.0
        print(
            f"{base_factory:28s} total={stats[field]:7d} "
            f"count={stats['count']:5d} avg={avg:8.3f}"
        )
    print()


def correlation(pairs: list[tuple[float, float]]) -> float:
    if len(pairs) < 2:
        return 0.0
    xs = [pair[0] for pair in pairs]
    ys = [pair[1] for pair in pairs]
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in pairs)
    denom_x = sum((x - mean_x) ** 2 for x in xs) ** 0.5
    denom_y = sum((y - mean_y) ** 2 for y in ys) ** 0.5
    if denom_x == 0 or denom_y == 0:
        return 0.0
    return numerator / (denom_x * denom_y)


def print_stable_pose_mesh_summary(successful: list[dict]) -> None:
    stable_rows = [
        row
        for row in successful
        if as_float(row, "stable_pose_duration") > 0
        and as_int(row, "mesh_vertex_count") > 0
        and as_int(row, "mesh_face_count") > 0
    ]
    stable_total = sum(as_float(row, "stable_pose_duration") for row in stable_rows)
    obj2_total = sum(as_float(row, "obj2trimesh_duration") for row in stable_rows)
    vertices = [as_int(row, "mesh_vertex_count") for row in stable_rows]
    faces = [as_int(row, "mesh_face_count") for row in stable_rows]
    edges = [as_int(row, "mesh_edge_count") for row in stable_rows]
    pose_counts = [as_int(row, "stable_pose_count") for row in stable_rows]
    stable_durations = [as_float(row, "stable_pose_duration") for row in stable_rows]

    print("Stable pose duration vs mesh complexity")
    print("-" * 38)
    print(f"stable_pose_rows: {len(stable_rows)}")
    print(f"stable_pose_total: {fmt_seconds(stable_total)}")
    print(
        f"stable_pose_avg:   "
        f"{fmt_seconds(stable_total / len(stable_rows) if stable_rows else 0.0)}"
    )
    print(f"stable_pose_max:   {fmt_seconds(max(stable_durations, default=0.0))}")
    print(f"obj2trimesh_total: {fmt_seconds(obj2_total)}")
    print(
        f"obj2trimesh_avg:   "
        f"{fmt_seconds(obj2_total / len(stable_rows) if stable_rows else 0.0)}"
    )
    print(
        f"avg_vertices: {fmt_count(sum(vertices) / len(vertices) if vertices else 0.0)} "
        f"max_vertices={max(vertices, default=0):7d}"
    )
    print(
        f"avg_faces:    {fmt_count(sum(faces) / len(faces) if faces else 0.0)} "
        f"max_faces={max(faces, default=0):7d}"
    )
    print(
        f"avg_edges:    {fmt_count(sum(edges) / len(edges) if edges else 0.0)} "
        f"max_edges={max(edges, default=0):7d}"
    )
    print(
        f"avg_stable_pose_count: "
        f"{fmt_count(sum(pose_counts) / len(pose_counts) if pose_counts else 0.0)} "
        f"max_stable_pose_count={max(pose_counts, default=0):7d}"
    )
    print(
        "corr(stable_pose_duration, vertices): "
        f"{correlation(list(zip(vertices, stable_durations))):.3f}"
    )
    print(
        "corr(stable_pose_duration, faces):    "
        f"{correlation(list(zip(faces, stable_durations))):.3f}"
    )
    print(
        "corr(stable_pose_duration, pose_count): "
        f"{correlation(list(zip(pose_counts, stable_durations))):.3f}"
    )
    if sum(faces) > 0:
        print(
            "stable_pose_seconds_per_1k_faces: "
            f"{stable_total / (sum(faces) / 1000.0):.6f}"
        )
    print()


def extent_text(row: dict) -> str:
    values = [as_float(row, field) for field in BBOX_EXTENT_FIELDS]
    return "x".join(f"{value:.4g}" for value in values)


def print_slowest_stable_pose(successful: list[dict], limit: int = 20) -> None:
    print("Slowest stable_pose top 20")
    print("-" * 38)
    print(
        "stable_pose,obj2trimesh,base_factory,vertices,faces,edges,"
        "bbox_extent,stable_pose_count,best_prob"
    )
    stable_rows = [
        row for row in successful if as_float(row, "stable_pose_duration") > 0
    ]
    for row in sorted(
        stable_rows,
        key=lambda item: as_float(item, "stable_pose_duration"),
        reverse=True,
    )[:limit]:
        print(
            f"{as_float(row, 'stable_pose_duration'):.6f},"
            f"{as_float(row, 'obj2trimesh_duration'):.6f},"
            f"{row.get('base_factory_class', '')},"
            f"{as_int(row, 'mesh_vertex_count')},"
            f"{as_int(row, 'mesh_face_count')},"
            f"{as_int(row, 'mesh_edge_count')},"
            f"{extent_text(row)},"
            f"{as_int(row, 'stable_pose_count')},"
            f"{as_float(row, 'stable_pose_best_prob'):.6f}"
        )
    print()


def cache_key_counts(successful: list[dict]) -> Counter:
    return Counter(row.get(CACHE_KEY_FIELD, "") for row in successful if row.get(CACHE_KEY_FIELD, ""))


def print_stable_pose_cache_key_summary(successful: list[dict]) -> Counter:
    counts = cache_key_counts(successful)
    repeated = [(key, count) for key, count in counts.items() if count > 1]
    repeated.sort(key=lambda item: item[1], reverse=True)

    print("Stable pose cache candidate key repeats")
    print("-" * 38)
    print(f"candidate_keys: {sum(counts.values())}")
    print(f"unique_candidate_keys: {len(counts)}")
    print(f"repeated_candidate_keys: {len(repeated)}")
    if repeated:
        for key, count in repeated[:20]:
            print(f"count={count:5d} key={key}")
        print(
            "Repeated candidate keys exist; a later exact, opt-in stable-pose "
            "cache may be worth prototyping for those keys."
        )
    else:
        print(
            "No repeated candidate keys were observed; an exact stable-pose "
            "cache is likely to have limited benefit on this sample."
        )
    print()
    return counts


def print_cause_summary(successful: list[dict], substage_totals: dict[str, float]):
    total_duration = sum(as_float(row, DURATION_FIELD) for row in successful)
    base_spawn_total = substage_totals.get("base_factory_spawn_duration", 0.0)
    obj2_total = substage_totals.get("obj2trimesh_duration", 0.0)
    stable_pose_total = substage_totals.get("stable_pose_duration", 0.0)
    modifiers_total = substage_totals.get("apply_modifiers_duration", 0.0)

    base_spawn_ratio = ratio(base_spawn_total, total_duration)
    obj2_ratio = ratio(obj2_total, total_duration)
    stable_pose_ratio = ratio(stable_pose_total, total_duration)
    stable_pose_pipeline_ratio = ratio(obj2_total + stable_pose_total, total_duration)
    modifiers_ratio = ratio(modifiers_total, total_duration)

    print("Cause summary")
    print("-" * 38)
    print(
        "base_factory.spawn_asset ratio: "
        f"{base_spawn_ratio:.1%} "
        f"({fmt_seconds(base_spawn_total)} / {fmt_seconds(total_duration)})"
    )
    print(
        "obj2trimesh ratio: "
        f"{obj2_ratio:.1%} "
        f"({fmt_seconds(obj2_total)} / {fmt_seconds(total_duration)})"
    )
    print(
        "stable_pose ratio: "
        f"{stable_pose_ratio:.1%} "
        f"({fmt_seconds(stable_pose_total)} / {fmt_seconds(total_duration)})"
    )
    print(
        "stable_pose pipeline ratio: "
        f"{stable_pose_pipeline_ratio:.1%} "
        f"({fmt_seconds(obj2_total + stable_pose_total)} / "
        f"{fmt_seconds(total_duration)})"
    )
    print(
        "stable_pose_pipeline_is_primary: "
        f"{'yes' if stable_pose_pipeline_ratio >= 0.5 else 'no'}"
    )
    print(
        "apply_modifiers ratio: "
        f"{modifiers_ratio:.1%} "
        f"({fmt_seconds(modifiers_total)} / {fmt_seconds(total_duration)})"
    )
    print(
        "base_factory.spawn_asset_is_primary: "
        f"{'yes' if base_spawn_ratio >= 0.5 else 'no'}"
    )
    print(
        "stable_pose_is_primary: "
        f"{'yes' if stable_pose_ratio >= 0.5 else 'no'}"
    )
    print()


def print_failed_instances(failed: list[dict]) -> None:
    if not failed:
        return

    print("Failed instances")
    print("-" * 38)
    by_error = Counter(
        (
            row.get("base_factory_class") or "(unknown)",
            row.get("error_type") or "(unknown)",
        )
        for row in failed
    )
    for (base_factory, error_type), count in by_error.most_common():
        print(f"{base_factory:28s} error={error_type:20s} count={count:5d}")
    print()


def successful_rows(rows: list[dict]) -> list[dict]:
    return [row for row in rows if str(row.get("success", "")).lower() == "true"]


def failed_rows(rows: list[dict]) -> list[dict]:
    return [row for row in rows if str(row.get("success", "")).lower() != "true"]


def stable_pose_mode(row: dict) -> str:
    mode = row.get("stable_pose_mode", "")
    if mode:
        return mode
    if as_bool(row, "fast_stable_pose_used"):
        return "fast_bbox_bottom_align"
    return "original"


def summarize_totals(rows: list[dict]) -> dict:
    successful = successful_rows(rows)
    return {
        "csv_rows": len(rows),
        "successful": len(successful),
        "failed": len(rows) - len(successful),
        "total_duration": sum(as_float(row, DURATION_FIELD) for row in successful),
        "stable_pose_duration": sum(
            as_float(row, "stable_pose_duration") for row in successful
        ),
        "obj2trimesh_duration": sum(
            as_float(row, "obj2trimesh_duration") for row in successful
        ),
        "fast_stable_pose_duration": sum(
            as_float(row, "fast_stable_pose_duration") for row in successful
        ),
        "fast_used": sum(as_bool(row, "fast_stable_pose_used") for row in successful),
        "skipped_compute": sum(
            as_bool(row, "skipped_compute_stable_poses") for row in successful
        ),
        "materials": sum(as_int(row, "created_material_count") for row in successful),
        "textures": sum(as_int(row, "created_texture_count") for row in successful),
        "node_groups": sum(
            as_int(row, "created_node_group_count") for row in successful
        ),
        "meshes": sum(as_int(row, "created_mesh_count") for row in successful),
        "objects": sum(as_int(row, "created_object_count") for row in successful),
    }


def print_fast_mode_summary(successful: list[dict]) -> None:
    print("Fast stable pose mode summary")
    print("-" * 38)
    fast_enabled_count = sum(as_bool(row, "fast_stable_pose_enabled") for row in successful)
    fast_used_count = sum(as_bool(row, "fast_stable_pose_used") for row in successful)
    skipped_count = sum(as_bool(row, "skipped_compute_stable_poses") for row in successful)
    print(f"fast_stable_pose_enabled rows: {fast_enabled_count}")
    print(f"fast_stable_pose_used rows:    {fast_used_count}")
    print(f"skipped_compute_stable_poses:  {skipped_count}")
    print(
        "mode,count,total,avg,stable_pose_total,obj2trimesh_total,"
        "fast_pose_total"
    )
    by_mode = defaultdict(list)
    for row in successful:
        by_mode[stable_pose_mode(row)].append(row)
    for mode, rows in sorted(by_mode.items()):
        total = sum(as_float(row, DURATION_FIELD) for row in rows)
        print(
            f"{mode},"
            f"{len(rows)},"
            f"{total:.6f},"
            f"{total / len(rows) if rows else 0.0:.6f},"
            f"{sum(as_float(row, 'stable_pose_duration') for row in rows):.6f},"
            f"{sum(as_float(row, 'obj2trimesh_duration') for row in rows):.6f},"
            f"{sum(as_float(row, 'fast_stable_pose_duration') for row in rows):.6f}"
        )
    print()


def aggregate_by_base(rows: list[dict]) -> dict[str, dict]:
    by_base = defaultdict(lambda: defaultdict(float))
    for row in successful_rows(rows):
        base_factory = row.get("base_factory_class") or "(unknown)"
        stats = by_base[base_factory]
        stats["count"] += 1
        stats["total_duration"] += as_float(row, DURATION_FIELD)
        stats["stable_pose_duration"] += as_float(row, "stable_pose_duration")
        stats["obj2trimesh_duration"] += as_float(row, "obj2trimesh_duration")
        stats["fast_stable_pose_duration"] += as_float(
            row, "fast_stable_pose_duration"
        )
        stats["fast_used"] += int(as_bool(row, "fast_stable_pose_used"))
        stats["skipped_compute"] += int(as_bool(row, "skipped_compute_stable_poses"))
        for field in COUNT_FIELDS:
            stats[field] += as_int(row, field)
    return by_base


def speedup_text(baseline: float, candidate: float) -> str:
    if candidate <= 0:
        return "inf" if baseline > 0 else "0.000"
    return f"{baseline / candidate:.3f}"


def print_comparison_summary(baseline_rows: list[dict], candidate_rows: list[dict]):
    baseline = summarize_totals(baseline_rows)
    candidate = summarize_totals(candidate_rows)

    print("Baseline vs candidate comparison")
    print("=" * 38)
    print("metric,baseline,candidate,delta,speedup")
    for field in (
        "total_duration",
        "stable_pose_duration",
        "obj2trimesh_duration",
        "fast_stable_pose_duration",
    ):
        print(
            f"{field},"
            f"{baseline[field]:.6f},"
            f"{candidate[field]:.6f},"
            f"{candidate[field] - baseline[field]:.6f},"
            f"{speedup_text(baseline[field], candidate[field])}"
        )
    for field in ("csv_rows", "successful", "failed", "fast_used", "skipped_compute"):
        print(
            f"{field},"
            f"{baseline[field]},"
            f"{candidate[field]},"
            f"{candidate[field] - baseline[field]},"
            ""
        )
    print()

    print("Datablock/object count comparison")
    print("-" * 38)
    print("metric,baseline,candidate,delta")
    for field in ("materials", "textures", "node_groups", "meshes", "objects"):
        print(
            f"{field},"
            f"{baseline[field]},"
            f"{candidate[field]},"
            f"{candidate[field] - baseline[field]}"
        )
    print()

    print("Per base_factory speedup summary")
    print("-" * 38)
    print(
        "base_factory,count_base,count_cand,total_base,total_cand,total_speedup,"
        "stable_base,stable_cand,obj2_base,obj2_cand,fast_used,skipped_compute,"
        "materials_delta,meshes_delta,objects_delta"
    )
    baseline_by_base = aggregate_by_base(baseline_rows)
    candidate_by_base = aggregate_by_base(candidate_rows)
    for base_factory in sorted(
        set(baseline_by_base) | set(candidate_by_base),
        key=lambda name: baseline_by_base[name]["total_duration"],
        reverse=True,
    ):
        base_stats = baseline_by_base[base_factory]
        cand_stats = candidate_by_base[base_factory]
        print(
            f"{base_factory},"
            f"{int(base_stats['count'])},"
            f"{int(cand_stats['count'])},"
            f"{base_stats['total_duration']:.6f},"
            f"{cand_stats['total_duration']:.6f},"
            f"{speedup_text(base_stats['total_duration'], cand_stats['total_duration'])},"
            f"{base_stats['stable_pose_duration']:.6f},"
            f"{cand_stats['stable_pose_duration']:.6f},"
            f"{base_stats['obj2trimesh_duration']:.6f},"
            f"{cand_stats['obj2trimesh_duration']:.6f},"
            f"{int(cand_stats['fast_used'])},"
            f"{int(cand_stats['skipped_compute'])},"
            f"{int(cand_stats['created_material_count'] - base_stats['created_material_count'])},"
            f"{int(cand_stats['created_mesh_count'] - base_stats['created_mesh_count'])},"
            f"{int(cand_stats['created_object_count'] - base_stats['created_object_count'])}"
        )
    print()

    if candidate["failed"]:
        print("Candidate had failures; do not proceed to visual quality gate yet.")
    elif candidate["fast_used"] == 0:
        print("Candidate had no fast rows; check the fast-mode environment variable.")
    else:
        print(
            "No candidate failures were recorded. If the speedup is useful, "
            "the next gate is manual Blender/Isaac visual inspection for "
            "floating, inverted, or intersecting shell trinkets."
        )


def summarize_rows(rows: list[dict]) -> None:
    successful = successful_rows(rows)
    failed = failed_rows(rows)
    durations = [as_float(row, DURATION_FIELD) for row in successful]
    total_duration = sum(durations)
    max_duration = max(durations, default=0.0)
    avg_duration = total_duration / len(successful) if successful else 0.0

    print("NatureShelfTrinkets timing summary")
    print("=" * 38)
    print(f"csv_rows: {len(rows)}")
    print(f"successful_instances: {len(successful)}")
    print(f"failed_instances: {len(rows) - len(successful)}")
    print(f"total_duration: {fmt_seconds(total_duration)}")
    print(f"avg_duration:   {fmt_seconds(avg_duration)}")
    print(f"max_duration:   {fmt_seconds(max_duration)}")
    print()

    print_failed_instances(failed)
    print_fast_mode_summary(successful)

    print("Created datablock summary")
    print("-" * 38)
    for field in COUNT_FIELDS:
        values = [as_int(row, field) for row in successful]
        total = sum(values)
        avg = total / len(values) if values else 0.0
        print(
            f"{field:28s} total={total:7d} avg={avg:8.3f} "
            f"max={max(values, default=0):5d}"
        )
    print()

    print("Substage duration totals")
    print("-" * 38)
    substage_totals = {
        field: sum(as_float(row, field) for row in successful)
        for field in SUBSTAGE_FIELDS
    }
    for field, total in sorted(
        substage_totals.items(), key=lambda item: item[1], reverse=True
    ):
        print(f"{field:42s} {fmt_seconds(total)}")
    print()

    by_base = build_base_factory_stats(successful)
    print_base_factory_top(by_base)
    print_base_mesh_complexity(by_base)
    print_count_top(
        by_base,
        "created_material_count",
        "Created materials by base_factory_class top 20",
    )
    print_count_top(
        by_base,
        "created_texture_count",
        "Created textures by base_factory_class top 20",
    )
    print_count_top(
        by_base,
        "created_node_group_count",
        "Created node_groups by base_factory_class top 20",
    )
    print_cause_summary(successful, substage_totals)
    print_stable_pose_mesh_summary(successful)
    cache_counts = print_stable_pose_cache_key_summary(successful)
    print_slowest_stable_pose(successful)

    print("Slowest individual sample top 20")
    print("-" * 38)
    for row in sorted(
        successful, key=lambda item: as_float(item, DURATION_FIELD), reverse=True
    )[:20]:
        dominant_stage = max(
            SUBSTAGE_FIELDS, key=lambda field: as_float(row, field), default=""
        )
        print(
            f"{fmt_seconds(as_float(row, DURATION_FIELD))} "
            f"base={row.get('base_factory_class', ''):24s} "
            f"materials={as_int(row, 'created_material_count'):4d} "
            f"textures={as_int(row, 'created_texture_count'):4d} "
            f"node_groups={as_int(row, 'created_node_group_count'):4d} "
            f"vertices={as_int(row, 'mesh_vertex_count'):7d} "
            f"faces={as_int(row, 'mesh_face_count'):7d} "
            f"meshes={as_int(row, 'created_mesh_count'):4d} "
            f"objects={as_int(row, 'created_object_count'):4d} "
            f"dominant={dominant_stage}"
        )
    print()

    print("Repeated material/texture/node_group name signals")
    print("-" * 38)
    repeated_any = False
    for label, field in NAME_FIELDS:
        normalized_counts = Counter()
        distinct_names_by_base = defaultdict(set)
        for row in successful:
            for name in split_names(row.get(field, "")):
                base_name = normalize_blender_name(name)
                normalized_counts[base_name] += 1
                distinct_names_by_base[base_name].add(name)
        repeated = [
            (name, count, len(distinct_names_by_base[name]))
            for name, count in normalized_counts.items()
            if count > 1
        ]
        repeated.sort(key=lambda item: item[1], reverse=True)
        print(f"{label}: repeated_base_names={len(repeated)}")
        for name, count, distinct_count in repeated[:20]:
            repeated_any = True
            print(
                f"  {name:40s} total_created={count:5d} "
                f"distinct_suffixed_names={distinct_count:5d}"
            )
    print()

    print("Recommended next optimization direction")
    print("-" * 38)
    if not successful:
        print("No successful timing rows were found; collect a populate sample first.")
        return

    created_totals = {
        field: sum(as_int(row, field) for row in successful) for field in COUNT_FIELDS
    }
    dominant_substage = max(substage_totals, key=substage_totals.get)
    top_base = max(by_base, key=lambda name: by_base[name][f"{DURATION_FIELD}_total"])
    repeated_cache_keys = sum(1 for count in cache_counts.values() if count > 1)

    print(
        f"Top base factory by duration is {top_base}; first inspect its "
        "asset generation path before broad reuse changes."
    )
    print(
        f"Dominant measured substage is {dominant_substage} "
        f"({fmt_seconds(substage_totals[dominant_substage])})."
    )

    if repeated_any and (
        created_totals["created_material_count"]
        or created_totals["created_texture_count"]
        or created_totals["created_node_group_count"]
    ):
        print(
            "There is a repeated-name signal, so material/texture/nodegroup "
            "template reuse is worth investigating behind a separate opt-in gate."
        )
    else:
        print(
            "The CSV does not show a strong repeated-name signal; prioritize "
            "base-factory spawn, mesh realization, or stable-pose costs first."
        )

    stable_pose_pipeline_total = substage_totals.get(
        "stable_pose_duration", 0.0
    ) + substage_totals.get("obj2trimesh_duration", 0.0)
    if ratio(stable_pose_pipeline_total, total_duration) >= 0.5:
        if repeated_cache_keys:
            print(
                "Stable-pose work is primary and repeated candidate keys exist; "
                "consider an exact opt-in stable-pose cache experiment next."
            )
        else:
            print(
                "Stable-pose work is primary but candidate keys did not repeat; "
                "prioritize mesh complexity or opt-in stable-pose simplification "
                "before an exact cache."
            )

    if len(successful) < 10:
        print(
            "This is a very small sample. Treat single slow rows as leads, not "
            "as enough evidence for a behavior change."
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyze NatureShelfTrinketsFactory timing CSV output."
    )
    parser.add_argument(
        "csv_path",
        nargs="?",
        type=Path,
        default=DEFAULT_CSV,
        help=f"Timing CSV path. Defaults to {DEFAULT_CSV}",
    )
    parser.add_argument(
        "compare_csv_path",
        nargs="?",
        type=Path,
        default=None,
        help="Optional candidate CSV path for baseline vs candidate comparison.",
    )
    args = parser.parse_args()

    if not args.csv_path.exists():
        raise SystemExit(f"CSV not found: {args.csv_path}")
    if args.compare_csv_path is not None and not args.compare_csv_path.exists():
        raise SystemExit(f"CSV not found: {args.compare_csv_path}")

    rows = read_rows(args.csv_path)
    summarize_rows(rows)
    if args.compare_csv_path is not None:
        print()
        print_comparison_summary(rows, read_rows(args.compare_csv_path))


if __name__ == "__main__":
    main()
