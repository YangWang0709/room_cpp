#!/usr/bin/env python3
"""Compare USD/Isaac-relevant static scene summaries from two Blender files."""

from __future__ import annotations

import argparse
import math
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_TRANSFORM_ATOL = 1e-6
DEFAULT_MAX_DIFFS = 20


@dataclass
class ObjectSummary:
    name: str
    type: str
    parent: str | None
    hide_render: bool
    hide_viewport: bool
    location: tuple[float, ...]
    rotation_mode: str
    rotation: tuple[float, ...]
    scale: tuple[float, ...]
    matrix_world: tuple[float, ...]
    mesh_name: str | None
    mesh_vertices: int | None
    mesh_edges: int | None
    mesh_polygons: int | None
    material_slots: tuple[str | None, ...]
    linked_node_groups: tuple[str, ...]


@dataclass
class BlendSummary:
    path: Path
    objects: dict[str, ObjectSummary]
    linked_mesh_names: set[str]
    linked_material_names: set[str]
    linked_node_group_names: set[str]
    all_mesh_names: set[str]
    all_material_names: set[str]
    all_node_group_names: set[str]
    object_type_counts: dict[str, int]

    @property
    def unused_mesh_names(self) -> set[str]:
        return self.all_mesh_names - self.linked_mesh_names

    @property
    def unused_material_names(self) -> set[str]:
        return self.all_material_names - self.linked_material_names

    @property
    def unused_node_group_names(self) -> set[str]:
        return self.all_node_group_names - self.linked_node_group_names


@dataclass
class Difference:
    path: str
    reason: str
    left: Any
    right: Any


@dataclass
class DiffBucket:
    max_diffs: int
    differences: list[Difference] = field(default_factory=list)
    total: int = 0

    def add(self, path: str, reason: str, left: Any, right: Any) -> None:
        self.total += 1
        if len(self.differences) < self.max_diffs:
            self.differences.append(
                Difference(path=path, reason=reason, left=left, right=right)
            )


def argv_after_blender_separator(argv: list[str]) -> list[str]:
    if "--" in argv:
        return argv[argv.index("--") + 1 :]
    return argv[1:]


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare two .blend files, or two Infinigen coarse output folders "
            "containing scene.blend, using a Blender static-scene summary."
        )
    )
    parser.add_argument("left", type=Path, help="Left .blend or coarse output folder")
    parser.add_argument("right", type=Path, help="Right .blend or coarse output folder")
    parser.add_argument(
        "--transform-atol",
        type=float,
        default=DEFAULT_TRANSFORM_ATOL,
        help=(
            "Absolute tolerance for location, rotation, scale, and matrix values. "
            f"Default: {DEFAULT_TRANSFORM_ATOL}"
        ),
    )
    parser.add_argument(
        "--max-diffs",
        type=int,
        default=DEFAULT_MAX_DIFFS,
        help=f"Maximum differences to print per section. Default: {DEFAULT_MAX_DIFFS}",
    )
    return parser.parse_args(argv)


def resolve_blend_path(path: Path) -> Path:
    if path.is_dir():
        path = path / "scene.blend"
    if not path.exists():
        raise SystemExit(f"Blend file does not exist: {path}")
    if not path.is_file():
        raise SystemExit(f"Blend path is not a file: {path}")
    if path.suffix.lower() != ".blend":
        raise SystemExit(f"Expected a .blend file or folder containing scene.blend: {path}")
    return path


def find_blender_binary() -> str:
    candidates = []
    env_blender = os.environ.get("BLENDER_BIN")
    if env_blender:
        candidates.append(Path(env_blender))
    if shutil.which("blender"):
        candidates.append(Path(shutil.which("blender") or ""))

    repo_root = Path(__file__).resolve().parents[1]
    candidates.extend(
        [
            repo_root / "blender" / "blender",
            Path.cwd() / "blender" / "blender",
            Path("/opt/infinigen/blender/blender"),
        ]
    )

    for candidate in candidates:
        if candidate and candidate.exists() and os.access(candidate, os.X_OK):
            return str(candidate)

    raise SystemExit(
        "Could not import bpy and could not find Blender. Set BLENDER_BIN to "
        "a Blender executable or run this script with blender --background --python."
    )


def rerun_under_blender(argv: list[str]) -> int:
    blender = find_blender_binary()
    command = [blender, "--background", "--python", str(Path(__file__).resolve()), "--"]
    command.extend(argv)
    completed = subprocess.run(command, check=False)
    return completed.returncode


def vector_tuple(values: Any) -> tuple[float, ...]:
    return tuple(float(v) for v in values)


def matrix_tuple(matrix: Any) -> tuple[float, ...]:
    return tuple(float(value) for row in matrix for value in row)


def collect_node_groups_from_tree(node_tree: Any, names: set[str], seen: set[int]) -> None:
    if node_tree is None:
        return
    pointer = int(node_tree.as_pointer())
    if pointer in seen:
        return
    seen.add(pointer)
    names.add(node_tree.name)

    try:
        nodes = list(node_tree.nodes)
    except Exception:
        return

    for node in nodes:
        child_tree = getattr(node, "node_tree", None)
        if child_tree is not None:
            collect_node_groups_from_tree(child_tree, names, seen)


def collect_modifier_node_groups(obj: Any) -> set[str]:
    names: set[str] = set()
    seen: set[int] = set()
    for modifier in getattr(obj, "modifiers", []):
        node_group = getattr(modifier, "node_group", None)
        if node_group is not None:
            collect_node_groups_from_tree(node_group, names, seen)
    return names


def collect_material_node_groups(material: Any) -> set[str]:
    names: set[str] = set()
    if material is None or not getattr(material, "use_nodes", False):
        return names
    collect_node_groups_from_tree(getattr(material, "node_tree", None), names, set())
    return names


def collect_object_summary(obj: Any) -> ObjectSummary:
    mesh_name = None
    mesh_vertices = None
    mesh_edges = None
    mesh_polygons = None
    if obj.type == "MESH" and obj.data is not None:
        mesh_name = obj.data.name
        mesh_vertices = len(obj.data.vertices)
        mesh_edges = len(obj.data.edges)
        mesh_polygons = len(obj.data.polygons)

    material_slots = tuple(
        slot.material.name if slot.material is not None else None
        for slot in getattr(obj, "material_slots", [])
    )

    linked_node_groups = collect_modifier_node_groups(obj)
    for slot in getattr(obj, "material_slots", []):
        linked_node_groups.update(collect_material_node_groups(slot.material))

    if obj.rotation_mode == "QUATERNION":
        rotation = vector_tuple(obj.rotation_quaternion)
    elif obj.rotation_mode == "AXIS_ANGLE":
        rotation = vector_tuple(obj.rotation_axis_angle)
    else:
        rotation = vector_tuple(obj.rotation_euler)

    return ObjectSummary(
        name=obj.name,
        type=obj.type,
        parent=obj.parent.name if obj.parent is not None else None,
        hide_render=bool(obj.hide_render),
        hide_viewport=bool(obj.hide_viewport),
        location=vector_tuple(obj.location),
        rotation_mode=str(obj.rotation_mode),
        rotation=rotation,
        scale=vector_tuple(obj.scale),
        matrix_world=matrix_tuple(obj.matrix_world),
        mesh_name=mesh_name,
        mesh_vertices=mesh_vertices,
        mesh_edges=mesh_edges,
        mesh_polygons=mesh_polygons,
        material_slots=material_slots,
        linked_node_groups=tuple(sorted(linked_node_groups)),
    )


def collect_blend_summary(path: Path, bpy: Any) -> BlendSummary:
    bpy.ops.wm.open_mainfile(filepath=str(path))
    bpy.context.view_layer.update()

    objects = {obj.name: collect_object_summary(obj) for obj in bpy.data.objects}
    linked_mesh_names = {
        summary.mesh_name for summary in objects.values() if summary.mesh_name is not None
    }
    linked_material_names = {
        material_name
        for summary in objects.values()
        for material_name in summary.material_slots
        if material_name is not None
    }
    linked_node_group_names = {
        node_group
        for summary in objects.values()
        for node_group in summary.linked_node_groups
    }

    object_type_counts: dict[str, int] = {}
    for summary in objects.values():
        object_type_counts[summary.type] = object_type_counts.get(summary.type, 0) + 1

    return BlendSummary(
        path=path,
        objects=objects,
        linked_mesh_names=linked_mesh_names,
        linked_material_names=linked_material_names,
        linked_node_group_names=linked_node_group_names,
        all_mesh_names={mesh.name for mesh in bpy.data.meshes},
        all_material_names={material.name for material in bpy.data.materials},
        all_node_group_names={node_group.name for node_group in bpy.data.node_groups},
        object_type_counts=object_type_counts,
    )


def short_list(values: set[str], limit: int = 12) -> list[str]:
    return sorted(values)[:limit]


def compare_sets(
    left: set[str],
    right: set[str],
    path: str,
    bucket: DiffBucket,
) -> None:
    missing = left - right
    extra = right - left
    if missing:
        bucket.add(path, "names missing from right", short_list(missing), len(missing))
    if extra:
        bucket.add(path, "names extra in right", short_list(extra), len(extra))


def compare_scalar(
    left: Any,
    right: Any,
    path: str,
    bucket: DiffBucket,
) -> None:
    if left != right:
        bucket.add(path, "values differ", left, right)


def max_abs_diff(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    if len(left) != len(right):
        return math.inf
    return max((abs(a - b) for a, b in zip(left, right)), default=0.0)


def compare_vector(
    left: tuple[float, ...],
    right: tuple[float, ...],
    path: str,
    atol: float,
    bucket: DiffBucket,
) -> None:
    diff = max_abs_diff(left, right)
    if diff > atol:
        bucket.add(path, f"max abs diff {diff} exceeds tolerance {atol}", left, right)


def compare_object_summaries(
    left: BlendSummary,
    right: BlendSummary,
    *,
    transform_atol: float,
    bucket: DiffBucket,
) -> None:
    compare_scalar(len(left.objects), len(right.objects), "object_count", bucket)
    compare_scalar(left.object_type_counts, right.object_type_counts, "object_type_counts", bucket)
    compare_sets(set(left.objects), set(right.objects), "object_names", bucket)

    for name in sorted(set(left.objects) & set(right.objects)):
        left_obj = left.objects[name]
        right_obj = right.objects[name]
        prefix = f"objects.{name}"

        compare_scalar(left_obj.type, right_obj.type, f"{prefix}.type", bucket)
        compare_scalar(left_obj.parent, right_obj.parent, f"{prefix}.parent", bucket)
        compare_scalar(
            left_obj.hide_render, right_obj.hide_render, f"{prefix}.hide_render", bucket
        )
        compare_scalar(
            left_obj.hide_viewport,
            right_obj.hide_viewport,
            f"{prefix}.hide_viewport",
            bucket,
        )
        compare_scalar(
            left_obj.rotation_mode,
            right_obj.rotation_mode,
            f"{prefix}.rotation_mode",
            bucket,
        )
        compare_vector(
            left_obj.location,
            right_obj.location,
            f"{prefix}.location",
            transform_atol,
            bucket,
        )
        compare_vector(
            left_obj.rotation,
            right_obj.rotation,
            f"{prefix}.rotation",
            transform_atol,
            bucket,
        )
        compare_vector(
            left_obj.scale,
            right_obj.scale,
            f"{prefix}.scale",
            transform_atol,
            bucket,
        )
        compare_vector(
            left_obj.matrix_world,
            right_obj.matrix_world,
            f"{prefix}.matrix_world",
            transform_atol,
            bucket,
        )
        compare_scalar(left_obj.mesh_name, right_obj.mesh_name, f"{prefix}.mesh_name", bucket)
        compare_scalar(
            left_obj.mesh_vertices,
            right_obj.mesh_vertices,
            f"{prefix}.mesh_vertices",
            bucket,
        )
        compare_scalar(
            left_obj.mesh_edges, right_obj.mesh_edges, f"{prefix}.mesh_edges", bucket
        )
        compare_scalar(
            left_obj.mesh_polygons,
            right_obj.mesh_polygons,
            f"{prefix}.mesh_polygons",
            bucket,
        )
        compare_scalar(
            left_obj.material_slots,
            right_obj.material_slots,
            f"{prefix}.material_slots",
            bucket,
        )
        compare_scalar(
            left_obj.linked_node_groups,
            right_obj.linked_node_groups,
            f"{prefix}.linked_node_groups",
            bucket,
        )


def compare_static_scene(
    left: BlendSummary,
    right: BlendSummary,
    *,
    transform_atol: float,
    max_diffs: int,
) -> tuple[DiffBucket, DiffBucket]:
    static_diffs = DiffBucket(max_diffs=max_diffs)
    unused_diffs = DiffBucket(max_diffs=max_diffs)

    compare_object_summaries(
        left, right, transform_atol=transform_atol, bucket=static_diffs
    )
    compare_scalar(
        len(left.linked_mesh_names),
        len(right.linked_mesh_names),
        "linked_mesh_datablock_count",
        static_diffs,
    )
    compare_sets(left.linked_mesh_names, right.linked_mesh_names, "linked_mesh_names", static_diffs)
    compare_scalar(
        len(left.linked_material_names),
        len(right.linked_material_names),
        "linked_material_count",
        static_diffs,
    )
    compare_sets(
        left.linked_material_names,
        right.linked_material_names,
        "linked_material_names",
        static_diffs,
    )
    compare_scalar(
        len(left.linked_node_group_names),
        len(right.linked_node_group_names),
        "linked_node_group_count",
        static_diffs,
    )
    compare_sets(
        left.linked_node_group_names,
        right.linked_node_group_names,
        "linked_node_group_names",
        static_diffs,
    )

    compare_scalar(
        len(left.unused_mesh_names),
        len(right.unused_mesh_names),
        "unused_mesh_datablock_count",
        unused_diffs,
    )
    compare_sets(left.unused_mesh_names, right.unused_mesh_names, "unused_mesh_names", unused_diffs)
    compare_scalar(
        len(left.unused_material_names),
        len(right.unused_material_names),
        "unused_material_count",
        unused_diffs,
    )
    compare_sets(
        left.unused_material_names,
        right.unused_material_names,
        "unused_material_names",
        unused_diffs,
    )
    compare_scalar(
        len(left.unused_node_group_names),
        len(right.unused_node_group_names),
        "unused_node_group_count",
        unused_diffs,
    )
    compare_sets(
        left.unused_node_group_names,
        right.unused_node_group_names,
        "unused_node_group_names",
        unused_diffs,
    )

    return static_diffs, unused_diffs


def print_summary(label: str, summary: BlendSummary) -> None:
    print(f"{label}_blend: {summary.path}")
    print(f"{label}_object_count: {len(summary.objects)}")
    print(f"{label}_object_type_counts: {summary.object_type_counts}")
    print(f"{label}_linked_mesh_datablock_count: {len(summary.linked_mesh_names)}")
    print(f"{label}_all_mesh_datablock_count: {len(summary.all_mesh_names)}")
    print(f"{label}_unused_mesh_datablock_count: {len(summary.unused_mesh_names)}")
    print(f"{label}_linked_material_count: {len(summary.linked_material_names)}")
    print(f"{label}_all_material_count: {len(summary.all_material_names)}")
    print(f"{label}_unused_material_count: {len(summary.unused_material_names)}")
    print(f"{label}_linked_node_group_count: {len(summary.linked_node_group_names)}")
    print(f"{label}_all_node_group_count: {len(summary.all_node_group_names)}")
    print(f"{label}_unused_node_group_count: {len(summary.unused_node_group_names)}")


def print_diffs(title: str, bucket: DiffBucket) -> None:
    print(f"{title}_diff_count: {bucket.total}")
    for diff in bucket.differences:
        print(f"  - {diff.path}: {diff.reason}")
        print(f"    left:  {diff.left}")
        print(f"    right: {diff.right}")
    if bucket.total > len(bucket.differences):
        print(f"  ... {bucket.total - len(bucket.differences)} more differences omitted")


def run_in_blender(args: argparse.Namespace, bpy: Any) -> int:
    left_path = resolve_blend_path(args.left)
    right_path = resolve_blend_path(args.right)

    print("=== compare_blend_static_scene.py ===")
    print(f"left: {left_path}")
    print(f"right: {right_path}")
    print(f"transform_atol: {args.transform_atol}")

    left_summary = collect_blend_summary(left_path, bpy)
    right_summary = collect_blend_summary(right_path, bpy)
    static_diffs, unused_diffs = compare_static_scene(
        left_summary,
        right_summary,
        transform_atol=args.transform_atol,
        max_diffs=args.max_diffs,
    )

    print()
    print("summary:")
    print_summary("left", left_summary)
    print_summary("right", right_summary)

    print()
    print_diffs("static_scene", static_diffs)
    print()
    print_diffs("unused_datablock", unused_diffs)

    static_pass = static_diffs.total == 0
    unused_diff = unused_diffs.total > 0
    unused_only = static_pass and unused_diff

    print()
    print("STATIC_SCENE_PASS" if static_pass else "STATIC_SCENE_FAIL")
    print(f"USD_RELEVANT_DIFF: {'yes' if not static_pass else 'no'}")
    print(f"UNUSED_DATABLOCK_DIFF: {'yes' if unused_diff else 'no'}")
    print(f"UNUSED_DATABLOCK_DIFF_ONLY: {'yes' if unused_only else 'no'}")
    if not static_pass:
        print("DIFF_CLASS: USD_RELEVANT_DIFF")
    elif unused_only:
        print("DIFF_CLASS: UNUSED_DATABLOCK_DIFF_ONLY")
    else:
        print("DIFF_CLASS: NO_DIFF")

    return 0 if static_pass else 1


def main() -> int:
    argv = argv_after_blender_separator(sys.argv)
    args = parse_args(argv)

    try:
        import bpy  # type: ignore
    except ModuleNotFoundError:
        return rerun_under_blender(argv)

    return run_in_blender(args, bpy)


if __name__ == "__main__":
    raise SystemExit(main())
