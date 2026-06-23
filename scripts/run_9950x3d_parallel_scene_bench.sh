#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

SEEDS="${SEEDS:-10,11,12,13}"
JOBS="${JOBS:-2}"
BENCH_MODE="${BENCH_MODE:-single}"
CPU_STRATEGY="${CPU_STRATEGY:-split_llc}"
CPU_SETS="${CPU_SETS:-}"
OUTPUT_ROOT="${OUTPUT_ROOT:-outputs/bench_9950x3d_parallel_scenes}"
PYTHON_BIN="${PYTHON_BIN:-${PYTHON:-python}}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-1800}"
FULL_TIMEOUT_SECONDS="${FULL_TIMEOUT_SECONDS:-14400}"
CLEAN="${CLEAN:-0}"
RESUME="${RESUME:-1}"
EXPORT_USD="${EXPORT_USD:-0}"
EXPORT_JOBS="${EXPORT_JOBS:-1}"
EXPORT_RESOLUTION="${EXPORT_RESOLUTION:-512}"
ENABLE_WHEAT_REUSE="${ENABLE_WHEAT_REUSE:-0}"
DRY_RUN="${DRY_RUN:-0}"
ALLOW_JOBS8="${ALLOW_JOBS8:-0}"
USE_NUMACTL="${USE_NUMACTL:-0}"

TOPOLOGY_DIR="${OUTPUT_ROOT}/topology"
TOPOLOGY_TXT="${TOPOLOGY_DIR}/cpu_topology.txt"
TOPOLOGY_JSON="${TOPOLOGY_DIR}/cpu_topology.json"
RECOMMENDED_CPU_SETS="${TOPOLOGY_DIR}/recommended_cpu_sets.md"
LOCK_KEY="${OUTPUT_ROOT//\//_}"
LOCK_KEY="${LOCK_KEY// /_}"
RUN_LOCK_DIR="${TMPDIR:-/tmp}/infinigen_9950x3d_bench_${LOCK_KEY}.lock"
LOCK_HELD=0

PROFILE_ENV_VARS=(
  INFINIGEN_PROFILE_TIMING
  INFINIGEN_PROFILE_GC
  INFINIGEN_PROFILE_ASSET_FACTORY
  INFINIGEN_PROFILE_BBOX
  INFINIGEN_PROFILE_SHELF_NODEGROUPS
  INFINIGEN_PROFILE_NATURE_SHELF_TRINKETS
  INFINIGEN_PROFILE_DATABLOCK_GROWTH
  INFINIGEN_PROFILE_PLANT_ASSETS
  INFINIGEN_PROFILE_BOOKSTACK
  INFINIGEN_REUSE_PLANT_TEMPLATE_GEOMETRY
)

SEED_LIST=()

quote_command() {
  printf "%q " "$@"
  printf "\n"
}

timestamp() {
  date -Iseconds
}

parse_seeds() {
  local raw="${SEEDS//,/ }"
  read -r -a SEED_LIST <<< "$raw"
  if (( ${#SEED_LIST[@]} == 0 )); then
    echo "No seeds provided. Set SEEDS=10,11,12,13 or similar." >&2
    exit 2
  fi
}

require_tools() {
  if [[ ! -x /usr/bin/time ]]; then
    echo "Missing required /usr/bin/time for -v timing output." >&2
    exit 2
  fi
  if ! command -v timeout >/dev/null 2>&1; then
    echo "Missing required timeout command." >&2
    exit 2
  fi
  if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    echo "PYTHON_BIN is not executable: ${PYTHON_BIN}" >&2
    exit 2
  fi
  if [[ "$USE_NUMACTL" == "1" ]]; then
    if ! command -v numactl >/dev/null 2>&1; then
      echo "USE_NUMACTL=1 was requested, but numactl is not installed." >&2
      exit 2
    fi
  elif ! command -v taskset >/dev/null 2>&1; then
    echo "Missing required taskset command for CPU binding." >&2
    exit 2
  fi
}

cleanup_lock() {
  if [[ "${LOCK_HELD:-0}" == "1" ]]; then
    rm -rf "$RUN_LOCK_DIR"
  fi
}

acquire_output_root_lock() {
  local lock_parent
  lock_parent="$(dirname "$RUN_LOCK_DIR")"
  mkdir -p "$lock_parent"

  if mkdir "$RUN_LOCK_DIR" 2>/dev/null; then
    LOCK_HELD=1
    echo "$$" > "${RUN_LOCK_DIR}/pid"
    echo "$(timestamp)" > "${RUN_LOCK_DIR}/started_at"
    echo "$OUTPUT_ROOT" > "${RUN_LOCK_DIR}/output_root"
    trap cleanup_lock EXIT
    return
  fi

  local lock_pid
  lock_pid="$(cat "${RUN_LOCK_DIR}/pid" 2>/dev/null || true)"
  if [[ -n "$lock_pid" ]] && kill -0 "$lock_pid" 2>/dev/null; then
    echo "Benchmark output root is already locked: ${OUTPUT_ROOT}" >&2
    echo "Lock: ${RUN_LOCK_DIR} (pid ${lock_pid})" >&2
    echo "Use a different OUTPUT_ROOT or wait for the active run to finish." >&2
    exit 2
  fi

  echo "Removing stale benchmark lock: ${RUN_LOCK_DIR}" >&2
  rm -rf "$RUN_LOCK_DIR"
  if ! mkdir "$RUN_LOCK_DIR" 2>/dev/null; then
    echo "Failed to acquire benchmark output root lock: ${RUN_LOCK_DIR}" >&2
    exit 2
  fi
  LOCK_HELD=1
  echo "$$" > "${RUN_LOCK_DIR}/pid"
  echo "$(timestamp)" > "${RUN_LOCK_DIR}/started_at"
  echo "$OUTPUT_ROOT" > "${RUN_LOCK_DIR}/output_root"
  trap cleanup_lock EXIT
}

active_output_root_users() {
  ps -eo pid=,ppid=,cmd= \
    | awk -v self="$$" -v root="$OUTPUT_ROOT" '
        $1 != self && $2 != self && $3 != "awk" && index($0, root) { print }
      ' || true
}

ensure_no_active_output_root_users() {
  local active
  active="$(active_output_root_users)"
  if [[ -n "$active" ]]; then
    echo "Refusing to use OUTPUT_ROOT while active processes reference it: ${OUTPUT_ROOT}" >&2
    echo "$active" >&2
    echo "Wait for the active benchmark/generation processes to finish or choose another OUTPUT_ROOT." >&2
    exit 2
  fi
}

safe_clean_output_root() {
  if [[ "$CLEAN" != "1" ]]; then
    return
  fi

  case "$OUTPUT_ROOT" in
    outputs/bench_9950x3d_compare_snapshots|outputs/bench_9950x3d_compare_snapshots/*)
      echo "Refusing CLEAN=1 for comparison snapshot path: ${OUTPUT_ROOT}" >&2
      exit 2
      ;;
    outputs/bench_9950x3d_*)
      echo "Removing existing benchmark output: ${OUTPUT_ROOT}"
      rm -rf "$OUTPUT_ROOT"
      ;;
    *)
      echo "Refusing CLEAN=1 for unexpected OUTPUT_ROOT: ${OUTPUT_ROOT}" >&2
      echo "Use an outputs/bench_9950x3d_* path outside outputs/bench_9950x3d_compare_snapshots." >&2
      exit 2
      ;;
  esac
}

validate_jobs() {
  local jobs="$1"
  if ! [[ "$jobs" =~ ^[0-9]+$ ]] || (( jobs < 1 )); then
    echo "Invalid JOBS value: ${jobs}" >&2
    exit 2
  fi
  if (( jobs >= 8 )) && [[ "$ALLOW_JOBS8" != "1" ]]; then
    echo "JOBS=${jobs} requires ALLOW_JOBS8=1. Start with JOBS=2/3/4." >&2
    exit 2
  fi
}

collect_topology_text() {
  mkdir -p "$TOPOLOGY_DIR"
  {
    echo "== uname -a =="
    uname -a || true
    echo
    echo "== nproc =="
    nproc || true
    echo
    echo "== lscpu =="
    lscpu || true
    echo
    echo "== lscpu -e=CPU,CORE,SOCKET,NODE,CACHE =="
    lscpu -e=CPU,CORE,SOCKET,NODE,CACHE || true
    echo
    echo "== lscpu -C =="
    lscpu -C || true
    echo
    echo "== numactl --hardware =="
    numactl --hardware || true
    echo
    echo "== CPU governor =="
    cat /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor 2>/dev/null \
      | sort | uniq -c || true
    echo
    echo "== free -h =="
    free -h || true
    echo
    echo "== swapon --show =="
    swapon --show || true
    echo
    echo "== df -h . =="
    df -h . || true
    echo
    echo "== lsblk =="
    lsblk -o NAME,MODEL,ROTA,SIZE,MOUNTPOINT || true
    echo
    echo "== git rev-parse --short HEAD =="
    git rev-parse --short HEAD || true
    echo
    echo "== git status --short =="
    git status --short || true
    echo
    echo "== which python =="
    which python || true
    echo
    echo "== python -V =="
    python -V || true
    echo
    echo "== PYTHON_BIN =="
    command -v "$PYTHON_BIN" || true
    "$PYTHON_BIN" -V || true
  } > "$TOPOLOGY_TXT" 2>&1
}

write_topology_json_and_md() {
  "$PYTHON_BIN" - "$TOPOLOGY_JSON" "$RECOMMENDED_CPU_SETS" <<'PY'
from __future__ import annotations

import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path


json_path = Path(sys.argv[1])
md_path = Path(sys.argv[2])


def run_text(args: list[str]) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(args, text=True, capture_output=True, check=False)
    except FileNotFoundError as exc:
        return 127, "", str(exc)
    return proc.returncode, proc.stdout, proc.stderr


def parse_int(value: str):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def compact_range(cpus: list[int]) -> str:
    cpus = sorted(set(cpus))
    if not cpus:
        return ""
    ranges = []
    start = prev = cpus[0]
    for cpu in cpus[1:]:
        if cpu == prev + 1:
            prev = cpu
            continue
        ranges.append(f"{start}-{prev}" if start != prev else str(start))
        start = prev = cpu
    ranges.append(f"{start}-{prev}" if start != prev else str(start))
    return ",".join(ranges)


def parse_lscpu_e() -> tuple[list[dict], str | None]:
    code, stdout, stderr = run_text(["lscpu", "-e=CPU,CORE,SOCKET,NODE,CACHE"])
    if code != 0:
        return [], f"lscpu -e failed: {stderr.strip() or code}"
    rows = []
    header = None
    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            header = line.lstrip("#").split()
            continue
        if header is None:
            header = line.split()
            continue
        parts = line.split()
        if len(parts) < len(header):
            continue
        row = dict(zip(header, parts))
        cpu = parse_int(row.get("CPU"))
        if cpu is None:
            continue
        cache = row.get("CACHE") or ""
        cache_parts = [part for part in cache.split(":") if part not in {"", "-"}]
        last_cache = cache_parts[-1] if cache_parts else None
        rows.append(
            {
                "cpu": cpu,
                "core": parse_int(row.get("CORE")),
                "socket": parse_int(row.get("SOCKET")),
                "node": parse_int(row.get("NODE")),
                "cache": cache,
                "last_level_cache": last_cache,
            }
        )
    if not rows:
        return [], "no parseable lscpu -e rows"
    return rows, None


def split_fallback(cpus: list[int]) -> list[list[int]]:
    midpoint = max(1, len(cpus) // 2)
    if len(cpus) <= 1:
        return [cpus]
    return [cpus[:midpoint], cpus[midpoint:]]


rows, parse_error = parse_lscpu_e()
all_cpus = sorted(row["cpu"] for row in rows)
fallback_used = False
fallback_reason = ""

cache_groups: dict[str, list[dict]] = defaultdict(list)
for row in rows:
    if row["last_level_cache"] is not None:
        key = f"llc_{row['last_level_cache']}"
        cache_groups[key].append(row)

if not cache_groups:
    fallback_used = True
    fallback_reason = parse_error or "lscpu CACHE column did not expose LLC ids"
    raw_groups = {
        f"fallback_{idx}": [{"cpu": cpu} for cpu in cpus]
        for idx, cpus in enumerate(split_fallback(all_cpus))
        if cpus
    }
else:
    raw_groups = dict(sorted(cache_groups.items(), key=lambda item: min(r["cpu"] for r in item[1])))

core_to_cpus: dict[tuple[int | None, int | None], list[int]] = defaultdict(list)
for row in rows:
    core_to_cpus[(row.get("socket"), row.get("core"))].append(row["cpu"])
physical_core_cpus = [min(cpus) for _, cpus in sorted(core_to_cpus.items(), key=lambda item: min(item[1]))]

llc_groups = []
fallback_physical_groups = split_fallback(physical_core_cpus) if fallback_used else []
for group_idx, (name, group_rows) in enumerate(raw_groups.items()):
    group_cpus = sorted({row["cpu"] for row in group_rows})
    if fallback_used and group_idx < len(fallback_physical_groups):
        group_physical = fallback_physical_groups[group_idx]
    else:
        group_core_to_cpus: dict[tuple[int | None, int | None], list[int]] = defaultdict(list)
        row_by_cpu = {row["cpu"]: row for row in rows}
        for cpu in group_cpus:
            row = row_by_cpu.get(cpu, {"socket": None, "core": cpu})
            group_core_to_cpus[(row.get("socket"), row.get("core"))].append(cpu)
        group_physical = [
            min(cpus)
            for _, cpus in sorted(group_core_to_cpus.items(), key=lambda item: min(item[1]))
        ]
    llc_groups.append(
        {
            "name": name,
            "cpus": group_cpus,
            "cpu_range": compact_range(group_cpus),
            "physical_core_cpus": group_physical,
            "physical_core_cpu_range": compact_range(group_physical),
            "logical_cpu_count": len(group_cpus),
            "physical_core_count": len(group_physical),
        }
    )

data = {
    "cpu_count": len(all_cpus),
    "all_cpus": all_cpus,
    "all_cpu_range": compact_range(all_cpus),
    "physical_core_cpus": physical_core_cpus,
    "physical_core_cpu_range": compact_range(physical_core_cpus),
    "lscpu_e_parse_error": parse_error,
    "fallback_used": fallback_used,
    "fallback_reason": fallback_reason,
    "llc_groups": llc_groups,
}
json_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")

lines = [
    "# Recommended CPU Sets",
    "",
    f"- logical CPUs: `{data['cpu_count']}`",
    f"- all CPUs: `{data['all_cpu_range']}`",
    f"- physical-core representatives: `{data['physical_core_cpu_range']}`",
    f"- fallback used: `{str(fallback_used).lower()}`",
]
if fallback_reason:
    lines.append(f"- fallback reason: {fallback_reason}")
lines.extend(["", "## LLC / CCD Candidate Groups", ""])
for group in llc_groups:
    lines.append(
        f"- `{group['name']}`: logical `{group['cpu_range']}` "
        f"({group['logical_cpu_count']} CPUs), physical-only "
        f"`{group['physical_core_cpu_range']}` "
        f"({group['physical_core_count']} cores)"
    )
lines.extend(
    [
        "",
        "## Strategy Notes",
        "",
        "- `CPU_STRATEGY=none`: no CPU binding.",
        "- `CPU_STRATEGY=compact_llc`: keep each job inside one LLC group when possible.",
        "- `CPU_STRATEGY=split_llc`: split jobs across LLC groups, then within each group.",
        "- `CPU_STRATEGY=physical_cores_only`: use one logical CPU per physical core.",
        "- `CPU_STRATEGY=smt_pairs`: use the full SMT logical CPU set.",
        "- `CPU_STRATEGY=manual`: use semicolon-separated `CPU_SETS`, such as `0-15;16-31`.",
        "",
        "The script does not assume that CPU `0-15` is a specific CCD. It uses the",
        "`lscpu -e` cache identifiers first and only falls back to continuous halves",
        "when cache grouping is unavailable.",
    ]
)
md_path.write_text("\n".join(lines) + "\n")
PY
}

resolve_cpu_sets() {
  local strategy="$1"
  local jobs="$2"
  "$PYTHON_BIN" - "$TOPOLOGY_JSON" "$strategy" "$jobs" "$CPU_SETS" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path


topology = json.loads(Path(sys.argv[1]).read_text())
strategy = sys.argv[2]
jobs = int(sys.argv[3])
manual_cpu_sets = [part.strip() for part in sys.argv[4].split(";") if part.strip()]


def compact_range(cpus: list[int]) -> str:
    cpus = sorted(set(cpus))
    if not cpus:
        return ""
    ranges = []
    start = prev = cpus[0]
    for cpu in cpus[1:]:
        if cpu == prev + 1:
            prev = cpu
            continue
        ranges.append(f"{start}-{prev}" if start != prev else str(start))
        start = prev = cpu
    ranges.append(f"{start}-{prev}" if start != prev else str(start))
    return ",".join(ranges)


def split_even(items: list[int], parts: int) -> list[list[int]]:
    if parts <= 0:
        return []
    chunks = []
    total = len(items)
    for idx in range(parts):
        start = (idx * total) // parts
        end = ((idx + 1) * total) // parts
        chunk = items[start:end]
        if chunk:
            chunks.append(chunk)
    return chunks


def jobs_per_group(group_count: int, jobs: int) -> list[int]:
    if group_count <= 0:
        return [jobs]
    counts = [jobs // group_count] * group_count
    for idx in range(jobs % group_count):
        counts[idx] += 1
    return counts


def split_across_groups(groups: list[list[int]], jobs: int) -> list[str]:
    groups = [sorted(group) for group in groups if group]
    if not groups:
        groups = [topology.get("all_cpus", [])]
    counts = jobs_per_group(len(groups), jobs)
    result: list[str] = []
    for group, count in zip(groups, counts):
        result.extend(compact_range(chunk) for chunk in split_even(group, count))
    while len(result) < jobs:
        result.append(result[-1] if result else topology.get("all_cpu_range", ""))
    return result[:jobs]


llc_groups = topology.get("llc_groups", [])
logical_groups = [group.get("cpus", []) for group in llc_groups]
physical_groups = [
    group.get("physical_core_cpus") or group.get("cpus", [])
    for group in llc_groups
]

if strategy == "manual":
    if not manual_cpu_sets:
        raise SystemExit("CPU_STRATEGY=manual requires CPU_SETS, e.g. CPU_SETS='0-15;16-31'")
    result = [manual_cpu_sets[idx % len(manual_cpu_sets)] for idx in range(jobs)]
elif strategy == "compact_llc":
    if jobs <= len(logical_groups):
        result = [compact_range(group) for group in logical_groups[:jobs]]
    else:
        result = split_across_groups(logical_groups, jobs)
elif strategy == "split_llc":
    result = split_across_groups(logical_groups, jobs)
elif strategy == "physical_cores_only":
    result = split_across_groups(physical_groups, jobs)
elif strategy == "smt_pairs":
    result = split_across_groups(logical_groups, jobs)
else:
    raise SystemExit(f"Unsupported CPU_STRATEGY={strategy}")

print(";".join(result))
PY
}

write_env_file() {
  local env_file="$1"
  local phase="$2"
  local case_name="$3"
  local seed="$4"
  local jobs="$5"
  local strategy="$6"
  local cpu_range="$7"
  shift 7
  local cmd=("$@")

  {
    echo "phase=${phase}"
    echo "case_name=${case_name}"
    echo "seed=${seed}"
    echo "jobs=${jobs}"
    echo "cpu_strategy=${strategy}"
    echo "cpu_range=${cpu_range}"
    echo "bench_mode=${BENCH_MODE}"
    echo "timeout_seconds=${TIMEOUT_SECONDS}"
    echo "full_timeout_seconds=${FULL_TIMEOUT_SECONDS}"
    echo "export_usd=${EXPORT_USD}"
    echo "export_jobs=${EXPORT_JOBS}"
    echo "export_resolution=${EXPORT_RESOLUTION}"
    echo "enable_wheat_reuse=${ENABLE_WHEAT_REUSE}"
    echo "use_numactl=${USE_NUMACTL}"
    echo "python_bin=${PYTHON_BIN}"
    echo "git_commit=$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
    echo "command=$(quote_command "${cmd[@]}")"
  } > "$env_file"
}

write_result_file() {
  local result_file="$1"
  local phase="$2"
  local case_name="$3"
  local seed="$4"
  local jobs="$5"
  local strategy="$6"
  local cpu_range="$7"
  local started_at="$8"
  local ended_at="$9"
  local exit_code="${10}"
  local status="${11}"
  local run_log="${12}"
  local time_txt="${13}"

  {
    echo "phase=${phase}"
    echo "case_name=${case_name}"
    echo "seed=${seed}"
    echo "jobs=${jobs}"
    echo "cpu_strategy=${strategy}"
    echo "cpu_range=${cpu_range}"
    echo "started_at=${started_at}"
    echo "ended_at=${ended_at}"
    echo "exit_code=${exit_code}"
    echo "status=${status}"
    echo "run_log=${run_log}"
    echo "time_txt=${time_txt}"
  } > "$result_file"
}

build_generate_cmd() {
  local cpu_range="$1"
  local output_folder="$2"
  CMD=()
  local bind_cmd=()
  local env_cmd=(env)
  local var

  for var in "${PROFILE_ENV_VARS[@]}"; do
    env_cmd+=(-u "$var")
  done
  env_cmd+=(
    INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1
    INFINIGEN_REUSE_LARGESHELF_CHILD_NODEGROUPS=1
    INFINIGEN_FAST_NATURE_TRINKET_STABLE_POSE=1
    OMP_NUM_THREADS=1
    OPENBLAS_NUM_THREADS=1
    MKL_NUM_THREADS=1
    NUMEXPR_NUM_THREADS=1
    BLIS_NUM_THREADS=1
  )
  if [[ "$ENABLE_WHEAT_REUSE" == "1" ]]; then
    env_cmd+=(INFINIGEN_REUSE_PLANT_TEMPLATE_GEOMETRY=1)
  fi

  if [[ -n "$cpu_range" ]]; then
    if [[ "$USE_NUMACTL" == "1" ]]; then
      bind_cmd=(numactl "--physcpubind=${cpu_range}")
    else
      bind_cmd=(taskset -c "$cpu_range")
    fi
  fi

  CMD=(
    "${bind_cmd[@]}"
    "${env_cmd[@]}"
    "$PYTHON_BIN"
    -m infinigen_examples.generate_indoors
    --seed "$CURRENT_SEED"
    --task coarse
    --output_folder "$output_folder"
    -g fast_solve.gin
    -p
    compose_indoors.terrain_enabled=False
    home_room_constraints.has_fewer_rooms=False
    restrict_solving.solve_max_rooms=10
    populate_doors.door_chance=0
  )
}

build_export_cmd() {
  local cpu_range="$1"
  local input_folder="$2"
  local output_folder="$3"
  CMD=()
  local bind_cmd=()
  local env_cmd=(env)
  local var

  for var in "${PROFILE_ENV_VARS[@]}"; do
    env_cmd+=(-u "$var")
  done
  env_cmd+=(
    OMP_NUM_THREADS=1
    OPENBLAS_NUM_THREADS=1
    MKL_NUM_THREADS=1
    NUMEXPR_NUM_THREADS=1
    BLIS_NUM_THREADS=1
  )

  if [[ -n "$cpu_range" ]]; then
    if [[ "$USE_NUMACTL" == "1" ]]; then
      bind_cmd=(numactl "--physcpubind=${cpu_range}")
    else
      bind_cmd=(taskset -c "$cpu_range")
    fi
  fi

  CMD=(
    "${bind_cmd[@]}"
    "${env_cmd[@]}"
    "$PYTHON_BIN"
    -m infinigen.tools.export
    --input_folder "$input_folder"
    --output_folder "$output_folder"
    -f usdc
    -r "$EXPORT_RESOLUTION"
    --omniverse
  )
}

run_generate_seed() {
  local case_name="$1"
  local case_dir="$2"
  local seed="$3"
  local jobs="$4"
  local strategy="$5"
  local cpu_range="$6"

  local seed_dir="${case_dir}/seed_${seed}"
  local output_folder="${seed_dir}/coarse"
  local log_dir="${case_dir}/logs/seed_${seed}"
  local run_log="${log_dir}/run.log"
  local time_txt="${log_dir}/time.txt"
  local env_txt="${log_dir}/env.txt"
  local result_file="${log_dir}/result_generate.env"
  mkdir -p "$seed_dir" "$output_folder" "$log_dir"

  local started_at ended_at exit_code status
  if [[ "$RESUME" == "1" && -f "${output_folder}/scene.blend" ]]; then
    started_at="$(timestamp)"
    ended_at="$started_at"
    status="skipped"
    write_result_file "$result_file" generate "$case_name" "$seed" "$jobs" \
      "$strategy" "$cpu_range" "$started_at" "$ended_at" 0 "$status" "" ""
    echo "RESUME=1: skipping existing ${output_folder}/scene.blend" > "$run_log"
    return 0
  fi

  CURRENT_SEED="$seed"
  build_generate_cmd "$cpu_range" "$output_folder"
  write_env_file "$env_txt" generate "$case_name" "$seed" "$jobs" \
    "$strategy" "$cpu_range" "${CMD[@]}"

  {
    echo "started_at=$(timestamp)"
    echo "generate command:"
    quote_command "${CMD[@]}"
    echo
  } > "$run_log"

  if [[ "$DRY_RUN" == "1" ]]; then
    started_at="$(timestamp)"
    ended_at="$started_at"
    echo "DRY_RUN=1: generation skipped." >> "$run_log"
    write_result_file "$result_file" generate "$case_name" "$seed" "$jobs" \
      "$strategy" "$cpu_range" "$started_at" "$ended_at" 0 skipped "$run_log" ""
    return 0
  fi

  started_at="$(timestamp)"
  set +e
  /usr/bin/time -v -o "$time_txt" \
    timeout "$TIMEOUT_SECONDS" "${CMD[@]}" >> "$run_log" 2>&1
  exit_code=$?
  set -e
  ended_at="$(timestamp)"

  if [[ "$exit_code" == "124" ]]; then
    status="timeout"
  elif [[ "$exit_code" == "0" && -f "${output_folder}/scene.blend" ]]; then
    status="complete"
  else
    status="failed"
  fi
  {
    echo
    echo "ended_at=${ended_at}"
    echo "exit_code=${exit_code}"
    echo "status=${status}"
  } >> "$run_log"
  write_result_file "$result_file" generate "$case_name" "$seed" "$jobs" \
    "$strategy" "$cpu_range" "$started_at" "$ended_at" "$exit_code" \
    "$status" "$run_log" "$time_txt"
  return 0
}

run_export_seed() {
  local case_name="$1"
  local case_dir="$2"
  local seed="$3"
  local jobs="$4"
  local strategy="$5"
  local cpu_range="$6"

  local input_folder="${case_dir}/seed_${seed}/coarse"
  local output_folder="${case_dir}/usd/seed_${seed}"
  local log_dir="${case_dir}/logs/seed_${seed}"
  local run_log="${log_dir}/export_run.log"
  local time_txt="${log_dir}/export_time.txt"
  local env_txt="${log_dir}/export_env.txt"
  local result_file="${log_dir}/result_export.env"
  mkdir -p "$output_folder" "$log_dir"

  local started_at ended_at exit_code status
  if [[ ! -f "${input_folder}/scene.blend" ]]; then
    started_at="$(timestamp)"
    ended_at="$started_at"
    echo "Skipping export because scene.blend is missing: ${input_folder}" > "$run_log"
    write_result_file "$result_file" export "$case_name" "$seed" "$jobs" \
      "$strategy" "$cpu_range" "$started_at" "$ended_at" 0 skipped "$run_log" ""
    return 0
  fi

  build_export_cmd "$cpu_range" "$input_folder" "$output_folder"
  write_env_file "$env_txt" export "$case_name" "$seed" "$jobs" \
    "$strategy" "$cpu_range" "${CMD[@]}"

  {
    echo "started_at=$(timestamp)"
    echo "export command:"
    quote_command "${CMD[@]}"
    echo
  } > "$run_log"

  if [[ "$DRY_RUN" == "1" ]]; then
    started_at="$(timestamp)"
    ended_at="$started_at"
    echo "DRY_RUN=1: export skipped." >> "$run_log"
    write_result_file "$result_file" export "$case_name" "$seed" "$jobs" \
      "$strategy" "$cpu_range" "$started_at" "$ended_at" 0 skipped "$run_log" ""
    return 0
  fi

  started_at="$(timestamp)"
  set +e
  /usr/bin/time -v -o "$time_txt" \
    timeout "$TIMEOUT_SECONDS" "${CMD[@]}" >> "$run_log" 2>&1
  exit_code=$?
  set -e
  ended_at="$(timestamp)"

  if [[ "$exit_code" == "124" ]]; then
    status="timeout"
  elif [[ "$exit_code" == "0" ]] \
    && find "$output_folder" -type f -name "*.usdc" -print -quit | grep -q .; then
    status="complete"
  else
    status="failed"
  fi
  {
    echo
    echo "ended_at=${ended_at}"
    echo "exit_code=${exit_code}"
    echo "status=${status}"
  } >> "$run_log"
  write_result_file "$result_file" export "$case_name" "$seed" "$jobs" \
    "$strategy" "$cpu_range" "$started_at" "$ended_at" "$exit_code" \
    "$status" "$run_log" "$time_txt"
  return 0
}

wait_for_slot() {
  local limit="$1"
  while (( $(jobs -pr | wc -l) >= limit )); do
    wait -n || true
  done
}

wait_for_all_jobs() {
  while (( $(jobs -pr | wc -l) > 0 )); do
    wait -n || true
  done
}

write_case_info() {
  local case_dir="$1"
  local case_name="$2"
  local jobs="$3"
  local strategy="$4"
  local cpu_sets_joined="$5"
  local started_at="$6"
  local ended_at="${7:-}"

  {
    echo "case_name=${case_name}"
    echo "output_root=${OUTPUT_ROOT}"
    echo "case_dir=${case_dir}"
    echo "jobs=${jobs}"
    echo "cpu_strategy=${strategy}"
    echo "cpu_sets=${cpu_sets_joined}"
    echo "seeds=${SEEDS}"
    echo "bench_mode=${BENCH_MODE}"
    echo "timeout_seconds=${TIMEOUT_SECONDS}"
    echo "full_timeout_seconds=${FULL_TIMEOUT_SECONDS}"
    echo "export_usd=${EXPORT_USD}"
    echo "export_jobs=${EXPORT_JOBS}"
    echo "export_resolution=${EXPORT_RESOLUTION}"
    echo "enable_wheat_reuse=${ENABLE_WHEAT_REUSE}"
    echo "dry_run=${DRY_RUN}"
    echo "started_at=${started_at}"
    if [[ -n "$ended_at" ]]; then
      echo "ended_at=${ended_at}"
    fi
  } > "${case_dir}/case.env"
}

run_case() {
  local case_name="$1"
  local jobs="$2"
  local strategy="$3"
  validate_jobs "$jobs"

  local case_dir="${OUTPUT_ROOT}/cases/${case_name}"
  mkdir -p "$case_dir"

  local cpu_sets_joined
  local cpu_set_list=()
  if [[ "$strategy" == "none" ]]; then
    for (( idx = 0; idx < jobs; idx++ )); do
      cpu_set_list+=("")
    done
    cpu_sets_joined="none"
  else
    cpu_sets_joined="$(resolve_cpu_sets "$strategy" "$jobs")"
    IFS=';' read -r -a cpu_set_list <<< "$cpu_sets_joined"
  fi

  echo
  echo "== Case ${case_name}: JOBS=${jobs}, CPU_STRATEGY=${strategy} =="
  echo "CPU sets: ${cpu_sets_joined}"
  echo "Seeds: ${SEEDS}"

  local case_started_at
  case_started_at="$(timestamp)"
  write_case_info "$case_dir" "$case_name" "$jobs" "$strategy" \
    "$cpu_sets_joined" "$case_started_at"

  local seed_index=0
  local seed cpu_range slot
  for seed in "${SEED_LIST[@]}"; do
    slot=$(( seed_index % jobs ))
    cpu_range="${cpu_set_list[$slot]:-}"
    wait_for_slot "$jobs"
    run_generate_seed "$case_name" "$case_dir" "$seed" "$jobs" "$strategy" \
      "$cpu_range" &
    seed_index=$(( seed_index + 1 ))
  done
  wait_for_all_jobs

  if [[ "$EXPORT_USD" == "1" ]]; then
    echo "Generation finished for ${case_name}; starting USD export with EXPORT_JOBS=${EXPORT_JOBS}."
    validate_jobs "$EXPORT_JOBS"
    seed_index=0
    for seed in "${SEED_LIST[@]}"; do
      slot=$(( seed_index % jobs ))
      cpu_range="${cpu_set_list[$slot]:-}"
      wait_for_slot "$EXPORT_JOBS"
      run_export_seed "$case_name" "$case_dir" "$seed" "$jobs" "$strategy" \
        "$cpu_range" &
      seed_index=$(( seed_index + 1 ))
    done
    wait_for_all_jobs
  fi

  local case_ended_at
  case_ended_at="$(timestamp)"
  write_case_info "$case_dir" "$case_name" "$jobs" "$strategy" \
    "$cpu_sets_joined" "$case_started_at" "$case_ended_at"
  "$PYTHON_BIN" scripts/analyze_9950x3d_parallel_scene_bench.py \
    "$OUTPUT_ROOT" --write-summaries >/dev/null
}

run_matrix() {
  run_case "jobs1_none" 1 none
  run_case "jobs2_split_llc" 2 split_llc
  run_case "jobs2_physical_cores_only" 2 physical_cores_only
  run_case "jobs4_split_llc" 4 split_llc
  run_case "jobs4_physical_cores_only" 4 physical_cores_only
}

run_single() {
  run_case "single_jobs${JOBS}_${CPU_STRATEGY}" "$JOBS" "$CPU_STRATEGY"
}

main() {
  parse_seeds
  require_tools
  acquire_output_root_lock
  ensure_no_active_output_root_users
  safe_clean_output_root
  mkdir -p "$OUTPUT_ROOT"
  collect_topology_text
  write_topology_json_and_md

  echo "Output root: ${OUTPUT_ROOT}"
  echo "Topology:"
  echo "  ${TOPOLOGY_TXT}"
  echo "  ${TOPOLOGY_JSON}"
  echo "  ${RECOMMENDED_CPU_SETS}"
  echo "BENCH_MODE=${BENCH_MODE}"
  echo "TIMEOUT_SECONDS=${TIMEOUT_SECONDS}"
  echo "ENABLE_WHEAT_REUSE=${ENABLE_WHEAT_REUSE}"
  echo "EXPORT_USD=${EXPORT_USD}"

  case "$BENCH_MODE" in
    single)
      run_single
      ;;
    matrix)
      run_matrix
      ;;
    *)
      echo "Unsupported BENCH_MODE=${BENCH_MODE}. Use single or matrix." >&2
      exit 2
      ;;
  esac

  "$PYTHON_BIN" scripts/analyze_9950x3d_parallel_scene_bench.py \
    "$OUTPUT_ROOT" --write-summaries

  local failed_count
  failed_count="$(
    "$PYTHON_BIN" - "${OUTPUT_ROOT}/summary_all_cases.csv" <<'PY'
import csv
import sys
from pathlib import Path

path = Path(sys.argv[1])
if not path.exists():
    print(0)
    raise SystemExit
with path.open(newline="") as handle:
    print(sum(1 for row in csv.DictReader(handle) if row.get("status") == "failed"))
PY
  )"
  if (( failed_count > 0 )); then
    echo "Benchmark completed with failed seed phases: ${failed_count}" >&2
    exit 1
  fi
}

main "$@"
