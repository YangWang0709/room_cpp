#!/usr/bin/env bash
set -euo pipefail

PROFILE_OUTPUT="/tmp/indoors_coarse.prof"
OUTPUT_ROOT="outputs/profile_indoor_baseline"
COARSE_OUTPUT="${OUTPUT_ROOT}/coarse"

echo "Removing existing baseline output: ${OUTPUT_ROOT}"
rm -rf "${OUTPUT_ROOT}"

echo "Writing cProfile data to: ${PROFILE_OUTPUT}"
python -m cProfile -o "${PROFILE_OUTPUT}" -m infinigen_examples.generate_indoors \
  --seed 0 \
  --task coarse \
  --output_folder "${COARSE_OUTPUT}" \
  -g fast_solve.gin \
  -p compose_indoors.terrain_enabled=False \
     home_room_constraints.has_fewer_rooms=False \
     restrict_solving.solve_max_rooms=10

echo "Profile complete."
echo "View cumulative profile results with:"
echo "  python scripts/print_indoor_profile.py"
