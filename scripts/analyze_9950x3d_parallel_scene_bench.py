#!/usr/bin/env python3
"""Summarize 9950X3D scene-level parallel indoor benchmark runs."""

from __future__ import annotations

import argparse
import csv
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Iterable


FIELDNAMES = [
    "case_name",
    "cpu_strategy",
    "jobs",
    "seed",
    "phase",
    "cpu_range",
    "started_at",
    "ended_at",
    "exit_code",
    "status",
    "wall_time",
    "max_rss",
    "user_time",
    "system_time",
    "scene_blend_exists",
    "usdc_exists",
    "fatal_marker",
    "fatal_marker_detail",
    "last_progress_line",
    "progress_score",
]

FATAL_RE = re.compile(
    r"Traceback|Segmentation fault|\bkilled\b|\bOOM\b|out of memory|CUDA error|Error:|Exception",
    re.IGNORECASE,
)
PROGRESS_RE = re.compile(
    r"progress|solve|populate|export|MAIN TOTAL|elapsed|task",
    re.IGNORECASE,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_root", type=Path)
    parser.add_argument(
        "--write-summaries",
        action="store_true",
        help="write per-case and global summary CSV/markdown files",
    )
    parser.add_argument(
        "--case",
        dest="case_name",
        help="only include one case name",
    )
    return parser.parse_args()


def parse_env(path: Path) -> dict[str, str]:
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


def parse_time_txt(path: Path | None) -> dict[str, str]:
    result = {
        "wall_time": "",
        "max_rss": "",
        "user_time": "",
        "system_time": "",
    }
    if path is None or not path.exists():
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


def resolve_path(value: str, fallback: Path | None = None) -> Path | None:
    if value:
        return Path(value)
    return fallback


def first_fatal_marker(log_path: Path | None) -> tuple[str, str]:
    if log_path is None or not log_path.exists():
        return "no", ""
    for line in log_path.read_text(errors="replace").splitlines():
        if is_echoed_command_line(line):
            continue
        match = FATAL_RE.search(line)
        if match:
            return "yes", clean_cell(line)
    return "no", ""


def clean_cell(value: str, limit: int = 180) -> str:
    value = " ".join(value.strip().split())
    value = value.replace("|", "\\|")
    if len(value) > limit:
        return value[: limit - 3] + "..."
    return value


def is_echoed_command_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    mentions_bench_command = (
        "infinigen_examples.generate_indoors" in stripped
        or "infinigen.tools.export" in stripped
    )
    return mentions_bench_command and stripped.startswith(("env ", "taskset ", "numactl "))


def progress_details(log_path: Path | None) -> tuple[str, int]:
    if log_path is None or not log_path.exists():
        return "", 0
    last = ""
    count = 0
    stage_score = 0
    for line in log_path.read_text(errors="replace").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        lowered = stripped.lower()
        if lowered.startswith(("generate command:", "export command:", "command=")):
            continue
        if is_echoed_command_line(stripped):
            continue
        if not PROGRESS_RE.search(stripped):
            continue
        last = clean_cell(stripped)
        count += 1
        if "main total" in lowered:
            stage_score = max(stage_score, 100_000)
        elif "populate" in lowered:
            stage_score = max(stage_score, 50_000)
        elif "solve" in lowered:
            stage_score = max(stage_score, 20_000)
        elif "export" in lowered:
            stage_score = max(stage_score, 10_000)
        percent_match = re.search(r"(\d+(?:\.\d+)?)\s*%", stripped)
        if percent_match:
            try:
                stage_score += int(float(percent_match.group(1)))
            except ValueError:
                pass
    return last, stage_score + count


def bool_text(value: bool) -> str:
    return "yes" if value else "no"


def collect_rows_from_results(root: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    result_files = sorted(root.glob("cases/*/logs/seed_*/result_*.env"))
    for result_file in result_files:
        env = parse_env(result_file)
        phase = env.get("phase") or (
            "export" if "export" in result_file.name else "generate"
        )
        seed_log_dir = result_file.parent
        case_dir = result_file.parents[2]
        case_name = env.get("case_name", case_dir.name)
        seed = env.get("seed", seed_log_dir.name.removeprefix("seed_"))
        if phase == "export":
            default_log = seed_log_dir / "export_run.log"
            default_time = seed_log_dir / "export_time.txt"
        else:
            default_log = seed_log_dir / "run.log"
            default_time = seed_log_dir / "time.txt"

        log_path = resolve_path(env.get("run_log", ""), default_log)
        if env.get("status") == "skipped" and not env.get("time_txt"):
            time_path = None
        else:
            time_path = resolve_path(env.get("time_txt", ""), default_time)
        time_values = parse_time_txt(time_path)
        fatal_marker, fatal_detail = first_fatal_marker(log_path)
        last_progress, progress_score = progress_details(log_path)

        scene_blend = case_dir / f"seed_{seed}" / "coarse" / "scene.blend"
        usdc_root = case_dir / "usd" / f"seed_{seed}"
        usdc_exists = usdc_root.exists() and any(usdc_root.rglob("*.usdc"))

        row = {
            "case_name": case_name,
            "cpu_strategy": env.get("cpu_strategy", ""),
            "jobs": env.get("jobs", ""),
            "seed": seed,
            "phase": phase,
            "cpu_range": env.get("cpu_range", ""),
            "started_at": env.get("started_at", ""),
            "ended_at": env.get("ended_at", ""),
            "exit_code": env.get("exit_code", ""),
            "status": env.get("status", ""),
            "wall_time": time_values["wall_time"],
            "max_rss": time_values["max_rss"],
            "user_time": time_values["user_time"],
            "system_time": time_values["system_time"],
            "scene_blend_exists": bool_text(scene_blend.exists()),
            "usdc_exists": bool_text(usdc_exists),
            "fatal_marker": fatal_marker,
            "fatal_marker_detail": fatal_detail,
            "last_progress_line": last_progress,
            "progress_score": str(progress_score),
        }
        rows.append(row)
    return rows


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def load_rows(root: Path) -> list[dict[str, str]]:
    rows = collect_rows_from_results(root)
    if rows:
        return rows
    summary_all = root / "summary_all_cases.csv"
    if summary_all.exists():
        return read_csv(summary_all)
    rows = []
    for summary in sorted(root.glob("cases/*/summary.csv")):
        rows.extend(read_csv(summary))
    return rows


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


def parse_dt(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def fmt_float(value: float | None, digits: int = 3) -> str:
    if value is None:
        return ""
    return f"{value:.{digits}f}"


def aggregate_cases(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    by_case: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        by_case[row.get("case_name", "")].append(row)

    aggregates: list[dict[str, object]] = []
    for case_name, case_rows in sorted(by_case.items()):
        generate_rows = [row for row in case_rows if row.get("phase") == "generate"]
        if not generate_rows:
            generate_rows = case_rows
        statuses = Counter(row.get("status", "") for row in generate_rows)
        starts = [parse_dt(row.get("started_at", "")) for row in case_rows]
        ends = [parse_dt(row.get("ended_at", "")) for row in case_rows]
        starts = [value for value in starts if value is not None]
        ends = [value for value in ends if value is not None]
        elapsed = None
        if starts and ends:
            elapsed = max((max(ends) - min(starts)).total_seconds(), 0.0)

        wall_values = [
            value
            for value in (parse_float(row.get("wall_time", "")) for row in generate_rows)
            if value is not None
        ]
        rss_values = [
            value
            for value in (parse_int(row.get("max_rss", "")) for row in case_rows)
            if value is not None
        ]
        complete = statuses.get("complete", 0)
        scenes_hour = 0.0
        if elapsed and elapsed > 0:
            scenes_hour = complete / (elapsed / 3600.0)
        progress_score = sum(
            parse_int(row.get("progress_score", "")) or 0 for row in generate_rows
        )
        best_progress_row = max(
            generate_rows,
            key=lambda row: parse_int(row.get("progress_score", "")) or 0,
            default={},
        )
        first = generate_rows[0] if generate_rows else case_rows[0]
        aggregates.append(
            {
                "case_name": case_name,
                "cpu_strategy": first.get("cpu_strategy", ""),
                "jobs": parse_int(first.get("jobs", "")) or 0,
                "complete": complete,
                "failed": statuses.get("failed", 0),
                "timeout": statuses.get("timeout", 0),
                "skipped": statuses.get("skipped", 0),
                "scenes_hour": scenes_hour,
                "elapsed": elapsed,
                "avg_wall": statistics.mean(wall_values) if wall_values else None,
                "max_rss": max(rss_values) if rss_values else None,
                "fatal_count": sum(1 for row in case_rows if row.get("fatal_marker") == "yes"),
                "progress_score": progress_score,
                "best_progress": best_progress_row.get("last_progress_line", ""),
            }
        )
    return aggregates


def markdown_table(headers: list[str], body: Iterable[list[object]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in body:
        lines.append("| " + " | ".join(clean_cell(str(value)) for value in row) + " |")
    return "\n".join(lines)


def case_recommendation(rows: list[dict[str, str]]) -> str:
    generate_rows = [row for row in rows if row.get("phase") == "generate"]
    statuses = Counter(row.get("status", "") for row in generate_rows)
    fatal = any(row.get("fatal_marker") == "yes" for row in rows)
    if statuses.get("failed", 0) or fatal:
        return "Not recommended until failures or fatal markers are understood."
    if statuses.get("complete", 0) and not statuses.get("timeout", 0):
        return "Stable candidate for comparison; rank by scenes/hour globally."
    if statuses.get("timeout", 0):
        return "Useful bounded sample; compare last progress globally or extend timeout."
    if statuses.get("skipped", 0) == len(generate_rows):
        return "Dry-run or resume-only sample; no performance recommendation."
    return "Inconclusive."


def overall_recommendation(aggregates: list[dict[str, object]]) -> list[str]:
    if not aggregates:
        return ["No benchmark rows found."]

    real_samples = [
        item
        for item in aggregates
        if item["complete"] or item["failed"] or item["timeout"]
    ]
    if not real_samples:
        return ["Dry-run only. Run the 1800s matrix before selecting a CPU policy."]

    clean_completed = [
        item
        for item in real_samples
        if item["complete"] and not item["failed"] and not item["fatal_count"]
    ]
    if clean_completed:
        best = max(
            clean_completed,
            key=lambda item: (
                float(item["scenes_hour"]),
                -int(item["timeout"]),
                -(int(item["max_rss"] or 0)),
            ),
        )
        basis = "highest clean scenes/hour"
    else:
        best = max(real_samples, key=lambda item: int(item["progress_score"]))
        basis = "furthest bounded-time progress; extend TIMEOUT_SECONDS"

    tested_jobs = {int(item["jobs"]) for item in aggregates if int(item["jobs"])}
    best_jobs = int(best["jobs"])
    best_strategy = str(best["cpu_strategy"])

    by_pair = {
        (int(item["jobs"]), str(item["cpu_strategy"])): item for item in aggregates
    }
    avoid_smt = "inconclusive"
    for jobs in sorted(tested_jobs):
        physical = by_pair.get((jobs, "physical_cores_only"))
        split = by_pair.get((jobs, "split_llc"))
        if not physical or not split:
            continue
        physical_score = (
            float(physical["scenes_hour"]),
            int(physical["progress_score"]),
            -int(physical["fatal_count"]),
        )
        split_score = (
            float(split["scenes_hour"]),
            int(split["progress_score"]),
            -int(split["fatal_count"]),
        )
        if physical_score > split_score:
            avoid_smt = "yes, physical_cores_only is ahead for at least one JOBS value"
            break
        if split_score > physical_score:
            avoid_smt = "no clear need; split_llc is competitive"

    if 3 not in tested_jobs and best_jobs in {2, 4}:
        try_jobs3 = "yes, JOBS=3 is the next useful interpolation point"
    else:
        try_jobs3 = "not yet"
    if 4 not in tested_jobs and best_jobs <= 3:
        try_jobs4 = "yes after JOBS=2/3 has zero failures"
    elif 4 in tested_jobs:
        try_jobs4 = "already covered by this matrix"
    else:
        try_jobs4 = "not before stabilizing lower JOBS"

    extend_timeout = (
        "yes" if not any(item["complete"] for item in real_samples) else "optional"
    )

    return [
        f"Recommended case: `{best['case_name']}` based on {basis}.",
        f"Best CPU_STRATEGY: `{best_strategy}`.",
        f"Best JOBS: `{best_jobs}`.",
        f"Try JOBS=3: {try_jobs3}.",
        f"Try JOBS=4: {try_jobs4}.",
        f"Avoid SMT: {avoid_smt}.",
        "Keep EXPORT_JOBS=1 unless export becomes the measured bottleneck.",
        f"Extend TIMEOUT_SECONDS: {extend_timeout}.",
    ]


def render_case_markdown(case_name: str, rows: list[dict[str, str]]) -> str:
    aggregates = aggregate_cases(rows)
    aggregate = aggregates[0] if aggregates else {}
    generate_rows = [row for row in rows if row.get("phase") == "generate"]
    statuses = Counter(row.get("status", "") for row in generate_rows)
    rss_top = sorted(
        rows,
        key=lambda row: parse_int(row.get("max_rss", "")) or -1,
        reverse=True,
    )[:5]
    suspected_swap_oom = any(
        row.get("fatal_marker") == "yes"
        and re.search(r"oom|killed", row.get("fatal_marker_detail", ""), re.I)
        for row in rows
    )

    lines = [
        f"# {case_name}",
        "",
        f"- complete scenes: `{statuses.get('complete', 0)}`",
        f"- failed scenes: `{statuses.get('failed', 0)}`",
        f"- timeout scenes: `{statuses.get('timeout', 0)}`",
        f"- skipped scenes: `{statuses.get('skipped', 0)}`",
        f"- total elapsed wall time for case: `{fmt_float(aggregate.get('elapsed'))}s`",
        f"- scenes/hour: `{fmt_float(aggregate.get('scenes_hour'))}`",
        f"- suspected swap/OOM: `{bool_text(suspected_swap_oom)}`",
        f"- recommendation: {case_recommendation(rows)}",
        "",
        "## Rows",
        "",
        markdown_table(
            [
                "seed",
                "phase",
                "cpu_range",
                "status",
                "exit",
                "wall_s",
                "max_rss_kb",
                "fatal",
                "last_progress",
            ],
            [
                [
                    row.get("seed", ""),
                    row.get("phase", ""),
                    row.get("cpu_range", "") or "none",
                    row.get("status", ""),
                    row.get("exit_code", ""),
                    row.get("wall_time", ""),
                    row.get("max_rss", ""),
                    row.get("fatal_marker", ""),
                    row.get("last_progress_line", ""),
                ]
                for row in rows
            ],
        ),
        "",
        "## Max RSS Top",
        "",
        markdown_table(
            ["seed", "phase", "max_rss_kb", "status"],
            [
                [
                    row.get("seed", ""),
                    row.get("phase", ""),
                    row.get("max_rss", ""),
                    row.get("status", ""),
                ]
                for row in rss_top
            ],
        ),
    ]
    return "\n".join(lines) + "\n"


def render_global_markdown(rows: list[dict[str, str]]) -> str:
    aggregates = aggregate_cases(rows)
    lines = [
        "# 9950X3D Parallel Scene Benchmark Summary",
        "",
        markdown_table(
            [
                "case",
                "strategy",
                "jobs",
                "complete",
                "failed",
                "timeout",
                "skipped",
                "scenes/hour",
                "avg_wall_s",
                "max_rss_kb",
                "fatal",
                "progress_score",
            ],
            [
                [
                    item["case_name"],
                    item["cpu_strategy"],
                    item["jobs"],
                    item["complete"],
                    item["failed"],
                    item["timeout"],
                    item["skipped"],
                    fmt_float(item["scenes_hour"]),
                    fmt_float(item["avg_wall"]),
                    item["max_rss"] or "",
                    item["fatal_count"],
                    item["progress_score"],
                ]
                for item in aggregates
            ],
        ),
        "",
        "## Recommendation",
        "",
    ]
    lines.extend(f"- {line}" for line in overall_recommendation(aggregates))

    if (
        aggregates
        and any(item["timeout"] for item in aggregates)
        and not any(item["complete"] for item in aggregates)
    ):
        lines.extend(["", "## Timeout Progress Clues", ""])
        lines.append(
            markdown_table(
                ["case", "progress_score", "best_last_progress"],
                [
                    [
                        item["case_name"],
                        item["progress_score"],
                        item["best_progress"],
                    ]
                    for item in sorted(
                        aggregates,
                        key=lambda item: int(item["progress_score"]),
                        reverse=True,
                    )
                ],
            )
        )
    return "\n".join(lines) + "\n"


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in FIELDNAMES})


def write_summaries(root: Path, rows: list[dict[str, str]]) -> None:
    by_case: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        by_case[row.get("case_name", "")].append(row)

    for case_name, case_rows in sorted(by_case.items()):
        case_dir = root / "cases" / case_name
        write_csv(case_dir / "summary.csv", case_rows)
        (case_dir / "summary.md").write_text(render_case_markdown(case_name, case_rows))

    write_csv(root / "summary_all_cases.csv", rows)
    (root / "summary_all_cases.md").write_text(render_global_markdown(rows))


def main() -> None:
    args = parse_args()
    rows = load_rows(args.output_root)
    if args.case_name:
        rows = [row for row in rows if row.get("case_name") == args.case_name]

    if args.write_summaries:
        write_summaries(args.output_root, rows)

    print(render_global_markdown(rows))


if __name__ == "__main__":
    main()
