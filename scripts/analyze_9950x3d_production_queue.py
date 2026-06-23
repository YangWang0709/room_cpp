#!/usr/bin/env python3
"""Summarize 9950X3D production scene queue runs."""

from __future__ import annotations

import argparse
import csv
import re
import statistics
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Iterable


FIELDNAMES = [
    "seed",
    "worker_id",
    "cpu_set",
    "generate_status",
    "generate_exit_code",
    "generate_wall_time",
    "generate_max_rss",
    "generate_user_time",
    "generate_system_time",
    "scene_blend_exists",
    "export_status",
    "export_exit_code",
    "export_wall_time",
    "export_max_rss",
    "export_user_time",
    "export_system_time",
    "usd_exists",
    "fatal_marker",
    "fatal_marker_detail",
    "blender_shutdown_leak_warning",
    "last_progress_line",
    "started_at",
    "ended_at",
    "output_folder",
    "usd_folder",
]

FATAL_RE = re.compile(
    r"Traceback|Segmentation fault|Fatal Python error|\bkilled\b|\bOOM\b|"
    r"out of memory|CUDA error|uncaught Exception|\bException\b",
    re.IGNORECASE,
)
LEAK_WARNING_RE = re.compile(r"Not freed memory blocks", re.IGNORECASE)
PROGRESS_RE = re.compile(
    r"progress|solve|populate|export|MAIN TOTAL|elapsed|task|coarse",
    re.IGNORECASE,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_root", type=Path)
    parser.add_argument(
        "--write-summaries",
        action="store_true",
        help="write summary.csv and summary.md under output_root",
    )
    return parser.parse_args()


def parse_kv_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(errors="replace").splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def parse_elapsed(value: str) -> float | None:
    value = value.strip()
    if not value:
        return None
    parts = value.split(":")
    try:
        if len(parts) == 3:
            hours = float(parts[0])
            minutes = float(parts[1])
            seconds = float(parts[2])
            return hours * 3600.0 + minutes * 60.0 + seconds
        if len(parts) == 2:
            minutes = float(parts[0])
            seconds = float(parts[1])
            return minutes * 60.0 + seconds
        return float(value)
    except ValueError:
        return None


def elapsed_value_from_time_line(line: str) -> str:
    if "):" in line:
        return line.split("):", 1)[1].strip()
    return line.split(":", 1)[-1].strip()


def parse_time_txt(path: Path) -> dict[str, str]:
    result = {
        "wall_time": "",
        "max_rss": "",
        "user_time": "",
        "system_time": "",
    }
    if not path.exists():
        return result
    for line in path.read_text(errors="replace").splitlines():
        if "Elapsed (wall clock) time" in line:
            elapsed = parse_elapsed(elapsed_value_from_time_line(line))
            if elapsed is not None:
                result["wall_time"] = f"{elapsed:.3f}"
        elif "Maximum resident set size (kbytes)" in line:
            result["max_rss"] = line.rsplit(":", 1)[-1].strip()
        elif line.startswith("\tUser time (seconds):"):
            result["user_time"] = line.rsplit(":", 1)[-1].strip()
        elif line.startswith("\tSystem time (seconds):"):
            result["system_time"] = line.rsplit(":", 1)[-1].strip()
    return result


def clean_cell(value: str, limit: int = 180) -> str:
    value = " ".join(value.strip().split())
    value = value.replace("|", "\\|")
    if len(value) > limit:
        return value[: limit - 3] + "..."
    return value


def scan_logs(log_paths: Iterable[Path]) -> tuple[str, str, str, str]:
    fatal_marker = "no"
    fatal_detail = ""
    leak_warning = "no"
    last_progress = ""
    for log_path in log_paths:
        if not log_path.exists():
            continue
        for line in log_path.read_text(errors="replace").splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if LEAK_WARNING_RE.search(stripped):
                leak_warning = "yes"
            if fatal_marker == "no" and FATAL_RE.search(stripped):
                fatal_marker = "yes"
                fatal_detail = clean_cell(stripped)
            lowered = stripped.lower()
            if lowered.startswith(("generate command:", "export command:")):
                continue
            if PROGRESS_RE.search(stripped):
                last_progress = clean_cell(stripped)
    return fatal_marker, fatal_detail, leak_warning, last_progress


def bool_text(value: bool) -> str:
    return "yes" if value else "no"


def parse_dt(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def parse_float(value: str) -> float | None:
    try:
        if value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_int(value: str) -> int | None:
    try:
        if value == "":
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def fmt_float(value: float | None, digits: int = 3) -> str:
    if value is None:
        return ""
    return f"{value:.{digits}f}"


def fmt_seconds(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.3f}s"


def has_usd_file(folder: Path) -> bool:
    if not folder.exists():
        return False
    for pattern in ("*.usd", "*.usdc", "*.usda"):
        if next(folder.rglob(pattern), None) is not None:
            return True
    return False


def collect_rows(root: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for status_path in sorted(root.glob("logs/seed_*/status.txt")):
        status = parse_kv_file(status_path)
        seed = status.get("seed") or status_path.parent.name.removeprefix("seed_")
        output_folder = Path(status.get("output_folder") or root / f"seed_{seed}" / "coarse")
        usd_folder = Path(status.get("usd_folder") or root / f"seed_{seed}" / "usd")
        generate_time = parse_time_txt(status_path.parent / "generate_time.txt")
        export_time = parse_time_txt(status_path.parent / "export_time.txt")
        fatal_marker, fatal_detail, leak_warning, last_progress = scan_logs(
            [status_path.parent / "generate.log", status_path.parent / "export.log"]
        )
        started_candidates = [
            status.get("generate_started_at", ""),
            status.get("export_started_at", ""),
        ]
        ended_candidates = [
            status.get("export_ended_at", ""),
            status.get("generate_ended_at", ""),
        ]
        started_at = next((value for value in started_candidates if value), "")
        ended_at = next((value for value in ended_candidates if value), "")
        rows.append(
            {
                "seed": seed,
                "worker_id": status.get("worker_id", ""),
                "cpu_set": status.get("cpu_set", ""),
                "generate_status": status.get("generate_status", ""),
                "generate_exit_code": status.get("generate_exit_code", ""),
                "generate_wall_time": generate_time["wall_time"],
                "generate_max_rss": generate_time["max_rss"],
                "generate_user_time": generate_time["user_time"],
                "generate_system_time": generate_time["system_time"],
                "scene_blend_exists": bool_text((output_folder / "scene.blend").exists()),
                "export_status": status.get("export_status", "not_requested"),
                "export_exit_code": status.get("export_exit_code", ""),
                "export_wall_time": export_time["wall_time"],
                "export_max_rss": export_time["max_rss"],
                "export_user_time": export_time["user_time"],
                "export_system_time": export_time["system_time"],
                "usd_exists": bool_text(has_usd_file(usd_folder)),
                "fatal_marker": fatal_marker,
                "fatal_marker_detail": fatal_detail,
                "blender_shutdown_leak_warning": leak_warning,
                "last_progress_line": last_progress,
                "started_at": started_at,
                "ended_at": ended_at,
                "output_folder": str(output_folder),
                "usd_folder": str(usd_folder),
            }
        )
    return rows


def markdown_table(headers: list[str], body: Iterable[list[object]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in body:
        lines.append("| " + " | ".join(clean_cell(str(value)) for value in row) + " |")
    return "\n".join(lines)


def total_elapsed(rows: list[dict[str, str]]) -> float | None:
    starts = [parse_dt(row.get("started_at", "")) for row in rows]
    ends = [parse_dt(row.get("ended_at", "")) for row in rows]
    starts = [value for value in starts if value is not None]
    ends = [value for value in ends if value is not None]
    if not starts or not ends:
        return None
    return max((max(ends) - min(starts)).total_seconds(), 0.0)


def avg(values: Iterable[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    if not present:
        return None
    return statistics.mean(present)


def row_wall(row: dict[str, str], phase: str) -> float | None:
    return parse_float(row.get(f"{phase}_wall_time", ""))


def row_max_rss(row: dict[str, str]) -> int:
    return max(
        parse_int(row.get("generate_max_rss", "")) or 0,
        parse_int(row.get("export_max_rss", "")) or 0,
    )


def recommendation(rows: list[dict[str, str]], elapsed: float | None) -> str:
    if not rows:
        return "No queue rows found. Run the production queue script first."
    generate_statuses = Counter(row.get("generate_status", "") for row in rows)
    export_statuses = Counter(row.get("export_status", "") for row in rows)
    fatal_count = sum(1 for row in rows if row.get("fatal_marker") == "yes")
    if fatal_count or generate_statuses.get("failed") or export_statuses.get("failed"):
        return "Inspect failed seeds and fatal markers before increasing the production batch."
    if generate_statuses.get("timeout") or export_statuses.get("timeout"):
        return "Timeouts occurred; inspect slow seeds before changing JOBS or CPU placement."
    if all(row.get("generate_status") == "skipped" for row in rows):
        return "Dry-run or resume-only sample; run a real batch to measure throughput."
    avg_generate = avg(row_wall(row, "generate") for row in rows)
    avg_export = avg(row_wall(row, "export") for row in rows)
    if avg_generate and avg_export and avg_export > avg_generate * 0.5:
        return "Export is a meaningful share of runtime; benchmark a separate export queue or EXPORT_JOBS next."
    if elapsed and export_statuses.get("complete"):
        return "Queue is clean; use the end-to-end USD scenes/hour for production sizing."
    return "Queue is clean for coarse generation; export remains a separate bottleneck check if enabled."


def render_markdown(root: Path, rows: list[dict[str, str]]) -> str:
    elapsed = total_elapsed(rows)
    generate_statuses = Counter(row.get("generate_status", "") for row in rows)
    export_statuses = Counter(row.get("export_status", "") for row in rows)
    generated = generate_statuses.get("complete", 0)
    exported = export_statuses.get("complete", 0)
    coarse_scenes_hour = None
    usd_scenes_hour = None
    if elapsed and elapsed > 0:
        coarse_scenes_hour = generated / (elapsed / 3600.0)
        usd_scenes_hour = exported / (elapsed / 3600.0)
    generate_walls = [row_wall(row, "generate") for row in rows]
    export_walls = [row_wall(row, "export") for row in rows]
    rss_top = sorted(rows, key=row_max_rss, reverse=True)[:5]
    failed_rows = [
        row
        for row in rows
        if row.get("generate_status") in {"failed", "timeout"}
        or row.get("export_status") in {"failed", "timeout"}
        or row.get("fatal_marker") == "yes"
    ]
    slowest = max(rows, key=lambda row: row_wall(row, "generate") or -1, default={})
    fastest = min(
        [row for row in rows if row_wall(row, "generate") is not None],
        key=lambda row: row_wall(row, "generate") or 0,
        default={},
    )

    lines = [
        "# 9950X3D Production Scene Queue Summary",
        "",
        f"- output root: `{root}`",
        f"- total seeds: `{len(rows)}`",
        f"- generated scene count: `{generated}`",
        f"- exported USD count: `{exported}`",
        f"- failed seeds: `{len(failed_rows)}`",
        f"- total elapsed wall time: `{fmt_seconds(elapsed)}`",
        f"- coarse scenes/hour: `{fmt_float(coarse_scenes_hour)}`",
        f"- end-to-end USD scenes/hour: `{fmt_float(usd_scenes_hour)}`",
        f"- avg generate wall: `{fmt_seconds(avg(generate_walls))}`",
        f"- avg export wall: `{fmt_seconds(avg(export_walls))}`",
        f"- max RSS: `{max((row_max_rss(row) for row in rows), default=0)} KB`",
        f"- slowest seed: `{slowest.get('seed', '')}`",
        f"- fastest seed: `{fastest.get('seed', '')}`",
        f"- recommended next action: {recommendation(rows, elapsed)}",
        "",
        "## Status Counts",
        "",
        markdown_table(
            ["phase", "complete", "failed", "timeout", "skipped", "not_requested"],
            [
                [
                    "generate",
                    generate_statuses.get("complete", 0),
                    generate_statuses.get("failed", 0),
                    generate_statuses.get("timeout", 0),
                    generate_statuses.get("skipped", 0),
                    generate_statuses.get("not_requested", 0),
                ],
                [
                    "export",
                    export_statuses.get("complete", 0),
                    export_statuses.get("failed", 0),
                    export_statuses.get("timeout", 0),
                    export_statuses.get("skipped", 0),
                    export_statuses.get("not_requested", 0),
                ],
            ],
        ),
        "",
        "## Rows",
        "",
        markdown_table(
            [
                "seed",
                "worker",
                "cpu_set",
                "generate",
                "gen_exit",
                "gen_wall_s",
                "gen_rss_kb",
                "scene",
                "export",
                "exp_exit",
                "exp_wall_s",
                "exp_rss_kb",
                "usd",
                "fatal",
                "leak_warn",
                "last_progress",
            ],
            [
                [
                    row.get("seed", ""),
                    row.get("worker_id", ""),
                    row.get("cpu_set", ""),
                    row.get("generate_status", ""),
                    row.get("generate_exit_code", ""),
                    row.get("generate_wall_time", ""),
                    row.get("generate_max_rss", ""),
                    row.get("scene_blend_exists", ""),
                    row.get("export_status", ""),
                    row.get("export_exit_code", ""),
                    row.get("export_wall_time", ""),
                    row.get("export_max_rss", ""),
                    row.get("usd_exists", ""),
                    row.get("fatal_marker", ""),
                    row.get("blender_shutdown_leak_warning", ""),
                    row.get("last_progress_line", ""),
                ]
                for row in rows
            ],
        ),
        "",
        "## Max RSS Top Seeds",
        "",
        markdown_table(
            ["seed", "worker", "max_rss_kb", "generate", "export"],
            [
                [
                    row.get("seed", ""),
                    row.get("worker_id", ""),
                    row_max_rss(row),
                    row.get("generate_status", ""),
                    row.get("export_status", ""),
                ]
                for row in rss_top
            ],
        ),
        "",
        "## Failed Seeds",
        "",
    ]
    if failed_rows:
        lines.append(
            markdown_table(
                ["seed", "worker", "generate", "export", "fatal_detail"],
                [
                    [
                        row.get("seed", ""),
                        row.get("worker_id", ""),
                        row.get("generate_status", ""),
                        row.get("export_status", ""),
                        row.get("fatal_marker_detail", ""),
                    ]
                    for row in failed_rows
                ],
            )
        )
    else:
        lines.append("None.")
    lines.extend(
        [
            "",
            "## Throughput Note",
            "",
            "Coarse throughput counts completed `scene.blend` generation. Final USD throughput counts completed USD/USDC exports.",
            "If export becomes the limiter, benchmark export queueing or `EXPORT_JOBS` separately from CPU placement.",
        ]
    )
    return "\n".join(lines) + "\n"


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in FIELDNAMES})


def main() -> None:
    args = parse_args()
    rows = collect_rows(args.output_root)
    markdown = render_markdown(args.output_root, rows)
    if args.write_summaries:
        write_csv(args.output_root / "summary.csv", rows)
        (args.output_root / "summary.md").write_text(markdown)
    print(markdown)


if __name__ == "__main__":
    main()
