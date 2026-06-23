#!/usr/bin/env bash
set -u
set -o pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-${PYTHON:-python}}"
EXPERIMENT_TIMEOUT_SECONDS="${EXPERIMENT_TIMEOUT_SECONDS-14400}"
EXPERIMENT_SMOKE_SINGLE_ROOM="${EXPERIMENT_SMOKE_SINGLE_ROOM:-0}"

OUTPUT_ROOT="outputs/gc_batch_remove_equiv"
BASELINE_DIR="${OUTPUT_ROOT}/baseline/coarse"
CANDIDATE_DIR="${OUTPUT_ROOT}/candidate_batch/coarse"
BASELINE_LOG="${OUTPUT_ROOT}/baseline.log"
CANDIDATE_LOG="${OUTPUT_ROOT}/candidate_batch.log"
COMPARE_LOG="${OUTPUT_ROOT}/compare.log"

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

reset_output_dir() {
  local output_dir="$1"
  case "$output_dir" in
    outputs/gc_batch_remove_equiv/*/coarse)
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

run_case() {
  local label="$1"
  local output_dir="$2"
  local log_path="$3"
  local batch_remove_enabled="$4"

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
  echo "INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=$batch_remove_enabled"
  echo "heavy timing env: unset"
  echo "timeout: $(timeout_label)"

  reset_output_dir "$output_dir"
  rm -f "$log_path"

  if timeout_enabled; then
    timeout "$EXPERIMENT_TIMEOUT_SECONDS" "${env_cmd[@]}" "${command[@]}" 2>&1 | tee "$log_path"
  else
    "${env_cmd[@]}" "${command[@]}" 2>&1 | tee "$log_path"
  fi
  local status="${PIPESTATUS[0]}"

  echo "$label status: $(status_label "$status")"
  return "$status"
}

mkdir -p "$OUTPUT_ROOT"
rm -f "$COMPARE_LOG"

echo "=== gc batch remove equivalence A/B ==="
echo "mode: $([[ "$EXPERIMENT_SMOKE_SINGLE_ROOM" == "1" ]] && echo smoke_single_room || echo full_10_room)"
echo "python: $PYTHON_BIN"
echo "configs: ${CONFIGS[*]}"
echo "overrides: ${GIN_OVERRIDES[*]}"
echo "timeout: $(timeout_label)"
echo "output_root: $OUTPUT_ROOT"
echo "NOTE: This script does not enable INFINIGEN_PROFILE_TIMING, INFINIGEN_PROFILE_GC, INFINIGEN_PROFILE_ASSET_FACTORY, or INFINIGEN_PROFILE_BBOX."
if [[ "$EXPERIMENT_SMOKE_SINGLE_ROOM" == "1" ]]; then
  echo "SMOKE_SINGLE_ROOM: validates the script and obvious equivalence only; it does not prove the 10-room mainline path."
fi

run_case "baseline" "$BASELINE_DIR" "$BASELINE_LOG" "0"
BASELINE_STATUS=$?

run_case "candidate_batch" "$CANDIDATE_DIR" "$CANDIDATE_LOG" "1"
CANDIDATE_STATUS=$?

echo
echo "=== compare_indoor_outputs.py ==="
"$PYTHON_BIN" scripts/compare_indoor_outputs.py "$BASELINE_DIR" "$CANDIDATE_DIR" 2>&1 | tee "$COMPARE_LOG"
COMPARE_STATUS="${PIPESTATUS[0]}"

NO_COMPARABLE_JSON=0
if grep -q "NO_COMPARABLE_JSON_FOUND" "$COMPARE_LOG"; then
  NO_COMPARABLE_JSON=1
fi

echo
echo "=== summary ==="
echo "baseline_status=$BASELINE_STATUS ($(status_label "$BASELINE_STATUS"))"
echo "candidate_status=$CANDIDATE_STATUS ($(status_label "$CANDIDATE_STATUS"))"
echo "compare_status=$COMPARE_STATUS"
echo "no_comparable_json=$NO_COMPARABLE_JSON"
echo "baseline_dir=$BASELINE_DIR"
echo "candidate_dir=$CANDIDATE_DIR"
echo "compare_log=$COMPARE_LOG"
echo "baseline_error_markers=$(scan_error_log "$BASELINE_LOG")"
echo "candidate_error_markers=$(scan_error_log "$CANDIDATE_LOG")"

if [[ "$BASELINE_STATUS" -eq 124 || "$CANDIDATE_STATUS" -eq 124 ]]; then
  echo "TIMEOUT_DETECTED: this is not a complete A/B and cannot be used as mainline evidence."
fi
if [[ "$NO_COMPARABLE_JSON" -eq 1 ]]; then
  echo "NO_COMPARABLE_JSON_FOUND: this is not a complete A/B and cannot be used as mainline evidence."
fi
if [[ "$EXPERIMENT_SMOKE_SINGLE_ROOM" == "1" ]]; then
  echo "SMOKE_SINGLE_ROOM_RESULT: useful only for script validation; 10-room A/B remains required."
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
