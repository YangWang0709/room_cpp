# Commands

## Run 9950X3D Production Scene Queue

Use this for the current 9950X3D production path after the clean `JOBS=4` CCD
split coarse benchmark. This is scene-level multiprocessing: each seed runs in
an independent Python-Blender process. It is not Python threading inside one
Blender / `bpy` process.

Each worker keeps a fixed CPU set and processes its own queue serially:

```text
worker: coarse -> export USD/USDC -> next seed
```

Current default candidate:

```text
JOBS=4
CPU_SETS="0-3,16-19;4-7,20-23;8-11,24-27;12-15,28-31"
```

Correct observed 9950X3D CCD / L3 groups:

```text
CCD0 / L3: 0-7,16-23
CCD1 / L3: 8-15,24-31
```

Do not use `0-15;16-31` as the default CPU split.

Dry-run the default worker assignment and commands:

```bash
DRY_RUN=1 \
SEEDS=100,101,102,103,104,105,106,107 \
JOBS=4 \
EXPORT_AFTER_GENERATE=1 \
bash scripts/run_9950x3d_production_scene_queue.sh
```

Run a production queue batch:

```bash
SEEDS=100-139 \
JOBS=4 \
CPU_SETS="0-3,16-19;4-7,20-23;8-11,24-27;12-15,28-31" \
EXPORT_AFTER_GENERATE=1 \
bash scripts/run_9950x3d_production_scene_queue.sh
```

The queue defaults to the stable Isaac static speed flags:

```text
INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1
INFINIGEN_REUSE_LARGESHELF_CHILD_NODEGROUPS=1
INFINIGEN_FAST_NATURE_TRINKET_STABLE_POSE=1
compose_indoors.terrain_enabled=False
home_room_constraints.has_fewer_rooms=False
restrict_solving.solve_max_rooms=10
populate_doors.door_chance=0
```

Wheat template reuse is default-off. It is only enabled when explicitly set:

```bash
ENABLE_WHEAT_REUSE=1 bash scripts/run_9950x3d_production_scene_queue.sh
```

Export runs serially inside each worker after that worker's coarse scene
finishes. The queue does not add a separate global export concurrency layer.
If export becomes the measured bottleneck, benchmark an export queue or
`EXPORT_JOBS` separately from CPU placement.

Analyze an existing queue output root:

```bash
python scripts/analyze_9950x3d_production_queue.py \
  outputs/production_9950x3d_isaac_queue
```

Generated `outputs`, logs, CSVs, `.blend`, `.usd`, `.usdc`, profiles, zips,
and cache data are local run artifacts and should not be committed.

## Run 9950X3D Parallel Scene Benchmark

Use this for Ryzen 9 9950X3D scene-level throughput testing. Each seed runs in
its own independent Python-Blender process. This is not Python threading inside
one Blender / `bpy` process, and it does not modify Infinigen generation logic,
the solver, asset factories, proposal order, or the stable
`scripts/run_isaac_static_optimized_10room.sh` defaults.

Correct observed CCD / L3 groups on this 9950X3D:

```text
CCD0 / L3: 0-7,16-23
CCD1 / L3: 8-15,24-31
```

Do not use `0-15;16-31` as a CCD split.

Dry-run the default matrix:

```bash
DRY_RUN=1 \
BENCH_MODE=matrix \
SEEDS=10,11,12,13 \
TIMEOUT_SECONDS=300 \
bash scripts/run_9950x3d_parallel_scene_bench.sh
```

Run the bounded 1800s matrix:

```bash
CLEAN=1 \
BENCH_MODE=matrix \
SEEDS=10,11,12,13 \
TIMEOUT_SECONDS=1800 \
bash scripts/run_9950x3d_parallel_scene_bench.sh
```

Default matrix cases:

```text
JOBS=1 CPU_STRATEGY=none
JOBS=2 CPU_STRATEGY=split_llc
JOBS=2 CPU_STRATEGY=physical_cores_only
JOBS=4 CPU_STRATEGY=split_llc
JOBS=4 CPU_STRATEGY=physical_cores_only
```

The script first records topology under:

```text
outputs/bench_9950x3d_parallel_scenes/topology/cpu_topology.txt
outputs/bench_9950x3d_parallel_scenes/topology/cpu_topology.json
outputs/bench_9950x3d_parallel_scenes/topology/recommended_cpu_sets.md
```

It uses `lscpu -e=CPU,CORE,SOCKET,NODE,CACHE` to group logical CPUs by shared
last-level cache / likely CCD. It does not assume CPU `0-15` is a specific CCD.
If cache grouping is unavailable, it records the fallback reason and uses
continuous halves. Also check CPU governor / frequency state, temperature
(`sensors` or host monitoring), memory, swap, and I/O while comparing cases;
thermal throttling or swap pressure invalidates scenes/hour comparisons.

Supported CPU strategies:

```text
CPU_STRATEGY=none
CPU_STRATEGY=compact_llc
CPU_STRATEGY=split_llc
CPU_STRATEGY=physical_cores_only
CPU_STRATEGY=smt_pairs
CPU_STRATEGY=manual CPU_SETS="0-15;16-31"
```

Single-case example:

```bash
CLEAN=1 \
BENCH_MODE=single \
JOBS=2 \
CPU_STRATEGY=split_llc \
SEEDS=10,11,12,13 \
bash scripts/run_9950x3d_parallel_scene_bench.sh
```

Manual 4-way CCD split used in the 2026-06-22 bounded comparison:

```bash
CLEAN=1 \
BENCH_MODE=single \
CPU_STRATEGY=manual \
CPU_SETS="0-3,16-19;4-7,20-23;8-11,24-27;12-15,28-31" \
JOBS=4 \
SEEDS=10,11,12,13 \
TIMEOUT_SECONDS=1800 \
OUTPUT_ROOT=outputs/bench_9950x3d_manual_ccd4 \
bash scripts/run_9950x3d_parallel_scene_bench.sh
```

Manual JOBS=3 bounded interpolation:

```bash
CLEAN=1 \
BENCH_MODE=single \
CPU_STRATEGY=manual \
CPU_SETS="0-4,16-20;5-9,21-25;10-15,26-31" \
JOBS=3 \
SEEDS=10,11,12 \
TIMEOUT_SECONDS=1800 \
OUTPUT_ROOT=outputs/bench_9950x3d_manual_jobs3 \
bash scripts/run_9950x3d_parallel_scene_bench.sh
```

Manual JOBS=4 CCD split full-timeout coarse-only run:

```bash
CLEAN=1 \
BENCH_MODE=single \
CPU_STRATEGY=manual \
CPU_SETS="0-3,16-19;4-7,20-23;8-11,24-27;12-15,28-31" \
JOBS=4 \
SEEDS=20,21,22,23 \
TIMEOUT_SECONDS=14400 \
OUTPUT_ROOT=outputs/bench_9950x3d_manual_ccd4_fulltimeout \
bash scripts/run_9950x3d_parallel_scene_bench.sh
```

Current clean JOBS=4 CCD split candidate after the seed 21 material kwarg fix:

```bash
CLEAN=1 \
BENCH_MODE=single \
CPU_STRATEGY=manual \
CPU_SETS="0-3,16-19;4-7,20-23;8-11,24-27;12-15,28-31" \
JOBS=4 \
SEEDS=20,21,22,23 \
TIMEOUT_SECONDS=14400 \
OUTPUT_ROOT=outputs/bench_9950x3d_manual_ccd4_clean_after_seed21_fix \
bash scripts/run_9950x3d_parallel_scene_bench.sh
```

This clean rerun completed `4/4` coarse scenes with `failed=0`,
`timeout=0`, and `scenes/hour=1.825`. It did not enable Wheat reuse and did
not export USD. The current recommended 9950X3D CPU placement is:

```text
JOBS=4
CPU_SETS="0-3,16-19;4-7,20-23;8-11,24-27;12-15,28-31"
```

Manual 2-way physical-core-only comparison:

```bash
CLEAN=1 \
BENCH_MODE=single \
CPU_STRATEGY=manual \
CPU_SETS="0-7;8-15" \
JOBS=2 \
SEEDS=10,11 \
TIMEOUT_SECONDS=1800 \
OUTPUT_ROOT=outputs/bench_9950x3d_physical2 \
bash scripts/run_9950x3d_parallel_scene_bench.sh
```

Analyze an existing output root:

```bash
python scripts/analyze_9950x3d_parallel_scene_bench.py \
  outputs/bench_9950x3d_parallel_scenes
```

The benchmark enables the accepted Isaac static switches:

```text
INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1
INFINIGEN_REUSE_LARGESHELF_CHILD_NODEGROUPS=1
INFINIGEN_FAST_NATURE_TRINKET_STABLE_POSE=1
```

and uses:

```text
compose_indoors.terrain_enabled=False
home_room_constraints.has_fewer_rooms=False
restrict_solving.solve_max_rooms=10
populate_doors.door_chance=0
```

`INFINIGEN_REUSE_PLANT_TEMPLATE_GEOMETRY` is not enabled by default because the
Wheat reuse path has only passed a targeted benchmark so far. Use
`ENABLE_WHEAT_REUSE=1` only for explicit experiments.

USD export is off by default. When `EXPORT_USD=1`, export starts only after all
coarse generation for the case finishes, with `EXPORT_JOBS=1` by default:

```bash
EXPORT_USD=1 EXPORT_JOBS=1 \
bash scripts/run_9950x3d_parallel_scene_bench.sh
```

The clean full-timeout coarse-only result currently favors `JOBS=4` with the
manual 4-way CCD split. Do not jump straight to `JOBS=8`; the script requires
`ALLOW_JOBS8=1` for that. Keep `JOBS=5/6` for a separate scaling experiment,
not as the next default step.

## Run Optimized Isaac Static 10-Room

Use this as the standard full 10-room static indoor command after the latest
Isaac Sim manual visual check:

```bash
bash scripts/run_isaac_static_optimized_10room.sh
```

The default output is:

```text
outputs/isaac_static_optimized_seed0_10room/coarse
```

Run a different seed:

```bash
SEED=4 bash scripts/run_isaac_static_optimized_10room.sh
```

Use a specific Python interpreter:

```bash
PYTHON_BIN=/home/ubuntu22/miniconda3/envs/infinigen/bin/python \
SEED=4 \
bash scripts/run_isaac_static_optimized_10room.sh
```

Regenerate a seed from a clean coarse output folder:

```bash
CLEAN=1 SEED=4 bash scripts/run_isaac_static_optimized_10room.sh
```

Generate and export USDC for Isaac Sim:

```bash
EXPORT_USD=1 SEED=4 bash scripts/run_isaac_static_optimized_10room.sh
```

Override export resolution:

```bash
EXPORT_USD=1 EXPORT_RESOLUTION=256 SEED=4 \
bash scripts/run_isaac_static_optimized_10room.sh
```

Dry-run command expansion without generating or exporting:

```bash
DRY_RUN=1 EXPORT_USD=1 SEED=4 \
bash scripts/run_isaac_static_optimized_10room.sh
```

The script enables these opt-in switches by default:

```text
INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1
INFINIGEN_REUSE_LARGESHELF_CHILD_NODEGROUPS=1
INFINIGEN_FAST_NATURE_TRINKET_STABLE_POSE=1
```

and uses:

```text
compose_indoors.terrain_enabled=False
home_room_constraints.has_fewer_rooms=False
restrict_solving.solve_max_rooms=10
populate_doors.door_chance=0
```

When `EXPORT_USD=1`, the default export folder is:

```text
outputs/usd_compare/isaac_static_optimized_seed${SEED}_10room
```

Open the host path in Isaac Sim, not a container-only path. Keep the full
export directory together; do not move only a single `.usdc` file. If the
scene appears black, add a Dome Light or Point Light, and check material /
texture resolve warnings in Isaac Sim.

## Run Plant Asset Timing Benchmark

This benchmark is for `PlantContainerFactory` / `LargePlantContainerFactory`
investigation only. It does not run a full indoor scene and does not enable a
Plant optimization.

```bash
INFINIGEN_PROFILE_PLANT_ASSETS=1 \
python scripts/bench_plant_assets_factory.py \
  --samples 30 \
  --seed 0 \
  --output_folder outputs/bench_plant_assets_deep
```

Analyze:

```bash
python scripts/analyze_plant_assets_timing.py \
  outputs/bench_plant_assets_deep/infinigen_plant_assets_timing.csv
```

Optional factory selection:

```bash
INFINIGEN_PROFILE_PLANT_ASSETS=1 \
python scripts/bench_plant_assets_factory.py \
  --factory-class PlantContainerFactory \
  --samples 30 \
  --seed 0 \
  --output_folder outputs/bench_plant_assets
```

The latest deep `LargePlantContainerFactory` run showed
`plant_spawn_duration` as the dominant stage, with leaf / stem / branch
geometry costs far above material generation. Future Plant optimizations must
be opt-in, default-off, and quality-gated.

## Run Wheat Template Reuse A/B

This is a targeted microbenchmark for the opt-in Wheat-only Plant geometry
reuse experiment. It does not run a full indoor scene and does not change the
standard Isaac static script.

Baseline:

```bash
INFINIGEN_PROFILE_PLANT_ASSETS=1 \
python scripts/bench_plant_assets_factory.py \
  --samples 30 \
  --seed 0 \
  --concrete-plant-filter WheatMonocotFactory \
  --output_folder outputs/bench_wheat_template_reuse_ab/baseline
```

Candidate:

```bash
INFINIGEN_PROFILE_PLANT_ASSETS=1 \
INFINIGEN_REUSE_PLANT_TEMPLATE_GEOMETRY=1 \
python scripts/bench_plant_assets_factory.py \
  --samples 30 \
  --seed 0 \
  --concrete-plant-filter WheatMonocotFactory \
  --output_folder outputs/bench_wheat_template_reuse_ab/candidate_reuse
```

Analyze:

```bash
python scripts/analyze_plant_assets_timing.py \
  outputs/bench_wheat_template_reuse_ab/baseline/infinigen_plant_assets_timing.csv

python scripts/analyze_plant_assets_timing.py \
  outputs/bench_wheat_template_reuse_ab/candidate_reuse/infinigen_plant_assets_timing.csv
```

Visual check blend:

```text
outputs/bench_wheat_template_reuse_ab/visual_check_wheat/wheat_template_reuse_check.blend
```

Manual inspection must pass before considering a full 10-room quality
validation or expanding the experiment to `GrassesMonocotFactory`.

## Enter Container

```bash
docker exec -it infinigen bash
```

## Activate Conda

```bash
source /root/miniconda3/etc/profile.d/conda.sh
conda activate infinigen
cd /opt/infinigen
```

## Run Indoor Coarse Profile

```bash
bash scripts/profile_indoor_solver.sh
```

## Run Indoor Coarse Profile With Solver Timing

```bash
INFINIGEN_PROFILE_TIMING=1 bash scripts/profile_indoor_solver.sh
```

Timing CSV output:

```text
outputs/profile_indoor_baseline/coarse/indoor_solver_timing.csv
```

## Run Bounded Timing Sample

Use this when a full indoor coarse run is too slow:

```bash
INFINIGEN_PROFILE_TIMING=1 timeout 1800s bash scripts/profile_indoor_solver.sh
```

This preserves the normal room count, solve steps, object availability, and gin settings used by `scripts/profile_indoor_solver.sh`. A timeout sample is not a complete profile. Depending on how `timeout` terminates Python, `/tmp/indoors_coarse.prof` may not be written; use `indoor_solver_timing.csv` as the timing source for this workflow.

## Analyze Solver Timing CSV

Default path:

```bash
python scripts/analyze_indoor_timing.py
```

Explicit path:

```bash
python scripts/analyze_indoor_timing.py outputs/profile_indoor_baseline/coarse/indoor_solver_timing.csv
```

The script prints:

- `apply_duration` by `generator_class`
- Addition breakdowns by `generator_class`
- duration totals by `move_type`
- slowest proposal attempts
- failed proposal clusters
- C++ rewrite candidate guidance

## Compare Indoor Coarse Outputs

Use this for baseline versus candidate A/B validation:

```bash
python scripts/compare_indoor_outputs.py outputs/a/coarse outputs/b/coarse
```

With explicit tolerances and a larger diff budget:

```bash
python scripts/compare_indoor_outputs.py \
  --rtol 1e-6 \
  --atol 1e-6 \
  --max-diffs 50 \
  outputs/a/coarse \
  outputs/b/coarse
```

The script recursively pairs `.json` files by relative path, canonicalizes
obvious run-specific fields and output/temp paths, sorts known unordered tag
lists such as `tags`, `child_tags`, and `parent_tags`, reports missing/extra
files, prints per-file `SAME` or `DIFFERENT`, reports numeric `max_abs_diff`,
and ends with `PASS` or `FAIL`.

`NO_COMPARABLE_JSON_FOUND` is a failed validation, not a pass.

## View Profile Top 80

```bash
python scripts/print_indoor_profile.py -n 80
```

The default profile path is:

```text
/tmp/indoors_coarse.prof
```

## Build Standalone Geometry Kernels

The standalone Cython/C++ geometry kernels are optional. If the extension is
not compiled, `infinigen.core.constraints.cpp.geometry_kernels` falls back to
NumPy implementations.

```bash
python -m pip install -e .
```

Disable only the standalone geometry extension build:

```bash
INFINIGEN_DISABLE_GEOMETRY_CPP=True python -m pip install -e .
```

This leaves the NumPy fallback importable:

```bash
python - <<'PY'
from infinigen.core.constraints.cpp import geometry_kernels as g
print("C_EXTENSION_AVAILABLE=", g.C_EXTENSION_AVAILABLE)
PY
```

Run fast unit tests:

```bash
python -m pytest tests/test_geometry_kernels.py -q
```

Run the microbenchmark:

```bash
python scripts/bench_geometry_kernels.py
```

These commands do not run indoor generation and do not connect the kernels to
the solver. Before any future solver-facing opt-in integration, run a same
seed/gin/task A/B comparison with `scripts/compare_indoor_outputs.py`.

## Run BBox Mesh Timing

Enable fine-grained `bbox_mesh_from_hipoly` timing:

```bash
INFINIGEN_PROFILE_BBOX=1 bash scripts/profile_indoor_solver.sh
```

The existing solver timing flag also enables bbox timing:

```bash
INFINIGEN_PROFILE_TIMING=1 INFINIGEN_PROFILE_BBOX=1 bash scripts/profile_indoor_solver.sh
```

When the solver output folder is available, bbox timing is written to:

```text
<output_folder>/infinigen_bbox_timing.csv
```

Outside the solver path, the fallback path is:

```text
/tmp/infinigen_bbox_timing.csv
```

Analyze bbox timing:

```bash
python scripts/analyze_bbox_timing.py /tmp/infinigen_bbox_timing.csv
```

or point it at the run output:

```bash
python scripts/analyze_bbox_timing.py outputs/profile_indoor_baseline/coarse/infinigen_bbox_timing.csv
```

Use the `union_all_bbox_duration / total_duration` share from this script before
considering any opt-in C++ bbox integration.

## Run Asset Factory Spawn Timing

Enable fine-grained `AssetFactory.spawn_asset` timing:

```bash
INFINIGEN_PROFILE_ASSET_FACTORY=1 bash scripts/profile_indoor_solver.sh
```

The existing solver timing flag also enables asset factory timing:

```bash
INFINIGEN_PROFILE_TIMING=1 INFINIGEN_PROFILE_ASSET_FACTORY=1 bash scripts/profile_indoor_solver.sh
```

When the solver output folder is available, asset factory timing is written to:

```text
<output_folder>/infinigen_asset_factory_timing.csv
```

Outside the solver path, the fallback path is:

```text
/tmp/infinigen_asset_factory_timing.csv
```

Analyze asset factory timing:

```bash
python scripts/analyze_asset_factory_timing.py /tmp/infinigen_asset_factory_timing.csv
```

or point it at the run output:

```bash
python scripts/analyze_asset_factory_timing.py outputs/profile_indoor_baseline/coarse/infinigen_asset_factory_timing.csv
```

Fresh-folder bounded sample used for the 2026-06-19 asset factory timing run:

```bash
INFINIGEN_PROFILE_TIMING=1 INFINIGEN_PROFILE_BBOX=1 INFINIGEN_PROFILE_ASSET_FACTORY=1 timeout 600s python -m infinigen_examples.generate_indoors \
  --seed 0 \
  --task coarse \
  --output_folder outputs/profile_asset_factory_current/coarse \
  -g fast_solve.gin \
  -p compose_indoors.terrain_enabled=False \
     home_room_constraints.has_fewer_rooms=False \
     restrict_solving.solve_max_rooms=10
```

Use this timing to decide whether the next behavior-preserving experiment
should inspect `create_asset`, placeholder deletion, placeholder finalization,
or `GarbageCollect` context behavior.

## Run NatureShelfTrinkets Targeted Benchmark

Collect isolated `NatureShelfTrinketsFactory.create_asset()` timing without
running a full indoor scene:

```bash
INFINIGEN_PROFILE_NATURE_SHELF_TRINKETS=1 \
python scripts/bench_nature_shelf_trinkets_factory.py \
  --samples 100 \
  --seed 0 \
  --output_folder outputs/bench_nature_shelf_trinkets_100
```

Analyze:

```bash
python scripts/analyze_nature_shelf_trinkets.py \
  outputs/bench_nature_shelf_trinkets_100/infinigen_nature_shelf_trinkets_timing.csv
```

## Run NatureShelfTrinkets Fast Shell Stable Pose A/B

The opt-in fast shell stable-pose experiment is enabled only with:

```bash
INFINIGEN_FAST_NATURE_TRINKET_STABLE_POSE=1
```

The current experiment affects:

```text
ClamFactory
MusselFactory
ScallopFactory
ConchFactory
AugerFactory
VoluteFactory
MolluskFactory
```

Baseline shell-only benchmark:

```bash
INFINIGEN_PROFILE_NATURE_SHELF_TRINKETS=1 \
python scripts/bench_nature_shelf_trinkets_factory.py \
  --samples 100 \
  --seed 0 \
  --base-factory-filter ClamFactory,MusselFactory,ScallopFactory,ConchFactory,AugerFactory,VoluteFactory,MolluskFactory \
  --output_folder outputs/bench_nature_fast_pose_expanded_shell/baseline
```

Candidate shell-only benchmark:

```bash
INFINIGEN_PROFILE_NATURE_SHELF_TRINKETS=1 \
INFINIGEN_FAST_NATURE_TRINKET_STABLE_POSE=1 \
python scripts/bench_nature_shelf_trinkets_factory.py \
  --samples 100 \
  --seed 0 \
  --base-factory-filter ClamFactory,MusselFactory,ScallopFactory,ConchFactory,AugerFactory,VoluteFactory,MolluskFactory \
  --output_folder outputs/bench_nature_fast_pose_expanded_shell/candidate_fast
```

Compare the two CSVs:

```bash
python scripts/analyze_nature_shelf_trinkets.py \
  outputs/bench_nature_fast_pose_expanded_shell/baseline/infinigen_nature_shelf_trinkets_timing.csv \
  outputs/bench_nature_fast_pose_expanded_shell/candidate_fast/infinigen_nature_shelf_trinkets_timing.csv
```

Generate a small fast-mode visual check blend:

```bash
INFINIGEN_PROFILE_NATURE_SHELF_TRINKETS=1 \
INFINIGEN_FAST_NATURE_TRINKET_STABLE_POSE=1 \
python scripts/bench_nature_shelf_trinkets_factory.py \
  --samples 16 \
  --seed 1 \
  --base-factory-filter ClamFactory,MusselFactory,ScallopFactory,ConchFactory,AugerFactory,VoluteFactory,MolluskFactory \
  --keep-blend true \
  --output_folder outputs/bench_nature_fast_pose_expanded_shell/visual_check_fast
```

Open the generated blend manually and check for floating, inverted shells,
bad bottom alignment, support-surface intersection, or unacceptable visual
orientation. Do not enable the fast flag in a full run until this visual gate
passes.

The expanded shell-like A/B measured `153.955s -> 8.200s` with `0` failures.
Treat this as microbenchmark speed evidence only; it is not a full-scene
quality gate.

## Run BookStack Populate Timing

Enable BookStack / BookColumn timing:

```bash
INFINIGEN_PROFILE_BOOKSTACK=1
```

Run the targeted BookStack benchmark:

```bash
python scripts/bench_bookstack_factory.py \
  --samples 30 \
  --seed 0 \
  --output_folder outputs/bench_bookstack
```

Analyze:

```bash
python scripts/analyze_bookstack_timing.py \
  outputs/bench_bookstack/infinigen_bookstack_timing.csv
```

The benchmark is an isolated source-level timing probe. It is not a complete
indoor scene walltime result and does not optimize or reduce book clutter.

## Run Plant Asset Populate Timing

Enable plant asset timing:

```bash
INFINIGEN_PROFILE_PLANT_ASSETS=1
```

Run the targeted LargePlantContainer benchmark:

```bash
python scripts/bench_plant_assets_factory.py \
  --samples 20 \
  --seed 0 \
  --output_folder outputs/bench_plant_assets
```

Analyze:

```bash
python scripts/analyze_plant_assets_timing.py \
  outputs/bench_plant_assets/infinigen_plant_assets_timing.csv
```

This is only a microbenchmark for plant container internals. It does not
simplify plants or reduce scene complexity.

## Run Datablock Growth Attribution

Enable final-populate datablock growth attribution:

```bash
INFINIGEN_PROFILE_DATABLOCK_GROWTH=1
```

When final populate is reached, the CSV is written to:

```text
<output_folder>/infinigen_datablock_growth_timing.csv
```

Fallback:

```text
/tmp/infinigen_datablock_growth_timing.csv
```

Analyze:

```bash
python scripts/analyze_datablock_growth.py \
  outputs/<run>/coarse/infinigen_datablock_growth_timing.csv
```

Use this to identify which factories create the most materials, textures,
node groups, meshes, and images. Do not treat this instrumentation as a reuse
optimization.

The current recommended full-scene speed configuration remains:

```text
INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1
INFINIGEN_REUSE_LARGESHELF_CHILD_NODEGROUPS=1
INFINIGEN_FAST_NATURE_TRINKET_STABLE_POSE=1
restrict_solving.solve_max_rooms=10
populate_doors.door_chance=0
```

## Run GarbageCollect Target Timing

Enable target-level `garbage_collect` / `GarbageCollect` timing:

```bash
INFINIGEN_PROFILE_GC=1 bash scripts/profile_indoor_solver.sh
```

The existing solver timing flag also enables GC timing:

```bash
INFINIGEN_PROFILE_TIMING=1 INFINIGEN_PROFILE_GC=1 bash scripts/profile_indoor_solver.sh
```

When the solver output folder is available, GC timing is written to:

```text
<output_folder>/infinigen_gc_timing.csv
```

Outside the solver path, the fallback path is:

```text
/tmp/infinigen_gc_timing.csv
```

Analyze GC timing:

```bash
python scripts/analyze_gc_timing.py /tmp/infinigen_gc_timing.csv
```

or point it at the run output:

```bash
python scripts/analyze_gc_timing.py outputs/profile_gc_current/coarse/infinigen_gc_timing.csv
```

Fresh-folder bounded sample used for the 2026-06-19 GC target timing run:

```bash
INFINIGEN_PROFILE_TIMING=1 INFINIGEN_PROFILE_BBOX=1 INFINIGEN_PROFILE_ASSET_FACTORY=1 INFINIGEN_PROFILE_GC=1 timeout 600s python -m infinigen_examples.generate_indoors \
  --seed 0 \
  --task coarse \
  --output_folder outputs/profile_gc_current/coarse \
  -g fast_solve.gin \
  -p compose_indoors.terrain_enabled=False \
     home_room_constraints.has_fewer_rooms=False \
     restrict_solving.solve_max_rooms=10
```

Use this timing to decide whether GC cost is in enter snapshot, exit scan,
remove calls, or a specific `bpy.data` target. Current evidence points to
`bpy.data.node_groups` removal, not `create_asset`, placeholder delete,
`union_all_bbox`, or a C++ kernel candidate.

## Run GarbageCollect Attribution Timing

Use this when the question is which factory or node group name family causes
`bpy.data.node_groups` remove cost:

```bash
INFINIGEN_PROFILE_TIMING=1 INFINIGEN_PROFILE_GC=1 INFINIGEN_PROFILE_ASSET_FACTORY=1 timeout 600s python -m infinigen_examples.generate_indoors \
  --seed 0 \
  --task coarse \
  --output_folder outputs/profile_gc_attribution/coarse \
  -g fast_solve.gin \
  -p compose_indoors.terrain_enabled=False \
     home_room_constraints.has_fewer_rooms=False \
     restrict_solving.solve_max_rooms=10
```

Analyze the resulting CSV:

```bash
python scripts/analyze_gc_timing.py \
  outputs/profile_gc_attribution/coarse/infinigen_gc_timing.csv
```

The analyzer reports:

- `node_groups` remove duration by `generator_class`
- `node_groups` removed count by `generator_class`
- removed node group name prefix totals
- slowest `node_groups` remove rows with `context_id`, `generator_class`,
  remove counts, target sizes, top prefixes, and name samples

Current sample output:

```text
outputs/profile_gc_attribution/coarse/infinigen_gc_timing.csv
```

The 2026-06-19 attribution sample produced 4,741 CSV lines including the
header. `node_groups` remove duration was 185.030s. The top factory was
`LargeShelfFactory` with 139.219s and 5,661 removed node groups. Top repeated
prefixes were `nodegroup_tagged_cube`, `nodegroup_division_board`, and
`nodegroup_screw_head`.

Use this attribution before designing an optimization. If a few factories or
prefixes dominate, inspect those factories' `create_asset` and node tree
generation first. Prefer precise reuse, caching, or reducing repeated node
group creation over broad deferred cleanup. Any optimization must remain
opt-in until same seed/gin/task A/B passes.

## Run LargeShelf Node Group Timing

Enable `LargeShelfFactory` shelf node group creation timing:

```bash
INFINIGEN_PROFILE_SHELF_NODEGROUPS=1 python -m infinigen_examples.generate_indoors \
  --seed 0 \
  --task coarse \
  --output_folder outputs/profile_shelf_nodegroups_seed0/coarse \
  -g fast_solve.gin \
  -p compose_indoors.terrain_enabled=False \
     home_room_constraints.has_fewer_rooms=False \
     restrict_solving.solve_max_rooms=10 \
     populate_doors.door_chance=0
```

The timing CSV is written under the solver output folder when available:

```text
<output_folder>/infinigen_shelf_nodegroup_timing.csv
```

Analyze it with:

```bash
python scripts/analyze_shelf_nodegroups.py \
  outputs/profile_shelf_nodegroups_seed0/coarse/infinigen_shelf_nodegroup_timing.csv
```

The analyzer reports prefix call counts, total and mean duration, per-spawn
node group counts, repeated-template signals, and, when present, reuse cache
hits and misses.

## Run LargeShelf Child Reuse Short A/B

The first `LargeShelfFactory` child node group reuse experiment is opt-in.
Default behavior is unchanged unless this variable is set:

```bash
INFINIGEN_REUSE_LARGESHELF_CHILD_NODEGROUPS=1
```

The first reuse set is limited to:

```text
nodegroup_screw_head
nodegroup_side_board
nodegroup_bottom_board
nodegroup_back_board
```

Do not use this switch to imply that top-level `geometry_nodes`,
`nodegroup_division_board`, or `nodegroup_tagged_cube` are reused. Those stay
uncached because of per-object material/array defaults and tag attribute risk.

Baseline short timing sample:

```bash
INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1 \
INFINIGEN_PROFILE_SHELF_NODEGROUPS=1 \
timeout 900s python -m infinigen_examples.generate_indoors \
  --seed 0 \
  --task coarse \
  --output_folder outputs/profile_shelf_reuse_ab/baseline/coarse \
  -g fast_solve.gin \
  -p compose_indoors.terrain_enabled=False \
     home_room_constraints.has_fewer_rooms=False \
     restrict_solving.solve_max_rooms=10 \
     populate_doors.door_chance=0
```

Candidate short timing sample:

```bash
INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1 \
INFINIGEN_REUSE_LARGESHELF_CHILD_NODEGROUPS=1 \
INFINIGEN_PROFILE_SHELF_NODEGROUPS=1 \
timeout 900s python -m infinigen_examples.generate_indoors \
  --seed 0 \
  --task coarse \
  --output_folder outputs/profile_shelf_reuse_ab/candidate/coarse \
  -g fast_solve.gin \
  -p compose_indoors.terrain_enabled=False \
     home_room_constraints.has_fewer_rooms=False \
     restrict_solving.solve_max_rooms=10 \
     populate_doors.door_chance=0
```

Analyze both CSVs:

```bash
python scripts/analyze_shelf_nodegroups.py \
  outputs/profile_shelf_reuse_ab/baseline/coarse/infinigen_shelf_nodegroup_timing.csv

python scripts/analyze_shelf_nodegroups.py \
  outputs/profile_shelf_reuse_ab/candidate/coarse/infinigen_shelf_nodegroup_timing.csv
```

The 2026-06-21 short A/B timed out on both sides at 900s, as intended for a
bounded sample. Both CSVs had 5,918 data rows and 163 `LargeShelfFactory`
spawns. Candidate cache hit rate was 96.744%, actual node groups created
dropped from 5,918 to 3,363, and target-prefix duration dropped from 21.417s
to 0.538s. Treat this as timing evidence only, not as a quality gate.

Next quality validation should keep:

```text
INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1
INFINIGEN_REUSE_LARGESHELF_CHILD_NODEGROUPS=1
restrict_solving.solve_max_rooms=10
populate_doors.door_chance=0
```

Do not run concurrent generation for this validation. Do not commit generated
outputs, CSVs, `.blend`, `.usd`, `.usdc`, `.zip`, or `.prof` files.

## Run Node Group Batch Remove Equivalence A/B

The node group batch remove path is an opt-in single-scene experiment. Default
behavior is unchanged unless this variable is explicitly set for the candidate:

```text
INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1
```

Run the full same seed/gin/task 10-room A/B without heavy timing
instrumentation:

```bash
EXPERIMENT_TIMEOUT_SECONDS=14400 \
bash scripts/run_gc_batch_remove_equivalence.sh
```

On the host, if the active `python` does not have `bpy`, point the script at
the Infinigen conda interpreter:

```bash
PYTHON_BIN=/home/ubuntu22/miniconda3/envs/infinigen/bin/python \
EXPERIMENT_TIMEOUT_SECONDS=14400 \
bash scripts/run_gc_batch_remove_equivalence.sh
```

The script runs:

- baseline without `INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS`:
  `outputs/gc_batch_remove_equiv/baseline/coarse`
- candidate with `INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1`:
  `outputs/gc_batch_remove_equiv/candidate_batch/coarse`

Both use seed `0`, task `coarse`, `fast_solve.gin`, and these overrides:

```text
compose_indoors.terrain_enabled=False
home_room_constraints.has_fewer_rooms=False
restrict_solving.solve_max_rooms=10
```

The script explicitly unsets:

```text
INFINIGEN_PROFILE_TIMING
INFINIGEN_PROFILE_GC
INFINIGEN_PROFILE_ASSET_FACTORY
INFINIGEN_PROFILE_BBOX
```

After generation, it runs:

```bash
python scripts/compare_indoor_outputs.py \
  outputs/gc_batch_remove_equiv/baseline/coarse \
  outputs/gc_batch_remove_equiv/candidate_batch/coarse
```

`EXPERIMENT_TIMEOUT_SECONDS` defaults to `14400`. Set it to `0` or an empty
string to disable `timeout`. If either side times out or the compare prints
`NO_COMPARABLE_JSON_FOUND`, the script reports that this is not a complete A/B
and cannot be used as mainline evidence.

Smoke mode:

```bash
EXPERIMENT_SMOKE_SINGLE_ROOM=1 \
EXPERIMENT_TIMEOUT_SECONDS=3600 \
bash scripts/run_gc_batch_remove_equivalence.sh
```

Smoke mode adds `singleroom.gin`, sets
`home_room_constraints.has_fewer_rooms=True`, and sets
`restrict_solving.solve_max_rooms=1`. A single-room PASS validates only the
script and obvious equivalence. It does not prove the 10-room mainline target.

2026-06-19 single-room smoke result: both new scripts completed and
`compare_indoor_outputs.py` printed `FINAL: PASS` with two comparable JSON
files. The wall-clock smoke was effectively flat, baseline `163.339s` versus
candidate `163.462s` (`0.999x`), with no traceback, OOM, kill, or segmentation
fault observed. Treat this as harness validation only.

## Run Node Group Batch Remove Wall-Clock A/B

Run the same baseline and candidate without heavy timing, recording wall time
and max RSS:

```bash
EXPERIMENT_TIMEOUT_SECONDS=14400 \
bash scripts/run_gc_batch_remove_walltime.sh
```

Host conda example:

```bash
PYTHON_BIN=/home/ubuntu22/miniconda3/envs/infinigen/bin/python \
EXPERIMENT_TIMEOUT_SECONDS=14400 \
bash scripts/run_gc_batch_remove_walltime.sh
```

The script writes:

```text
outputs/gc_batch_remove_walltime/summary.txt
outputs/gc_batch_remove_walltime/baseline.time.txt
outputs/gc_batch_remove_walltime/candidate_batch.time.txt
outputs/gc_batch_remove_walltime/compare.log
```

It records:

- baseline and candidate exit code
- shell-measured wall time
- `/usr/bin/time -v` max RSS when available
- `compare_indoor_outputs.py` result
- explicit timeout or `NO_COMPARABLE_JSON_FOUND` warnings

Smoke mode is available with:

```bash
EXPERIMENT_SMOKE_SINGLE_ROOM=1 \
EXPERIMENT_TIMEOUT_SECONDS=3600 \
bash scripts/run_gc_batch_remove_walltime.sh
```

Treat wall-clock speedup as accepted evidence only when both 10-room runs
complete and `compare_indoor_outputs.py` prints `FINAL: PASS`.

## Run Node Group Batch Remove Profiling Experiment

This older script is for GC/profile timing attribution, not no-instrumentation
wall-clock validation. It enables heavy timing and writes GC CSVs.

Run the sequential baseline and candidate profiling smoke:

```bash
EXPERIMENT_TIMEOUT_SECONDS=1200 bash scripts/run_gc_batch_remove_experiment.sh
```

On the host, if the active `python` does not have `bpy`, point the script at
the Infinigen conda interpreter:

```bash
PYTHON_BIN=/home/ubuntu22/miniconda3/envs/infinigen/bin/python \
EXPERIMENT_TIMEOUT_SECONDS=1200 \
bash scripts/run_gc_batch_remove_experiment.sh
```

The script runs:

- baseline without `INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS`:
  `outputs/gc_batch_remove_ab/baseline/coarse`
- candidate with `INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1`:
  `outputs/gc_batch_remove_ab/candidate_batch/coarse`

Both use seed `0`, task `coarse`, `fast_solve.gin`, and these overrides:

```text
compose_indoors.terrain_enabled=False
home_room_constraints.has_fewer_rooms=False
restrict_solving.solve_max_rooms=10
```

Both enable:

```text
INFINIGEN_PROFILE_TIMING=1
INFINIGEN_PROFILE_GC=1
INFINIGEN_PROFILE_ASSET_FACTORY=1
```

After generation, the script runs:

```bash
python scripts/compare_indoor_outputs.py \
  outputs/gc_batch_remove_ab/baseline/coarse \
  outputs/gc_batch_remove_ab/candidate_batch/coarse
```

If either side times out, the output is only a smoke/profile sample, not a
complete A/B equivalence result. If the compare prints
`NO_COMPARABLE_JSON_FOUND`, the candidate must not be mainlined.

Analyze the GC timing files:

```bash
python scripts/analyze_gc_timing.py \
  outputs/gc_batch_remove_ab/baseline/coarse/infinigen_gc_timing.csv

python scripts/analyze_gc_timing.py \
  outputs/gc_batch_remove_ab/candidate_batch/coarse/infinigen_gc_timing.csv
```

The 2026-06-19 smoke timed out on both sides and produced no comparable JSON.
It still showed a strong timing signal: baseline partial `node_groups`
remove_duration was 366.131s, while the candidate partial was 46.350s with
15,758 node groups removed via `batch_remove`. Treat that as profiling evidence
only until a complete same seed/gin/task A/B passes.

Do not use this script for concurrent generation or throughput benchmarking.
Do not change `manage_jobs.num_concurrent` for this experiment.

## Run Node Group GC Throttling A/B Experiment

The node group cleanup throttle is an opt-in experiment. Default behavior is
unchanged when `INFINIGEN_GC_NODE_GROUP_INTERVAL` is unset or set to `1`.

The interval=20 smoke on 2026-06-19 is not a valid speedup. Both runs timed
out, no comparable JSON was produced, and raw `node_groups_remove` increased
from 369.071s to 443.414s because deferred cleanup produced large burst
removes. Do not continue by simply increasing this interval.

Run the scripted baseline and candidate comparison:

```bash
EXPERIMENT_TIMEOUT_SECONDS=1200 bash scripts/run_gc_node_group_experiment.sh
```

On the host, if the active `python` does not have `bpy`, point the script at
the Infinigen conda interpreter:

```bash
PYTHON_BIN=/home/ubuntu22/miniconda3/envs/infinigen/bin/python \
EXPERIMENT_TIMEOUT_SECONDS=1200 \
bash scripts/run_gc_node_group_experiment.sh
```

The script runs:

- baseline with `INFINIGEN_GC_NODE_GROUP_INTERVAL=1`:
  `outputs/gc_node_group_ab/baseline/coarse`
- candidate with `INFINIGEN_GC_NODE_GROUP_INTERVAL=20`:
  `outputs/gc_node_group_ab/candidate_interval20/coarse`

Both use seed `0`, task `coarse`, `fast_solve.gin`, and these overrides:

```text
compose_indoors.terrain_enabled=False
home_room_constraints.has_fewer_rooms=False
restrict_solving.solve_max_rooms=10
```

Both enable:

```text
INFINIGEN_PROFILE_TIMING=1
INFINIGEN_PROFILE_GC=1
INFINIGEN_PROFILE_ASSET_FACTORY=1
```

After generation, the script runs:

```bash
python scripts/compare_indoor_outputs.py \
  outputs/gc_node_group_ab/baseline/coarse \
  outputs/gc_node_group_ab/candidate_interval20/coarse
```

If either side times out, the output is only a smoke/profile sample, not a
complete A/B equivalence result.

Analyze the GC timing files:

```bash
python scripts/analyze_gc_timing.py \
  outputs/gc_node_group_ab/baseline/coarse/infinigen_gc_timing.csv

python scripts/analyze_gc_timing.py \
  outputs/gc_node_group_ab/candidate_interval20/coarse/infinigen_gc_timing.csv
```

The analyzer reports interval values, skipped and executed node group cleanup
counts, node group duration and remove duration totals, an estimated saved-time
signal, and the maximum observed `node_groups` datablock count.

## Single-Room Coarse Generation

Single-room generation is useful only as a smoke test for scripts and workflow.
It is not evidence that reducing room count is a valid speed optimization.

```bash
python -m infinigen_examples.generate_indoors \
  --seed 0 \
  --task coarse \
  --output_folder outputs/single_room/coarse \
  -g fast_solve.gin \
  -p compose_indoors.terrain_enabled=False \
     home_room_constraints.has_fewer_rooms=True \
     restrict_single_supported_roomtype=True \
     restrict_solving.solve_max_rooms=1
```

## Smoke A/B Comparator Check

Use the same seed, same gin files, same task, and same parameter overrides for
both folders:

```bash
python -m infinigen_examples.generate_indoors \
  --seed 0 \
  --task coarse \
  --output_folder outputs/ab_smoke_a/coarse \
  -g fast_solve.gin \
  -p compose_indoors.terrain_enabled=False \
     home_room_constraints.has_fewer_rooms=True \
     restrict_single_supported_roomtype=True \
     restrict_solving.solve_max_rooms=1

python -m infinigen_examples.generate_indoors \
  --seed 0 \
  --task coarse \
  --output_folder outputs/ab_smoke_b/coarse \
  -g fast_solve.gin \
  -p compose_indoors.terrain_enabled=False \
     home_room_constraints.has_fewer_rooms=True \
     restrict_single_supported_roomtype=True \
     restrict_solving.solve_max_rooms=1

python scripts/compare_indoor_outputs.py \
  outputs/ab_smoke_a/coarse \
  outputs/ab_smoke_b/coarse
```

Do not use this reduced single-room smoke command as the main performance
target. Full indoor coarse A/B must keep the normal room count and solve steps.

## Single-Room USDC Export

Generate or reuse a coarse output folder, then export:

```bash
python -m infinigen.tools.export \
  --input_folder outputs/single_room/coarse \
  --output_folder outputs/single_room/usdc \
  --format usdc \
  --omniverse
```

## Find USD/USDC/USDA Files

```bash
find outputs -type f \( -name '*.usd' -o -name '*.usdc' -o -name '*.usda' \)
```

## Isaac Sim Import Notes

Use the host path when importing into Isaac Sim. Do not copy only a single `.usdc` file if the export produced related assets, textures, or sidecar files; keep the exported folder structure together.
