#!/usr/bin/env bash
set -u

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-${PYTHON:-python}}"
EXPERIMENT_TIMEOUT_SECONDS="${EXPERIMENT_TIMEOUT_SECONDS:-1200}"

BASELINE_DIR="outputs/gc_batch_remove_ab/baseline/coarse"
CANDIDATE_DIR="outputs/gc_batch_remove_ab/candidate_batch/coarse"

COMMON_ARGS=(
  -m infinigen_examples.generate_indoors
  --seed 0
  --task coarse
)

GIN_OVERRIDES=(
  -g fast_solve.gin
  -p
  compose_indoors.terrain_enabled=False
  home_room_constraints.has_fewer_rooms=False
  restrict_solving.solve_max_rooms=10
)

reset_output_dir() {
  local output_dir="$1"
  case "$output_dir" in
    outputs/gc_batch_remove_ab/*/coarse)
      rm -rf "$output_dir"
      mkdir -p "$output_dir"
      ;;
    *)
      echo "Refusing to reset unexpected output dir: $output_dir" >&2
      exit 2
      ;;
  esac
}

run_case() {
  local label="$1"
  local output_dir="$2"
  local batch_remove_enabled="$3"

  echo
  echo "=== $label ==="
  echo "output_folder: $output_dir"
  echo "INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=$batch_remove_enabled"
  echo "timeout: ${EXPERIMENT_TIMEOUT_SECONDS}s"

  reset_output_dir "$output_dir"

  if [[ "$batch_remove_enabled" == "1" ]]; then
    env \
      INFINIGEN_PROFILE_TIMING=1 \
      INFINIGEN_PROFILE_GC=1 \
      INFINIGEN_PROFILE_ASSET_FACTORY=1 \
      INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1 \
      timeout "$EXPERIMENT_TIMEOUT_SECONDS" "$PYTHON_BIN" \
        "${COMMON_ARGS[@]}" \
        --output_folder "$output_dir" \
        "${GIN_OVERRIDES[@]}"
  else
    env -u INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS \
      INFINIGEN_PROFILE_TIMING=1 \
      INFINIGEN_PROFILE_GC=1 \
      INFINIGEN_PROFILE_ASSET_FACTORY=1 \
      timeout "$EXPERIMENT_TIMEOUT_SECONDS" "$PYTHON_BIN" \
        "${COMMON_ARGS[@]}" \
        --output_folder "$output_dir" \
        "${GIN_OVERRIDES[@]}"
  fi
  local status=$?

  if [[ "$status" -eq 0 ]]; then
    echo "$label status: complete"
  elif [[ "$status" -eq 124 ]]; then
    echo "$label status: timeout"
  else
    echo "$label status: failed($status)"
  fi
  return "$status"
}

run_case "baseline" "$BASELINE_DIR" "0"
BASELINE_STATUS=$?

run_case "candidate_batch" "$CANDIDATE_DIR" "1"
CANDIDATE_STATUS=$?

echo
echo "=== compare_indoor_outputs.py ==="
"$PYTHON_BIN" scripts/compare_indoor_outputs.py "$BASELINE_DIR" "$CANDIDATE_DIR"
COMPARE_STATUS=$?

echo
echo "=== summary ==="
echo "baseline_status=$BASELINE_STATUS"
echo "candidate_status=$CANDIDATE_STATUS"
echo "compare_status=$COMPARE_STATUS"
echo "baseline_dir=$BASELINE_DIR"
echo "candidate_dir=$CANDIDATE_DIR"

if [[ "$BASELINE_STATUS" -eq 124 || "$CANDIDATE_STATUS" -eq 124 ]]; then
  echo "NOTE: at least one run timed out; this is not a complete A/B."
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
