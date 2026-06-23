#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

SEED="${SEED:-0}"
PYTHON_BIN="${PYTHON_BIN:-${PYTHON:-python}}"
CLEAN="${CLEAN:-0}"
EXPORT_USD="${EXPORT_USD:-0}"
EXPORT_RESOLUTION="${EXPORT_RESOLUTION:-512}"
DRY_RUN="${DRY_RUN:-0}"

OUTPUT_ROOT="outputs/isaac_static_optimized_seed${SEED}_10room"
COARSE_OUTPUT="${OUTPUT_ROOT}/coarse"
USD_OUTPUT="outputs/usd_compare/isaac_static_optimized_seed${SEED}_10room"

export INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS="${INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS:-1}"
export INFINIGEN_REUSE_LARGESHELF_CHILD_NODEGROUPS="${INFINIGEN_REUSE_LARGESHELF_CHILD_NODEGROUPS:-1}"
export INFINIGEN_FAST_NATURE_TRINKET_STABLE_POSE="${INFINIGEN_FAST_NATURE_TRINKET_STABLE_POSE:-1}"

quote_command() {
  printf "%q " "$@"
  printf "\n"
}

print_header() {
  echo "pwd: $(pwd)"
  echo "git_commit: $(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
  if command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    echo "python_bin: $(command -v "$PYTHON_BIN")"
  else
    echo "python_bin: $PYTHON_BIN"
  fi
  "$PYTHON_BIN" -V
  echo "SEED=${SEED}"
  echo "EXPORT_USD=${EXPORT_USD}"
  echo "EXPORT_RESOLUTION=${EXPORT_RESOLUTION}"
  echo "INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=${INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS}"
  echo "INFINIGEN_REUSE_LARGESHELF_CHILD_NODEGROUPS=${INFINIGEN_REUSE_LARGESHELF_CHILD_NODEGROUPS}"
  echo "INFINIGEN_FAST_NATURE_TRINKET_STABLE_POSE=${INFINIGEN_FAST_NATURE_TRINKET_STABLE_POSE}"
  echo
}

print_outputs() {
  echo
  echo "coarse output path: ${COARSE_OUTPUT}"
  if [[ "$EXPORT_USD" == "1" ]]; then
    echo "USD output path: ${USD_OUTPUT}"
  fi
  echo
  echo "coarse key files:"
  find "$COARSE_OUTPUT" -maxdepth 1 -type f \
    \( -name "scene.blend" -o -name "solve_state.json" -o -name "MaskTag.json" \) \
    -print 2>/dev/null | sort || true
  if [[ "$EXPORT_USD" == "1" ]]; then
    echo
    echo "USD files:"
    find "$USD_OUTPUT" -type f \
      \( -name "*.usd" -o -name "*.usdc" -o -name "*.usda" \) \
      -print 2>/dev/null | sort || true
    echo
    echo "Isaac Sim host path:"
    echo "  Open the host directory: $(realpath -m "$USD_OUTPUT")"
    echo "  Keep the complete export directory together; do not move only one .usdc file."
  fi
}

safe_clean_coarse_output() {
  case "$COARSE_OUTPUT" in
    outputs/isaac_static_optimized_seed*_10room/coarse)
      echo "Removing existing coarse output: ${COARSE_OUTPUT}"
      rm -rf "$COARSE_OUTPUT"
      ;;
    *)
      echo "Refusing to clean unexpected path: ${COARSE_OUTPUT}" >&2
      exit 2
      ;;
  esac
}

GENERATE_CMD=(
  "$PYTHON_BIN"
  -m infinigen_examples.generate_indoors
  --seed "$SEED"
  --task coarse
  --output_folder "$COARSE_OUTPUT"
  -g fast_solve.gin
  -p
  compose_indoors.terrain_enabled=False
  home_room_constraints.has_fewer_rooms=False
  restrict_solving.solve_max_rooms=10
  populate_doors.door_chance=0
)

EXPORT_CMD=(
  "$PYTHON_BIN"
  -m infinigen.tools.export
  --input_folder "$COARSE_OUTPUT"
  --output_folder "$USD_OUTPUT"
  -f usdc
  -r "$EXPORT_RESOLUTION"
  --omniverse
)

print_header

echo "generate command:"
quote_command "${GENERATE_CMD[@]}"
if [[ "$EXPORT_USD" == "1" ]]; then
  echo "export command:"
  quote_command "${EXPORT_CMD[@]}"
fi

if [[ "$DRY_RUN" == "1" ]]; then
  echo
  echo "DRY_RUN=1: commands printed; generation/export skipped."
  echo "coarse output path: ${COARSE_OUTPUT}"
  if [[ "$EXPORT_USD" == "1" ]]; then
    echo "USD output path: ${USD_OUTPUT}"
  fi
  exit 0
fi

if [[ "$CLEAN" == "1" ]]; then
  safe_clean_coarse_output
fi

mkdir -p "$COARSE_OUTPUT"
"${GENERATE_CMD[@]}"

if [[ "$EXPORT_USD" == "1" ]]; then
  mkdir -p "$USD_OUTPUT"
  "${EXPORT_CMD[@]}"
fi

print_outputs
