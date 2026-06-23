#!/usr/bin/env python3
"""Compare JSON metadata from two Infinigen indoor coarse output folders."""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_ATOL = 1e-6
DEFAULT_RTOL = 1e-6
DEFAULT_MAX_DIFFS = 20

IGNORED_FIELD_NAMES = {
    "created_at",
    "cwd",
    "date",
    "datetime",
    "duration",
    "elapsed",
    "elapsed_seconds",
    "end_time",
    "host",
    "hostname",
    "log_file",
    "log_path",
    "machine",
    "machine_name",
    "platform",
    "profile_file",
    "profile_path",
    "run_time",
    "runtime",
    "runtime_seconds",
    "start_time",
    "tempdir",
    "temporary_directory",
    "time",
    "time_stamp",
    "timestamp",
    "tmpdir",
    "updated_at",
    "wall_time",
    "walltime",
    "working_dir",
    "workdir",
}

IGNORED_FIELD_SUFFIXES = (
    "_duration",
    "_duration_s",
    "_duration_seconds",
    "_elapsed",
    "_elapsed_s",
    "_elapsed_seconds",
    "_runtime",
    "_runtime_s",
    "_runtime_seconds",
    "_time_stamp",
    "_timestamp",
    "_wall_time",
    "_wall_time_s",
    "_wall_time_seconds",
)

UNORDERED_LIST_FIELD_NAMES = {
    "child_tags",
    "parent_tags",
    "tags",
}

TEMP_PATH_RE = re.compile(r"(?<![\w.-])/(?:tmp|var/tmp)/[^\s\"'<>:,;]+")
HOME_REPO_RE = re.compile(r"/home/[^/\s\"'<>:,;]+/infinigen")
WINDOWS_TEMP_RE = re.compile(
    r"(?i)(?:[a-z]:\\(?:users\\[^\\\s\"'<>:,;]+\\)?appdata\\local\\temp)"
    r"\\[^\s\"'<>:,;]+"
)


@dataclass
class NumericStats:
    count: int = 0
    max_abs_diff: float = 0.0

    def add(self, left: float, right: float) -> None:
        self.count += 1
        diff = abs(left - right)
        if math.isfinite(diff):
            self.max_abs_diff = max(self.max_abs_diff, diff)

    def merge(self, other: "NumericStats") -> None:
        self.count += other.count
        self.max_abs_diff = max(self.max_abs_diff, other.max_abs_diff)


@dataclass
class Difference:
    path: str
    reason: str
    left: Any
    right: Any


@dataclass
class FileResult:
    relpath: str
    same: bool
    comparable: bool
    numeric_stats: NumericStats = field(default_factory=NumericStats)
    differences: list[Difference] = field(default_factory=list)
    total_differences: int = 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare canonicalized JSON files from two Infinigen indoor coarse "
            "output directories."
        )
    )
    parser.add_argument("left", type=Path, help="Baseline output folder")
    parser.add_argument("right", type=Path, help="Candidate output folder")
    parser.add_argument(
        "--rtol",
        type=float,
        default=DEFAULT_RTOL,
        help=f"Relative tolerance for numeric values. Default: {DEFAULT_RTOL}",
    )
    parser.add_argument(
        "--atol",
        type=float,
        default=DEFAULT_ATOL,
        help=f"Absolute tolerance for numeric values. Default: {DEFAULT_ATOL}",
    )
    parser.add_argument(
        "--max-diffs",
        type=int,
        default=DEFAULT_MAX_DIFFS,
        help=f"Maximum differences to print per file. Default: {DEFAULT_MAX_DIFFS}",
    )
    return parser.parse_args()


def is_ignored_key(key: str) -> bool:
    lowered = key.lower()
    return lowered in IGNORED_FIELD_NAMES or any(
        lowered.endswith(suffix) for suffix in IGNORED_FIELD_SUFFIXES
    )


def replacement_roots(root: Path) -> list[tuple[str, str]]:
    roots = []
    for candidate, label in (
        (root, "<OUTPUT_ROOT>"),
        (root.parent, "<OUTPUT_PARENT>"),
    ):
        for value in {candidate, candidate.resolve()}:
            text = str(value)
            if text and text != ".":
                roots.append((text, label))
    roots.sort(key=lambda item: len(item[0]), reverse=True)
    return roots


def normalize_string(value: str, root: Path) -> str:
    normalized = value
    for actual, label in replacement_roots(root):
        normalized = normalized.replace(actual, label)
    normalized = normalized.replace("/opt/infinigen", "<REPO_ROOT>")
    normalized = HOME_REPO_RE.sub("<REPO_ROOT>", normalized)
    normalized = TEMP_PATH_RE.sub("<TEMP_PATH>", normalized)
    normalized = WINDOWS_TEMP_RE.sub("<TEMP_PATH>", normalized)
    return normalized


def sort_key(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def should_sort_list(field_name: str | None, values: list[Any]) -> bool:
    if field_name is None or field_name.lower() not in UNORDERED_LIST_FIELD_NAMES:
        return False
    return all(not isinstance(value, (dict, list)) for value in values)


def canonicalize(value: Any, root: Path, field_name: str | None = None) -> Any:
    if isinstance(value, dict):
        return {
            key: canonicalize(value[key], root, str(key))
            for key in sorted(value)
            if not is_ignored_key(str(key))
        }
    if isinstance(value, list):
        values = [canonicalize(item, root) for item in value]
        if should_sort_list(field_name, values):
            return sorted(values, key=sort_key)
        return values
    if isinstance(value, str):
        return normalize_string(value, root)
    return value


def find_json_files(root: Path) -> dict[str, Path]:
    if not root.exists():
        raise SystemExit(f"Output folder does not exist: {root}")
    if not root.is_dir():
        raise SystemExit(f"Output path is not a directory: {root}")
    result = {}
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() == ".json":
            result[path.relative_to(root).as_posix()] = path
    return result


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def short_value(value: Any, limit: int = 180) -> str:
    try:
        text = json.dumps(value, sort_keys=True, ensure_ascii=False)
    except TypeError:
        text = repr(value)
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def record_difference(
    differences: list[Difference],
    path: str,
    reason: str,
    left: Any,
    right: Any,
    max_diffs: int,
) -> None:
    if len(differences) < max_diffs:
        differences.append(Difference(path=path, reason=reason, left=left, right=right))


def compare_values(
    left: Any,
    right: Any,
    path: str,
    *,
    rtol: float,
    atol: float,
    max_diffs: int,
    differences: list[Difference],
    numeric_stats: NumericStats,
) -> int:
    total_differences = 0

    if is_number(left) and is_number(right):
        left_float = float(left)
        right_float = float(right)
        numeric_stats.add(left_float, right_float)
        if math.isnan(left_float) and math.isnan(right_float):
            return 0
        if not math.isclose(left_float, right_float, rel_tol=rtol, abs_tol=atol):
            record_difference(
                differences,
                path,
                "numeric values differ beyond tolerance",
                left,
                right,
                max_diffs,
            )
            return 1
        return 0

    if type(left) is not type(right):
        record_difference(
            differences,
            path,
            "types differ",
            type(left).__name__,
            type(right).__name__,
            max_diffs,
        )
        return 1

    if isinstance(left, dict):
        left_keys = set(left)
        right_keys = set(right)
        for key in sorted(left_keys - right_keys):
            record_difference(
                differences,
                f"{path}.{key}",
                "key missing from right",
                left[key],
                "<missing>",
                max_diffs,
            )
            total_differences += 1
        for key in sorted(right_keys - left_keys):
            record_difference(
                differences,
                f"{path}.{key}",
                "key missing from left",
                "<missing>",
                right[key],
                max_diffs,
            )
            total_differences += 1
        for key in sorted(left_keys & right_keys):
            total_differences += compare_values(
                left[key],
                right[key],
                f"{path}.{key}",
                rtol=rtol,
                atol=atol,
                max_diffs=max_diffs,
                differences=differences,
                numeric_stats=numeric_stats,
            )
        return total_differences

    if isinstance(left, list):
        if len(left) != len(right):
            record_difference(
                differences,
                path,
                "list lengths differ",
                len(left),
                len(right),
                max_diffs,
            )
            total_differences += 1
        for index, (left_item, right_item) in enumerate(zip(left, right)):
            total_differences += compare_values(
                left_item,
                right_item,
                f"{path}[{index}]",
                rtol=rtol,
                atol=atol,
                max_diffs=max_diffs,
                differences=differences,
                numeric_stats=numeric_stats,
            )
        return total_differences

    if left != right:
        record_difference(
            differences, path, "values differ", left, right, max_diffs
        )
        return 1

    return 0


def compare_file(
    relpath: str,
    left_path: Path,
    right_path: Path,
    left_root: Path,
    right_root: Path,
    *,
    rtol: float,
    atol: float,
    max_diffs: int,
) -> FileResult:
    differences: list[Difference] = []
    numeric_stats = NumericStats()

    try:
        left_json = canonicalize(load_json(left_path), left_root)
    except Exception as exc:  # noqa: BLE001 - report malformed comparison input.
        differences.append(
            Difference(
                path="$",
                reason="failed to parse left JSON",
                left=str(left_path),
                right=f"{exc.__class__.__name__}: {exc}",
            )
        )
        return FileResult(
            relpath=relpath,
            same=False,
            comparable=False,
            differences=differences,
            total_differences=1,
        )

    try:
        right_json = canonicalize(load_json(right_path), right_root)
    except Exception as exc:  # noqa: BLE001 - report malformed comparison input.
        differences.append(
            Difference(
                path="$",
                reason="failed to parse right JSON",
                left=str(right_path),
                right=f"{exc.__class__.__name__}: {exc}",
            )
        )
        return FileResult(
            relpath=relpath,
            same=False,
            comparable=False,
            differences=differences,
            total_differences=1,
        )

    total_differences = compare_values(
        left_json,
        right_json,
        "$",
        rtol=rtol,
        atol=atol,
        max_diffs=max_diffs,
        differences=differences,
        numeric_stats=numeric_stats,
    )
    return FileResult(
        relpath=relpath,
        same=(total_differences == 0),
        comparable=True,
        numeric_stats=numeric_stats,
        differences=differences,
        total_differences=total_differences,
    )


def print_file_list(title: str, files: list[str]) -> None:
    if not files:
        print(f"{title}: 0")
        return
    print(f"{title}: {len(files)}")
    for relpath in files:
        print(f"  {relpath}")


def print_result(result: FileResult, max_diffs: int) -> None:
    status = "SAME" if result.same else "DIFFERENT"
    if result.numeric_stats.count:
        max_diff = f"{result.numeric_stats.max_abs_diff:.12g}"
    else:
        max_diff = "n/a"
    print(
        f"  {status} {result.relpath} "
        f"numeric_max_abs_diff={max_diff}"
    )
    for diff in result.differences:
        print(f"    - {diff.path}: {diff.reason}")
        print(f"      left:  {short_value(diff.left)}")
        print(f"      right: {short_value(diff.right)}")
    omitted = result.total_differences - min(result.total_differences, max_diffs)
    if omitted > 0:
        print(f"    ... {omitted} additional differences omitted")


def main() -> int:
    args = parse_args()
    if args.max_diffs < 0:
        raise SystemExit("--max-diffs must be non-negative")

    left_root = args.left
    right_root = args.right

    left_files = find_json_files(left_root)
    right_files = find_json_files(right_root)
    common = sorted(set(left_files) & set(right_files))
    missing = sorted(set(left_files) - set(right_files))
    extra = sorted(set(right_files) - set(left_files))

    print(f"left: {left_root}")
    print(f"right: {right_root}")
    print(f"matched_json_file_count: {len(common)}")
    print_file_list("missing_files", missing)
    print_file_list("extra_files", extra)

    if not common:
        print("NO_COMPARABLE_JSON_FOUND")
        print("FINAL: FAIL")
        return 2

    results = [
        compare_file(
            relpath,
            left_files[relpath],
            right_files[relpath],
            left_root,
            right_root,
            rtol=args.rtol,
            atol=args.atol,
            max_diffs=args.max_diffs,
        )
        for relpath in common
    ]

    comparable_results = [result for result in results if result.comparable]
    if not comparable_results:
        print("NO_COMPARABLE_JSON_FOUND")
        print("FINAL: FAIL")
        return 2

    print("file_results:")
    global_numeric_stats = NumericStats()
    for result in results:
        global_numeric_stats.merge(result.numeric_stats)
        print_result(result, args.max_diffs)

    if global_numeric_stats.count:
        print(
            "numeric_max_abs_diff: "
            f"{global_numeric_stats.max_abs_diff:.12g}"
        )
    else:
        print("numeric_max_abs_diff: n/a")

    passed = (
        not missing
        and not extra
        and all(result.same for result in comparable_results)
        and len(comparable_results) == len(results)
    )
    print(f"FINAL: {'PASS' if passed else 'FAIL'}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
