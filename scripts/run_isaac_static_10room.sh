#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-${PYTHON:-python}}"
SEED="${SEED:-0}"
CLEAN="${CLEAN:-0}"
OUTPUT_DIR="outputs/isaac_static_seed${SEED}_10room/coarse"

if [[ ! "$SEED" =~ ^[A-Za-z0-9_.-]+$ ]]; then
  echo "Invalid SEED '$SEED'. Use a simple seed value without slashes or spaces." >&2
  exit 2
fi

if [[ "$CLEAN" != "0" && "$CLEAN" != "1" ]]; then
  echo "Invalid CLEAN '$CLEAN'. Use CLEAN=1 to remove the previous output directory." >&2
  exit 2
fi

if [[ "$CLEAN" == "1" ]]; then
  case "$OUTPUT_DIR" in
    outputs/isaac_static_seed*_10room/coarse)
      rm -rf "$OUTPUT_DIR"
      ;;
    *)
      echo "Refusing to clean unexpected output dir: $OUTPUT_DIR" >&2
      exit 2
      ;;
  esac
fi

mkdir -p "$OUTPUT_DIR"

ENV_CMD=(
  env
  -u INFINIGEN_PROFILE_TIMING
  -u INFINIGEN_PROFILE_GC
  -u INFINIGEN_PROFILE_ASSET_FACTORY
  -u INFINIGEN_PROFILE_BBOX
  -u INFINIGEN_GC_NODE_GROUP_INTERVAL
  INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1
)

COMMAND=(
  "$PYTHON_BIN"
  -m infinigen_examples.generate_indoors
  --seed "$SEED"
  --task coarse
  --output_folder "$OUTPUT_DIR"
  -g fast_solve.gin
  -p
  compose_indoors.terrain_enabled=False
  home_room_constraints.has_fewer_rooms=False
  restrict_solving.solve_max_rooms=10
  populate_doors.door_chance=0
)

echo "=== isaac static 10-room coarse generation ==="
echo "python: $PYTHON_BIN"
echo "seed: $SEED"
echo "output_folder: $OUTPUT_DIR"
echo "INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1"
echo "heavy profiling env: unset"
echo "door_chance: 0"
echo
printf 'command:'
printf ' %q' "${ENV_CMD[@]}" "${COMMAND[@]}"
printf '\n\n'

"${ENV_CMD[@]}" "${COMMAND[@]}"
