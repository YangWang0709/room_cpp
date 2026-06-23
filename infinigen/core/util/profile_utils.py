# Copyright (C) 2024, Princeton University.
# This source code is licensed under the BSD 3-Clause license found in the LICENSE file in the root directory of this source tree.

import csv
import os
import re
import sys
from collections import Counter
from pathlib import Path

import bpy


DATABLOCK_KEYS = ("material", "texture", "node_group", "mesh", "object", "image")


def env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def solver_output_csv_path(
    csv_name: str,
    fallback_path: Path,
    explicit_env_var: str | None = None,
) -> Path:
    if explicit_env_var:
        explicit_path = os.environ.get(explicit_env_var)
        if explicit_path:
            return Path(explicit_path)

    solver_timing = sys.modules.get("infinigen.core.constraints.example_solver.timing")
    if solver_timing is not None:
        current_output_folder = getattr(solver_timing, "current_output_folder", None)
        if current_output_folder is not None:
            output_folder = current_output_folder()
            if output_folder is not None:
                return Path(output_folder) / csv_name
    return fallback_path


def write_csv_row(path: Path, fieldnames: list[str], row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.exists() or path.stat().st_size == 0
    with path.open("a", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()
        writer.writerow({field: row.get(field, "") for field in fieldnames})


def bpy_datablock_name_sets(include_images: bool = True) -> dict[str, set[str]]:
    sets = {
        "material": set(bpy.data.materials.keys()),
        "texture": set(bpy.data.textures.keys()),
        "node_group": set(bpy.data.node_groups.keys()),
        "mesh": set(bpy.data.meshes.keys()),
        "object": set(bpy.data.objects.keys()),
    }
    if include_images:
        sets["image"] = set(bpy.data.images.keys())
    return sets


def add_datablock_before_counts(row: dict, before_sets: dict[str, set[str]]) -> None:
    for key, names in before_sets.items():
        row[f"{key}_count_before"] = len(names)


def strip_blender_numeric_suffix(name: str) -> str:
    return re.sub(r"\.\d{3,}$", "", name)


def datablock_prefix(name: str) -> str:
    base = strip_blender_numeric_suffix(name)
    if base.startswith("nodegroup_"):
        parts = base.split("_")
        return "_".join(parts[:3]) if len(parts) >= 3 else base
    if "." in base:
        return base.split(".", 1)[0]
    return base


def prefix_top_text(names: list[str], limit: int = 8) -> str:
    counts = Counter(datablock_prefix(name) for name in names)
    return ";".join(
        f"{prefix}:{count}" for prefix, count in counts.most_common(limit)
    )


def add_datablock_after_counts(
    row: dict,
    before_sets: dict[str, set[str]],
    include_name_samples: bool = False,
    sample_limit: int = 20,
    prefix_limit: int = 8,
) -> dict[str, list[str]]:
    after_sets = bpy_datablock_name_sets(include_images="image" in before_sets)
    created_by_key = {}
    for key, before_names in before_sets.items():
        after_names = after_sets[key]
        created_names = sorted(after_names - before_names)
        created_by_key[key] = created_names
        row[f"{key}_count_after"] = len(after_names)
        row[f"created_{key}_count"] = len(created_names)
        if include_name_samples:
            row[f"created_{key}_names_sample"] = ";".join(
                created_names[:sample_limit]
            )
            row[f"created_{key}_prefix_top"] = prefix_top_text(
                created_names, prefix_limit
            )
    return created_by_key
