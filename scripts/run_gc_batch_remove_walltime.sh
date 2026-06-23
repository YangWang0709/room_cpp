#!/usr/bin/env bash
set -u
set -o pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-${PYTHON:-python}}"
TIME_BIN="${TIME_BIN:-/usr/bin/time}"
EXPERIMENT_TIMEOUT_SECONDS="${EXPERIMENT_TIMEOUT_SECONDS-14400}"
EXPERIMENT_SMOKE_SINGLE_ROOM="${EXPERIMENT_SMOKE_SINGLE_ROOM:-0}"

OUTPUT_ROOT="outputs/gc_batch_remove_walltime"
BASELINE_DIR="${OUTPUT_ROOT}/baseline/coarse"
CANDIDATE_DIR="${OUTPUT_ROOT}/candidate_batch/coarse"
BASELINE_LOG="${OUTPUT_ROOT}/baseline.log"
CANDIDATE_LOG="${OUTPUT_ROOT}/candidate_batch.log"
BASELINE_TIME_LOG="${OUTPUT_ROOT}/baseline.time.txt"
CANDIDATE_TIME_LOG="${OUTPUT_ROOT}/candidate_batch.time.txt"
COMPARE_LOG="${OUTPUT_ROOT}/compare.log"
SUMMARY_FILE="${OUTPUT_ROOT}/summary.txt"

COMMON_ARGS=(
  -m infinigen_examples.generate_indoors
  --seed 0
  --task coarse
)

CONFIGS=(fast_solve.gin)
GIN_OVERRIDES=(
  -p
  compose_indoors.terrain_enabled=False
  home_room_constraints.has_fewer_rooms=False
  restrict_solving.solve_max_rooms=10
)

if [[ "$EXPERIMENT_SMOKE_SINGLE_ROOM" == "1" ]]; then
  CONFIGS=(fast_solve.gin singleroom.gin)
  GIN_OVERRIDES=(
    -p
    compose_indoors.terrain_enabled=False
    home_room_constraints.has_fewer_rooms=True
    restrict_solving.solve_max_rooms=1
  )
fi

BASELINE_WALL_SECONDS="unavailable"
BASELINE_MAX_RSS_KB="unavailable"
CANDIDATE_WALL_SECONDS="unavailable"
CANDIDATE_MAX_RSS_KB="unavailable"

timeout_enabled() {
  [[ -n "$EXPERIMENT_TIMEOUT_SECONDS" && "$EXPERIMENT_TIMEOUT_SECONDS" != "0" ]]
}

timeout_label() {
  if timeout_enabled; then
    echo "${EXPERIMENT_TIMEOUT_SECONDS}s"
  else
    echo "disabled"
  fi
}

log_summary() {
  echo "$*" | tee -a "$SUMMARY_FILE"
}

reset_output_dir() {
  local output_dir="$1"
  case "$output_dir" in
    outputs/gc_batch_remove_walltime/*/coarse)
      rm -rf "$output_dir"
      mkdir -p "$output_dir"
      ;;
    *)
      echo "Refusing to reset unexpected output dir: $output_dir" >&2
      exit 2
      ;;
  esac
}

status_label() {
  local status="$1"
  if [[ "$status" -eq 0 ]]; then
    echo "complete"
  elif [[ "$status" -eq 124 ]]; then
    echo "timeout"
  else
    echo "failed(${status})"
  fi
}

parse_max_rss_kb() {
  local time_log="$1"
  if [[ ! -f "$time_log" ]]; then
    echo "unavailable"
    return
  fi
  awk -F: '/Maximum resident set size/ {
    value=$2
    gsub(/^[ \t]+|[ \t]+$/, "", value)
    print value
  }' "$time_log" | tail -n 1
}

scan_error_log() {
  local log_path="$1"
  if [[ ! -f "$log_path" ]]; then
    echo "log_missing"
    return
  fi
  if grep -Eiq "Traceback|out[ -]of[ -]memory|segmentation fault|segfault|(^|[^[:alnum:]_])(oom|killed)([^[:alnum:]_]|$)" "$log_path"; then
    echo "yes"
  else
    echo "no"
  fi
}

run_timed_command() {
  local time_log="$1"
  shift

  if [[ -x "$TIME_BIN" ]]; then
    if timeout_enabled; then
      "$TIME_BIN" -v -o "$time_log" timeout "$EXPERIMENT_TIMEOUT_SECONDS" "$@"
    else
      "$TIME_BIN" -v -o "$time_log" "$@"
    fi
  else
    echo "WARNING: $TIME_BIN not executable; max RSS will be unavailable." >&2
    rm -f "$time_log"
    if timeout_enabled; then
      timeout "$EXPERIMENT_TIMEOUT_SECONDS" "$@"
    else
      "$@"
    fi
  fi
}

run_case() {
  local label="$1"
  local output_dir="$2"
  local log_path="$3"
  local time_log="$4"
  local batch_remove_enabled="$5"

  local env_cmd=(
    env
    -u INFINIGEN_PROFILE_TIMING
    -u INFINIGEN_PROFILE_GC
    -u INFINIGEN_PROFILE_ASSET_FACTORY
    -u INFINIGEN_PROFILE_BBOX
    -u INFINIGEN_GC_NODE_GROUP_INTERVAL
  )
  if [[ "$batch_remove_enabled" == "1" ]]; then
    env_cmd+=(INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1)
  else
    env_cmd+=(-u INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS)
  fi

  local command=(
    "$PYTHON_BIN"
    "${COMMON_ARGS[@]}"
    --output_folder "$output_dir"
    -g "${CONFIGS[@]}"
    "${GIN_OVERRIDES[@]}"
  )

  echo
  echo "=== $label ==="
  echo "output_folder: $output_dir"
  echo "log: $log_path"
  echo "time_log: $time_log"
  echo "INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=$batch_remove_enabled"
  echo "heavy timing env: unset"
  echo "timeout: $(timeout_label)"

  reset_output_dir "$output_dir"
  rm -f "$log_path" "$time_log"

  local start_ns
  start_ns="$(date +%s%N)"
  run_timed_command "$time_log" "${env_cmd[@]}" "${command[@]}" 2>&1 | tee "$log_path"
  local status="${PIPESTATUS[0]}"
  local end_ns
  end_ns="$(date +%s%N)"

  local wall_seconds
  wall_seconds="$(awk -v start="$start_ns" -v end="$end_ns" 'BEGIN { printf "%.3f", (end - start) / 1000000000 }')"
  local max_rss_kb
  max_rss_kb="$(parse_max_rss_kb "$time_log")"
  if [[ -z "$max_rss_kb" ]]; then
    max_rss_kb="unavailable"
  fi

  case "$label" in
    baseline)
      BASELINE_WALL_SECONDS="$wall_seconds"
      BASELINE_MAX_RSS_KB="$max_rss_kb"
      ;;
    candidate_batch)
      CANDIDATE_WALL_SECONDS="$wall_seconds"
      CANDIDATE_MAX_RSS_KB="$max_rss_kb"
      ;;
  esac

  echo "$label status: $(status_label "$status")"
  echo "$label wall_seconds: $wall_seconds"
  echo "$label max_rss_kb: $max_rss_kb"
  return "$status"
}

compute_speedup() {
  if [[ "$BASELINE_WALL_SECONDS" == "unavailable" || "$CANDIDATE_WALL_SECONDS" == "unavailable" ]]; then
    echo "unavailable"
    return
  fi
  awk -v baseline="$BASELINE_WALL_SECONDS" -v candidate="$CANDIDATE_WALL_SECONDS" 'BEGIN {
    if (candidate > 0) {
      printf "%.3fx", baseline / candidate
    } else {
      print "unavailable"
    }
  }'
}

mkdir -p "$OUTPUT_ROOT"
rm -f "$BASELINE_LOG" "$CANDIDATE_LOG" "$BASELINE_TIME_LOG" "$CANDIDATE_TIME_LOG" "$COMPARE_LOG" "$SUMMARY_FILE"

log_summary "=== gc batch remove wall-clock A/B ==="
log_summary "mode: $([[ "$EXPERIMENT_SMOKE_SINGLE_ROOM" == "1" ]] && echo smoke_single_room || echo full_10_room)"
log_summary "python: $PYTHON_BIN"
log_summary "time_bin: $TIME_BIN"
log_summary "configs: ${CONFIGS[*]}"
log_summary "overrides: ${GIN_OVERRIDES[*]}"
log_summary "timeout: $(timeout_label)"
log_summary "output_root: $OUTPUT_ROOT"
log_summary "NOTE: This script does not enable INFINIGEN_PROFILE_TIMING, INFINIGEN_PROFILE_GC, INFINIGEN_PROFILE_ASSET_FACTORY, or INFINIGEN_PROFILE_BBOX."
if [[ "$EXPERIMENT_SMOKE_SINGLE_ROOM" == "1" ]]; then
  log_summary "SMOKE_SINGLE_ROOM: validates the script and obvious equivalence only; it does not prove the 10-room mainline path."
fi

run_case "baseline" "$BASELINE_DIR" "$BASELINE_LOG" "$BASELINE_TIME_LOG" "0"
BASELINE_STATUS=$?

run_case "candidate_batch" "$CANDIDATE_DIR" "$CANDIDATE_LOG" "$CANDIDATE_TIME_LOG" "1"
CANDIDATE_STATUS=$?

echo
echo "=== compare_indoor_outputs.py ==="
"$PYTHON_BIN" scripts/compare_indoor_outputs.py "$BASELINE_DIR" "$CANDIDATE_DIR" 2>&1 | tee "$COMPARE_LOG"
COMPARE_STATUS="${PIPESTATUS[0]}"

NO_COMPARABLE_JSON=0
if grep -q "NO_COMPARABLE_JSON_FOUND" "$COMPARE_LOG"; then
  NO_COMPARABLE_JSON=1
fi

SPEEDUP="$(compute_speedup)"

{
  echo
  echo "=== compare_indoor_outputs.py ==="
  cat "$COMPARE_LOG"
  echo
} >> "$SUMMARY_FILE"

log_summary "=== summary ==="
log_summary "baseline_status=$BASELINE_STATUS ($(status_label "$BASELINE_STATUS"))"
log_summary "candidate_status=$CANDIDATE_STATUS ($(status_label "$CANDIDATE_STATUS"))"
log_summary "compare_status=$COMPARE_STATUS"
log_summary "no_comparable_json=$NO_COMPARABLE_JSON"
log_summary "baseline_wall_seconds=$BASELINE_WALL_SECONDS"
log_summary "candidate_wall_seconds=$CANDIDATE_WALL_SECONDS"
log_summary "speedup=$SPEEDUP"
log_summary "baseline_max_rss_kb=$BASELINE_MAX_RSS_KB"
log_summary "candidate_max_rss_kb=$CANDIDATE_MAX_RSS_KB"
log_summary "baseline_dir=$BASELINE_DIR"
log_summary "candidate_dir=$CANDIDATE_DIR"
log_summary "compare_log=$COMPARE_LOG"
log_summary "summary_file=$SUMMARY_FILE"
log_summary "baseline_error_markers=$(scan_error_log "$BASELINE_LOG")"
log_summary "candidate_error_markers=$(scan_error_log "$CANDIDATE_LOG")"

if [[ "$BASELINE_STATUS" -eq 124 || "$CANDIDATE_STATUS" -eq 124 ]]; then
  log_summary "TIMEOUT_DETECTED: this is not a complete A/B and cannot be used as mainline evidence."
fi
if [[ "$NO_COMPARABLE_JSON" -eq 1 ]]; then
  log_summary "NO_COMPARABLE_JSON_FOUND: this is not a complete A/B and cannot be used as mainline evidence."
fi
if [[ "$BASELINE_STATUS" -ne 0 || "$CANDIDATE_STATUS" -ne 0 || "$COMPARE_STATUS" -ne 0 ]]; then
  log_summary "WALLTIME_NOTE: speedup is not a validated full-run speedup unless both runs complete and compare PASS."
fi
if [[ "$EXPERIMENT_SMOKE_SINGLE_ROOM" == "1" ]]; then
  log_summary "SMOKE_SINGLE_ROOM_RESULT: useful only for script validation; 10-room A/B remains required."
fi

if [[ "$BASELINE_STATUS" -ne 0 && "$BASELINE_STATUS" -ne 124 ]]; then
  exit "$BASELINE_STATUS"
fi
if [[ "$CANDIDATE_STATUS" -ne 0 && "$CANDIDATE_STATUS" -ne 124 ]]; then
  exit "$CANDIDATE_STATUS"
fi
if [[ "$BASELINE_STATUS" -eq 124 || "$CANDIDATE_STATUS" -eq 124 ]]; then
  exit 124
fi
exit "$COMPARE_STATUS"
