#!/usr/bin/env bash
set -u
set -o pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-${PYTHON:-python}}"
EXPERIMENT_TIMEOUT_SECONDS="${EXPERIMENT_TIMEOUT_SECONDS-14400}"
EXPERIMENT_SMOKE_SINGLE_ROOM="${EXPERIMENT_SMOKE_SINGLE_ROOM:-0}"
RUN_BASELINE_AA="${RUN_BASELINE_AA:-1}"
RUN_CANDIDATE_AA="${RUN_CANDIDATE_AA:-auto}"

OUTPUT_ROOT="outputs/determinism_ablation"

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

if [[ "$RUN_CANDIDATE_AA" == "auto" ]]; then
  if [[ "$EXPERIMENT_SMOKE_SINGLE_ROOM" == "1" ]]; then
    RUN_CANDIDATE_AA="1"
  else
    RUN_CANDIDATE_AA="0"
  fi
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

mode_label() {
  if [[ "$EXPERIMENT_SMOKE_SINGLE_ROOM" == "1" ]]; then
    echo "smoke_single_room"
  else
    echo "full_10_room"
  fi
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

reset_output_dir() {
  local output_dir="$1"
  case "$output_dir" in
    outputs/determinism_ablation/*/coarse)
      rm -rf "$output_dir"
      mkdir -p "$output_dir"
      ;;
    *)
      echo "Refusing to reset unexpected output dir: $output_dir" >&2
      exit 2
      ;;
  esac
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
  echo "=== run $label ==="
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
  echo "$label error_markers: $(scan_error_log "$log_path")"
  return "$status"
}

run_compare_pair() {
  local pair_name="$1"
  local first_label="$2"
  local second_label="$3"
  local batch_remove_enabled="$4"

  local pair_root="${OUTPUT_ROOT}/${pair_name}"
  local first_dir="${pair_root}/${first_label}/coarse"
  local second_dir="${pair_root}/${second_label}/coarse"
  local first_log="${pair_root}/${first_label}.log"
  local second_log="${pair_root}/${second_label}.log"
  local json_log="${pair_root}/compare_json.log"
  local blend_log="${pair_root}/compare_blend_static_scene.log"

  mkdir -p "$pair_root"
  rm -f "$json_log" "$blend_log"

  echo
  echo "=== pair $pair_name ==="
  echo "first: $first_label"
  echo "second: $second_label"
  echo "batch_remove_enabled: $batch_remove_enabled"

  run_case "$first_label" "$first_dir" "$first_log" "$batch_remove_enabled"
  local first_status=$?

  run_case "$second_label" "$second_dir" "$second_log" "$batch_remove_enabled"
  local second_status=$?

  echo
  echo "=== $pair_name compare_indoor_outputs.py ==="
  "$PYTHON_BIN" scripts/compare_indoor_outputs.py "$first_dir" "$second_dir" 2>&1 | tee "$json_log"
  local json_status="${PIPESTATUS[0]}"

  echo
  echo "=== $pair_name compare_blend_static_scene.py ==="
  "$PYTHON_BIN" scripts/compare_blend_static_scene.py "$first_dir" "$second_dir" 2>&1 | tee "$blend_log"
  local blend_status="${PIPESTATUS[0]}"

  local no_comparable_json=0
  if grep -q "NO_COMPARABLE_JSON_FOUND" "$json_log"; then
    no_comparable_json=1
  fi

  echo
  echo "=== $pair_name summary ==="
  echo "${pair_name}_first_status=$first_status ($(status_label "$first_status"))"
  echo "${pair_name}_second_status=$second_status ($(status_label "$second_status"))"
  echo "${pair_name}_json_compare_status=$json_status"
  echo "${pair_name}_static_scene_compare_status=$blend_status"
  echo "${pair_name}_no_comparable_json=$no_comparable_json"
  echo "${pair_name}_first_error_markers=$(scan_error_log "$first_log")"
  echo "${pair_name}_second_error_markers=$(scan_error_log "$second_log")"
  echo "${pair_name}_first_dir=$first_dir"
  echo "${pair_name}_second_dir=$second_dir"
  echo "${pair_name}_json_compare_log=$json_log"
  echo "${pair_name}_static_scene_compare_log=$blend_log"

  if [[ "$first_status" -eq 124 || "$second_status" -eq 124 ]]; then
    echo "${pair_name}_TIMEOUT_DETECTED: this is not a complete determinism comparison."
  fi
  if [[ "$no_comparable_json" -eq 1 ]]; then
    echo "${pair_name}_NO_COMPARABLE_JSON_FOUND: this is not a complete determinism comparison."
  fi

  if [[ "$first_status" -ne 0 && "$first_status" -ne 124 ]]; then
    return "$first_status"
  fi
  if [[ "$second_status" -ne 0 && "$second_status" -ne 124 ]]; then
    return "$second_status"
  fi
  if [[ "$first_status" -eq 124 || "$second_status" -eq 124 ]]; then
    return 124
  fi
  if [[ "$json_status" -ne 0 ]]; then
    return "$json_status"
  fi
  return "$blend_status"
}

mkdir -p "$OUTPUT_ROOT"

echo "=== determinism ablation ==="
echo "mode: $(mode_label)"
echo "python: $PYTHON_BIN"
echo "configs: ${CONFIGS[*]}"
echo "overrides: ${GIN_OVERRIDES[*]}"
echo "timeout: $(timeout_label)"
echo "output_root: $OUTPUT_ROOT"
echo "run_baseline_aa: $RUN_BASELINE_AA"
echo "run_candidate_aa: $RUN_CANDIDATE_AA"
echo "NOTE: baseline-vs-candidate is not run by default; existing A/B results remain the reference."
echo "NOTE: This script does not enable INFINIGEN_PROFILE_TIMING, INFINIGEN_PROFILE_GC, INFINIGEN_PROFILE_ASSET_FACTORY, or INFINIGEN_PROFILE_BBOX."
if [[ "$EXPERIMENT_SMOKE_SINGLE_ROOM" == "1" ]]; then
  echo "SMOKE_SINGLE_ROOM: validates determinism harness and obvious differences only; it does not prove the 10-room mainline path."
fi

overall_status=0

if [[ "$RUN_BASELINE_AA" == "1" ]]; then
  run_compare_pair "baseline_aa" "baseline_a" "baseline_b" "0"
  pair_status=$?
  if [[ "$pair_status" -ne 0 && "$overall_status" -eq 0 ]]; then
    overall_status="$pair_status"
  fi
else
  echo "Skipping baseline_aa because RUN_BASELINE_AA=$RUN_BASELINE_AA"
fi

if [[ "$RUN_CANDIDATE_AA" == "1" ]]; then
  run_compare_pair "candidate_aa" "candidate_a" "candidate_b" "1"
  pair_status=$?
  if [[ "$pair_status" -ne 0 && "$overall_status" -eq 0 ]]; then
    overall_status="$pair_status"
  fi
else
  echo "Skipping candidate_aa because RUN_CANDIDATE_AA=$RUN_CANDIDATE_AA"
fi

echo
echo "=== determinism ablation final ==="
echo "overall_status=$overall_status"
if [[ "$EXPERIMENT_SMOKE_SINGLE_ROOM" == "1" ]]; then
  echo "SMOKE_SINGLE_ROOM_RESULT: useful only for script validation and quick determinism checks; full 10-room A/A remains required for mainline conclusions."
fi

exit "$overall_status"
