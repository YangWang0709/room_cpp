# Next Steps

## 9950X3D Production Scene Queue

Do not continue CPU parallel strategy tuning as the next step. The current
clean candidate is the validated 9950X3D `JOBS=4` CCD split:

```text
JOBS=4
CPU_SETS="0-3,16-19;4-7,20-23;8-11,24-27;12-15,28-31"
```

The correct observed CCD / L3 groups remain:

```text
CCD0 / L3: 0-7,16-23
CCD1 / L3: 8-15,24-31
```

`0-15;16-31` is not a CCD split and must not be used as the default. Do not
test `JOBS=5/6/8` in this line unless starting an explicit scaling experiment.

The next operational path is:

```text
scripts/run_9950x3d_production_scene_queue.sh
```

Each worker keeps a fixed CPU set and serially runs:

```text
coarse -> export USD/USDC -> next seed
```

This remains scene-level multiprocessing. Each seed is an independent
Python-Blender process, not multiple Python threads inside one Blender process.
The queue does not change the solver, asset factories, proposal order,
accept/reject behavior, or the default behavior of
`scripts/run_isaac_static_optimized_10room.sh`.

The production queue defaults to the stable Isaac static speed flags:

```text
INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1
INFINIGEN_REUSE_LARGESHELF_CHILD_NODEGROUPS=1
INFINIGEN_FAST_NATURE_TRINKET_STABLE_POSE=1
compose_indoors.terrain_enabled=False
home_room_constraints.has_fewer_rooms=False
restrict_solving.solve_max_rooms=10
populate_doors.door_chance=0
```

Wheat reuse remains default-off. Only `ENABLE_WHEAT_REUSE=1` should set
`INFINIGEN_REUSE_PLANT_TEMPLATE_GEOMETRY=1`; it is not accepted as a stable
full 10-room default yet.

Export runs inside each worker after that worker finishes coarse generation
for the seed. It does not add separate global export concurrency on top of
coarse generation. If export becomes the bottleneck, benchmark an export queue
or `EXPORT_JOBS` separately.

Use the dry-run before real batches:

```bash
DRY_RUN=1 \
SEEDS=100,101,102,103,104,105,106,107 \
JOBS=4 \
EXPORT_AFTER_GENERATE=1 \
bash scripts/run_9950x3d_production_scene_queue.sh
```

Summaries are written to:

```text
outputs/production_9950x3d_isaac_queue/summary.csv
outputs/production_9950x3d_isaac_queue/summary.md
```

Do not commit generated `outputs`, logs, CSVs, `.blend`, `.usd`, `.usdc`,
profiles, zips, or cache directories.

## 9950X3D Parallel Scene Benchmark

Current priority is a Ryzen 9 9950X3D-specific throughput benchmark for
multiple indoor 10-room coarse scenes. This is scene-level multiprocessing:
one seed, one scene, one independent Python-Blender process. Do not add Python
threads inside a single Blender / `bpy` process, do not change the solver, and
do not change asset factories or proposal / accept / reject behavior.

The correct observed CCD / L3 groups for this machine are:

```text
CCD0 / L3: 0-7,16-23
CCD1 / L3: 8-15,24-31
```

Do not use `0-15;16-31` as a CCD split; that separates SMT siblings, not L3
groups.

Latest follow-up:

```text
JOBS=3 bounded:
  CPU_SETS=0-4,16-20;5-9,21-25;10-15,26-31
  SEEDS=10,11,12 TIMEOUT_SECONDS=1800
  complete=0 timeout=3 failed=0 fatal=0 progress_score=302082 max_rss_kb=3306032

JOBS=4 CCD split full-timeout before seed21 fix:
  CPU_SETS=0-3,16-19;4-7,20-23;8-11,24-27;12-15,28-31
  SEEDS=20,21,22,23 TIMEOUT_SECONDS=14400
  complete=3 timeout=0 failed=1 scenes/hour=1.378 max_rss_kb=11260204

JOBS=4 CCD split clean rerun after seed21 fix:
  CPU_SETS=0-3,16-19;4-7,20-23;8-11,24-27;12-15,28-31
  SEEDS=20,21,22,23 TIMEOUT_SECONDS=14400
  complete=4 timeout=0 failed=0 scenes/hour=1.825 max_rss_kb=11183508
```

Seed 21's failure was a room material kwarg compatibility issue:
`room_walls()` passed `vertical/alternating/shape` to a wall material
generator that resolved to `ceramic.Concrete`, while `Concrete.generate()` did
not accept `vertical`. `call_material_generator()` now filters kwargs using
`inspect.signature()`, and seed 21 passed both standalone validation and the
clean 4-way rerun.

Current 9950X3D recommendation: use `JOBS=4` with the 4-way CCD split as the
multi-scene coarse generation candidate default. The clean rerun had no
timeout, no failed scenes, no Traceback, no killed/OOM marker, and no swap use.
The analyzer's `fatal=4` is from small Blender `Not freed memory blocks`
shutdown messages in otherwise complete logs and is treated as a false-positive
fatal marker for this benchmark. Keep `TIMEOUT_SECONDS=14400` for comparable
full-timeout runs. Do not test JOBS=5/6 next unless doing an explicit scaling
experiment. It is reasonable to move to fullopt_wheat quality validation as a
separate opt-in line. Keep `EXPORT_USD` / `EXPORT_JOBS` for a separate export
benchmark.

Latest bounded comparison:

```text
2-way CCD:          JOBS=2 CPU_SETS=0-7,16-23;8-15,24-31
4-way CCD split:    JOBS=4 CPU_SETS=0-3,16-19;4-7,20-23;8-11,24-27;12-15,28-31
2-way physical-only JOBS=2 CPU_SETS=0-7;8-15
```

All three 1800s cases timed out in solve with `complete=0`, `failed=0`,
`fatal=0`, no Traceback/killed/OOM marker, and no swap. `scenes/hour` is
therefore tied at zero. The bounded progress scores were `200849` for 2-way
CCD, `403039` for 4-way CCD split, and `200878` for 2-way physical-only. Max
RSS stayed modest: `2818032 KB`, `3015204 KB`, and `3122024 KB`.

Current recommendation: use the 4-way CCD split for 9950X3D multi-scene
coarse throughput. Do not enable `EXPORT_USD` in this benchmark line; measure
export separately after coarse-only throughput is stable.

Useful dry-run:

```bash
DRY_RUN=1 BENCH_MODE=matrix SEEDS=10,11,12,13 TIMEOUT_SECONDS=300 \
bash scripts/run_9950x3d_parallel_scene_bench.sh
```

Then run the bounded comparison:

```bash
CLEAN=1 BENCH_MODE=matrix SEEDS=10,11,12,13 TIMEOUT_SECONDS=1800 \
bash scripts/run_9950x3d_parallel_scene_bench.sh
```

The script records CPU topology first and derives CPU sets from
`lscpu -e=CPU,CORE,SOCKET,NODE,CACHE`. Do not hard-code a CCD assumption such
as "CPU 0-15 is CCD0"; use the cache grouping output in
`topology/recommended_cpu_sets.md`. During real runs, watch CPU governor /
frequency state, temperatures, memory, swap, and I/O; a faster-looking case is
not acceptable if it reaches thermal throttling, swap, OOM, or storage stalls.

Default matrix:

```text
JOBS=1 CPU_STRATEGY=none
JOBS=2 CPU_STRATEGY=split_llc
JOBS=2 CPU_STRATEGY=physical_cores_only
JOBS=4 CPU_STRATEGY=split_llc
JOBS=4 CPU_STRATEGY=physical_cores_only
```

The clean full-timeout coarse-only result selects `JOBS=4` for the immediate
9950X3D candidate default. Do not jump straight to `JOBS=8`. USD export
remains `EXPORT_JOBS=1` by default and should happen after coarse generation,
not concurrently with generation, until export is measured as a bottleneck.

`INFINIGEN_REUSE_PLANT_TEMPLATE_GEOMETRY=1` is not part of the stable default
full 10-room configuration yet; enable it only with `ENABLE_WHEAT_REUSE=1` for
explicit experiments. The optimization target is maximum `scenes/hour` with
zero failures, no swap/OOM pressure, and no Isaac visual quality regression.

## Current Isaac Static Recommendation

The latest recommended full 10-room Isaac Sim static indoor configuration is:

```text
INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1
INFINIGEN_REUSE_LARGESHELF_CHILD_NODEGROUPS=1
INFINIGEN_FAST_NATURE_TRINKET_STABLE_POSE=1
compose_indoors.terrain_enabled=False
home_room_constraints.has_fewer_rooms=False
restrict_solving.solve_max_rooms=10
populate_doors.door_chance=0
```

This configuration has been manually inspected in Isaac Sim after USD/USDC
export. The visual result was good, with no obvious quality problem. Treat this
as an Isaac static scene quality-preserving target, not a bitwise-identical
target.

Standard command:

```bash
bash scripts/run_isaac_static_optimized_10room.sh
```

Useful variants:

```bash
SEED=4 bash scripts/run_isaac_static_optimized_10room.sh
EXPORT_USD=1 SEED=4 bash scripts/run_isaac_static_optimized_10room.sh
DRY_RUN=1 EXPORT_USD=1 SEED=4 bash scripts/run_isaac_static_optimized_10room.sh
```

For Isaac Sim, open the host export directory and keep the full export folder
together. Do not move only one `.usdc` file. If the scene appears black, add a
Dome Light or Point Light and inspect material or texture resolve warnings.

The stable single-scene command remains the quality-preserving baseline. The
current throughput work is separate and uses scene-level multiprocessing in
`scripts/run_9950x3d_parallel_scene_bench.sh`; it does not change this stable
script's default behavior. Do not reduce room count or clutter complexity
unless a later quality gate explicitly allows it.

## Plant Candidate Bottleneck

The current Plant investigation is timing-only. The stable script
`scripts/run_isaac_static_optimized_10room.sh` must stay unchanged unless a
future quality gate explicitly accepts a new opt-in Plant switch.

Latest targeted run:

```bash
INFINIGEN_PROFILE_PLANT_ASSETS=1 \
python scripts/bench_plant_assets_factory.py \
  --samples 50 \
  --seed 0 \
  --output_folder outputs/bench_plant_assets_concrete_deep
python scripts/analyze_plant_assets_timing.py \
  outputs/bench_plant_assets_concrete_deep/infinigen_plant_assets_timing.csv
```

Summary: `50/50` samples succeeded, total measured duration was `214.538s`,
average `4.291s`, max `13.230s`. `plant_spawn_duration` was `170.618s`
(`79.5%`). The measured concrete monocot leaf / stem / branch substages were
the dominant internal cost, while material generation was only `0.991s`.

Current Plant experiment:

```bash
INFINIGEN_REUSE_PLANT_TEMPLATE_GEOMETRY=1
```

Keep it default-off, narrow, and quality-gated. The implemented v1 affects
only `WheatMonocotFactory` raw mesh templates. It does not affect
`GrassesMonocotFactory`, `VeratrumMonocotFactory`, `AgaveMonocotFactory`,
`MaizeMonocotFactory`, or other Plant factories. Do not reduce plant count,
leaf count, stem count, or general plant complexity. Do not use concurrency or
C++.

Wheat-only A/B result: `30/30` baseline and candidate samples succeeded.
Measured total duration improved `229.654s -> 144.198s`; cache hit rate was
`65.909%`; fallback count was `0`.

Next gate:

```text
outputs/bench_wheat_template_reuse_ab/visual_check_wheat/wheat_template_reuse_check.blend
```

Manually inspect for copied Wheat appearance, abnormal leaves/stems/ears,
flying objects, scaling errors, and severe intersections. If Wheat looks OK,
consider a full 10-room quality validation with the Plant switch. Only after
that should `GrassesMonocotFactory` be considered as the second reuse
candidate. Do not start with `VeratrumMonocotFactory` or
`AgaveMonocotFactory` because their branch systems and leaf deformation carry
higher visual-randomness risk.

## Current Populate Multi-Track Status

The current accepted main speed configuration remains:

```text
INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1
INFINIGEN_REUSE_LARGESHELF_CHILD_NODEGROUPS=1
INFINIGEN_FAST_NATURE_TRINKET_STABLE_POSE=1
restrict_solving.solve_max_rooms=10
populate_doors.door_chance=0
```

P0/P1/P2/P3 are now separate populate-stage lines:

- P0: opt-in `NatureShelfTrinketsFactory` fast stable-pose experiment.
- P1: `BookStackFactory` / `BookColumnFactory` source investigation and
  timing.
- P2: `LargePlantContainerFactory` / plant asset source investigation and
  timing.
- P3: integrated final-populate datablock growth attribution.

Only P0 is a speed experiment. P1/P2/P3 are investigation and timing only.
None of the new switches are enabled by default. Do not reduce clutter count,
do not run concurrent optimization, and do not run a full 10-room quality
validation until the relevant microbench and visual evidence is clear.

P0 now supports the expanded shell-like allow-list behind:

```bash
INFINIGEN_FAST_NATURE_TRINKET_STABLE_POSE=1
```

Supported:

```text
ClamFactory
MusselFactory
ScallopFactory
ConchFactory
AugerFactory
VoluteFactory
MolluskFactory
```

Still excluded:

```text
CoralFactory
HerbivoreFactory
CarnivoreFactory
PineconeFactory
BlenderRockFactory
BoulderFactory
```

Expanded shell-like 100-sample A/B completed with `0` failures and total
duration `153.955s -> 8.200s` (`18.8x`). Mesh and object creation counts were
unchanged. Before any full 10-room Isaac quality validation, manually inspect:

```text
outputs/bench_nature_fast_pose_expanded_shell/visual_check_fast/nature_shelf_trinkets_bench.blend
```

Look for floating, inverted shells, bad bottom alignment, support-surface
intersection, or unacceptable orientation loss.

P1 BookStack timing is available with:

```bash
INFINIGEN_PROFILE_BOOKSTACK=1
python scripts/bench_bookstack_factory.py --samples 30 --seed 0 \
  --output_folder outputs/bench_bookstack
python scripts/analyze_bookstack_timing.py \
  outputs/bench_bookstack/infinigen_bookstack_timing.csv
```

The first 30-sample run had `0` failures. Create-asset timing showed repeated
BookFactory geometry/material/nodegroup creation, while stdout showed
`findfont` warnings from `BookFactory` initialization. If BookStack remains a
priority, the next step is init-time font/Text material attribution before any
opt-in material or font cache.

P2 plant timing is available with:

```bash
INFINIGEN_PROFILE_PLANT_ASSETS=1
python scripts/bench_plant_assets_factory.py --samples 50 --seed 0 \
  --output_folder outputs/bench_plant_assets_concrete_deep
python scripts/analyze_plant_assets_timing.py \
  outputs/bench_plant_assets_concrete_deep/infinigen_plant_assets_timing.csv
```

The latest 50-sample `LargePlantContainerFactory` run had `0` failures and
measured `214.538s` total. The largest measured stages were
`geometry_duration` (`192.574s`) and `plant_spawn_duration` (`170.618s`).
Leaf / stem / branch geometry accounted for `87.873s`, `28.268s`, and
`31.567s` respectively. Material generation was only `0.991s`, so Plant
material reuse is not the first priority.

Recommended next Plant experiment, if continuing this line:

```bash
INFINIGEN_REUSE_PLANT_TEMPLATE_GEOMETRY=1
```

Do not implement this broadly. Start with a narrow, default-off
`WheatMonocotFactory` template experiment; `GrassesMonocotFactory` is the
second candidate. Do not start with `VeratrumMonocotFactory` or
`AgaveMonocotFactory`; their branch systems and leaf deformation are higher
visual-risk sources of random variation. Any Plant reuse must pass Blender /
Isaac visual checks and must not make plants look copied or reduce plant
complexity.

P3 datablock growth attribution is ready for a future integrated sample:

```bash
INFINIGEN_PROFILE_DATABLOCK_GROWTH=1
python scripts/analyze_datablock_growth.py \
  outputs/<run>/coarse/infinigen_datablock_growth_timing.csv
```

Do not hard-run a full 10-room 4-hour job just for P3. If integrated evidence
is required, use the bounded 1800s current recommended configuration, and if
it does not reach final `populate_assets`, record that and rely on targeted
benchmarks until the next planned full quality run.

## Latest Populate Clutter Focus

The current Isaac-inspected speed configuration is:

```text
INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1
INFINIGEN_REUSE_LARGESHELF_CHILD_NODEGROUPS=1
INFINIGEN_FAST_NATURE_TRINKET_STABLE_POSE=1
restrict_solving.solve_max_rooms=10
populate_doors.door_chance=0
```

After the solver / GC and `LargeShelfFactory` child node-group work, the next
bottleneck focus is final `populate_assets` clutter. A complete 10-room proxy
log showed `populate_assets` at about `3296.8s` / `54.9m` for `222` items.
The highest-priority populate factory is now `NatureShelfTrinketsFactory`,
with `BookStackFactory` and `LargePlantContainerFactory` as the next targets.

Use the new NatureShelfTrinkets instrumentation only when collecting evidence:

```bash
INFINIGEN_PROFILE_NATURE_SHELF_TRINKETS=1 python -m infinigen_examples.generate_indoors ...
python scripts/analyze_nature_shelf_trinkets.py \
  outputs/<run>/coarse/infinigen_nature_shelf_trinkets_timing.csv
```

For isolated internal cost attribution, use the targeted benchmark instead of
rerunning a full 10-room scene:

```bash
INFINIGEN_PROFILE_NATURE_SHELF_TRINKETS=1 \
python scripts/bench_nature_shelf_trinkets_factory.py \
  --samples 100 \
  --seed 0 \
  --output_folder outputs/bench_nature_shelf_trinkets_100
python scripts/analyze_nature_shelf_trinkets.py \
  outputs/bench_nature_shelf_trinkets_100/infinigen_nature_shelf_trinkets_timing.csv
```

The latest 100-sample targeted run completed with `100` successful samples and
`0` failures. It is only a microbenchmark for
`NatureShelfTrinketsFactory.create_asset()` internals, not a complete-scene
walltime result. In that sample, `stable_pose_duration` accounted for
`95.971s` / `54.1%` of measured `create_asset` time, and
`obj2trimesh_duration` accounted for `26.151s` / `14.7%`. Together the
stable-pose pipeline accounted for `122.121s` / `68.9%`, while
`base_factory_spawn_duration` accounted for `46.610s` / `26.3%`.

Top duration factories were `ClamFactory` (`49.970s`), `MusselFactory`
(`27.341s`), and `CoralFactory` (`25.904s`). `ClamFactory` and
`MusselFactory` were dominated by `compute_stable_poses()` on about `528k`
faces per sample. `CoralFactory` used much larger meshes, about `3.45m`
average faces, and was often dominated by `obj2trimesh` conversion rather than
`compute_stable_poses()` itself.

The diagnostic `stable_pose_cache_candidate_key` had `75` keys, `75` unique
keys, and `0` repeats. Exact stable-pose cache likely has limited benefit for
this sample. Material / texture / node-group creation is not the first
duration target in this benchmark, even though creature factories still create
most materials and node groups.

An opt-in fast shell stable-pose experiment now exists behind:

```bash
INFINIGEN_FAST_NATURE_TRINKET_STABLE_POSE=1
```

The first version affected only `ClamFactory`, `MusselFactory`, and
`ScallopFactory`; the current expanded version also affects `ConchFactory`,
`AugerFactory`, `VoluteFactory`, and `MolluskFactory`. It still does not affect
`CoralFactory` because Coral has separate `obj2trimesh` cost and higher shape /
support risk. The expanded shell-like 100-sample A/B showed total time
dropping from `153.955s` to `8.200s`, with `0` failures and unchanged mesh /
object / material counts. The earlier unfiltered candidate run was not
completed because it stalled on a non-fast `CoralFactory` sample, so use the
filtered A/B only as evidence for the fast scope itself.

A small manual visual check blend was generated at:

```text
outputs/bench_nature_shelf_trinkets_pose_ab/visual_check_fast_shell/nature_shelf_trinkets_bench.blend
outputs/bench_nature_fast_pose_expanded_shell/visual_check_fast/nature_shelf_trinkets_bench.blend
```

This output is not committed. Open it manually in Blender or Isaac and inspect
for floating, inverted shells, bottom-alignment errors, shelf intersection, or
obvious visual quality loss.

Recommended next order:

1. Do not rerun a full 10-room scene just to collect NatureShelfTrinkets
   internals. The bounded 1800s sample timed out inside `[solve_large]`, did
   not reach final `populate_assets`, and wrote no Nature timing CSV.
2. Manually inspect the fast shell visual check blend. Do not enter a full
   Isaac quality run until the small blend has no obvious floating, inverted,
   or intersecting shell trinkets.
3. If the small visual check passes, run a full Isaac static visual quality
   test with:
   `INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1`,
   `INFINIGEN_REUSE_LARGESHELF_CHILD_NODEGROUPS=1`,
   `INFINIGEN_FAST_NATURE_TRINKET_STABLE_POSE=1`, and
   `populate_doors.door_chance=0`.
4. Keep exact stable-pose cache off the main path unless a later full-scene or
   larger targeted sample shows repeated exact candidate keys.
5. Use the targeted benchmark for more samples or specific seeds when the goal
   is internal cost attribution. Keep interpreting it as a microbenchmark, not
   complete-scene walltime.
6. First inspect stable-pose-heavy paths, starting with `ClamFactory`, then
   `MusselFactory`. Look at the geometry fed into
   `trimesh.poses.compute_stable_poses()` and whether a separate opt-in
   simplification path can preserve visual quality.
7. Inspect `CoralFactory` separately for `obj2trimesh` conversion cost on very
   large meshes before changing stable-pose logic.
8. If a later larger sample shows `base_factory.spawn_asset` dominating,
   inspect the concrete wrapped base factory before broad wrapper changes.
9. If a later CSV shows repeated material, texture, or node-group names with high
   creation counts, design a separate opt-in reuse experiment for the narrowest
   repeated template only.
10. Keep `BookStackFactory` and `LargePlantContainerFactory` as second-priority
   populate targets after the NatureShelfTrinkets evidence is clearer.
11. Do not run concurrent benchmarks in this phase.
12. Do not reduce clutter count or scene complexity unless a later quality gate
   explicitly allows it.
13. Do not change solver behavior, proposal order, accept/reject behavior, or
   random number flow.

## Latest LargeShelf Child Reuse Short Sample

A first-round opt-in `LargeShelfFactory` child node group reuse experiment was
implemented behind:

```bash
INFINIGEN_REUSE_LARGESHELF_CHILD_NODEGROUPS=1
```

Default behavior is unchanged when the variable is unset. The first reuse set
is limited to `nodegroup_screw_head`, `nodegroup_side_board`,
`nodegroup_bottom_board`, and `nodegroup_back_board`.

Do not reuse these in the next step:

| prefix | reason |
| --- | --- |
| top-level `geometry_nodes` | per-shelf arrays, scalar defaults, and material objects |
| `nodegroup_division_board` | tag-support path and inclusive nested timing |
| `nodegroup_tagged_cube` | `MaskTag` / `TAG_support_surface` attribute risk |

The bounded 900s short A/B used seed `0`, `fast_solve.gin`,
`restrict_solving.solve_max_rooms=10`,
`populate_doors.door_chance=0`,
`INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1`, and
`INFINIGEN_PROFILE_SHELF_NODEGROUPS=1`. Both sides timed out as intended at
900s, so this is not a complete coarse profile and not a quality gate.

Results from the matched 163-spawn sample:

| metric | baseline | candidate |
| --- | ---: | ---: |
| CSV data rows | 5,918 | 5,918 |
| `LargeShelfFactory` spawns | 163 | 163 |
| actual node groups created | 5,918 | 3,363 |
| mean actual node groups per spawn | 36.307 | 20.632 |
| `spawn_summary` total duration | 60.096s | 36.718s |
| cache hit rate | 0.000% | 96.744% |

Target prefix duration dropped from `21.417s` to `0.538s`. No traceback, OOM,
or segfault was observed.

Recommended next order:

1. Run a full 10-room Isaac static quality validation with both opt-in speed
   switches enabled:
   `INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1` and
   `INFINIGEN_REUSE_LARGESHELF_CHILD_NODEGROUPS=1`.
2. Keep the static Isaac quality configuration at
   `restrict_solving.solve_max_rooms=10` and
   `populate_doors.door_chance=0` so door panels are not generated while door
   openings remain.
3. Treat the 900s result as timing evidence only; do not accept the reuse path
   until the full quality validation has no obvious scene bug and Isaac Sim can
   use the exported static environment.
4. Do not expand reuse to `nodegroup_division_board`, `nodegroup_tagged_cube`,
   or top-level `geometry_nodes` before the child-only path passes.
5. Keep `batch_remove` as the main deletion-cost switch. The reuse experiment
   addresses repeated creation cost that `batch_remove` does not solve.
6. Do not continue bbox C++ work or concurrent optimization from the current
   evidence.

## Latest LargeShelf Node Group Timing Sample

A bounded `LargeShelfFactory` shelf node group timing sample was collected on
2026-06-21 with `INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1`,
`INFINIGEN_PROFILE_SHELF_NODEGROUPS=1`, seed `0`, `fast_solve.gin`,
`restrict_solving.solve_max_rooms=10`, and
`populate_doors.door_chance=0`.

The valid run timed out at `3600s`, so it is not a complete coarse profile.
It still wrote:

```text
outputs/profile_shelf_nodegroups_seed0/coarse/infinigen_shelf_nodegroup_timing.csv
```

The CSV has `24,524` data rows, including `23,083` child
`nodegroup_create` rows and `1,441` `spawn_summary` rows. Mean created node
groups per `LargeShelfFactory` spawn was `17.019`, including one top-level
`geometry_nodes` tree per shelf.

Prefix duration totals:

| prefix | calls | total duration |
| --- | ---: | ---: |
| `nodegroup_division_board` | 5,629 | 278.151s |
| `nodegroup_screw_head` | 5,629 | 125.246s |
| `nodegroup_side_board` | 3,170 | 43.601s |
| `nodegroup_tagged_cube` | 5,629 | 37.736s |
| `nodegroup_bottom_board` | 1,585 | 25.735s |
| `nodegroup_back_board` | 1,441 | 23.490s |

The first-round reuse candidates
(`nodegroup_screw_head`, `nodegroup_side_board`,
`nodegroup_bottom_board`, and `nodegroup_back_board`) accounted for
`218.072s`, about `6.1%` of the `3600s` timeout window. This is enough to
justify a small opt-in reuse experiment. The inclusive prefix total
(`533.958s`) double-counts nested work because `nodegroup_division_board`
includes nested `nodegroup_tagged_cube` and `nodegroup_screw_head` creation.

`LargeShelfFactory` remains the next single-scene speed investigation target,
but only for opt-in shelf child node group reuse. The repeated high-frequency
shelf node group prefixes are created in
`infinigen/assets/objects/shelves/large_shelf.py` and
`infinigen/assets/objects/shelves/utils.py`.

The active path is:

```text
LargeShelfBaseFactory.create_asset()
  surface.add_geomod(obj, geometry_nodes, apply=True, input_kwargs=obj_params)
    geometry_nodes(...)
      nodegroup_side_board()
      nodegroup_back_board()
      nodegroup_bottom_board()
      nodegroup_division_board(..., tag_support=True)
        nodegroup_tagged_cube()
        nodegroup_screw_head()
```

All of these child groups currently use `singleton=False`, so each call creates
a fresh Blender node group datablock. `batch_remove` remains useful as an
opt-in deletion-cost switch, but it does not reduce repeated creation cost.

Use the new instrumentation only when needed:

```bash
INFINIGEN_PROFILE_SHELF_NODEGROUPS=1 python -m infinigen_examples.generate_indoors ...
python scripts/analyze_shelf_nodegroups.py \
  outputs/<run>/coarse/infinigen_shelf_nodegroup_timing.csv
```

Recommended next order:

1. Keep `INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1` as a separate opt-in
   deletion-cost switch; do not change its behavior.
2. Add a separate opt-in reuse experiment for pure shelf child groups,
   starting with `nodegroup_screw_head`,
   `nodegroup_side_board`, `nodegroup_bottom_board`, and
   `nodegroup_back_board`.
3. Treat `nodegroup_tagged_cube` and `nodegroup_division_board` as more
   sensitive second-phase candidates because they participate in tag-support
   behavior.
4. Do not reuse the top-level `geometry_nodes` tree in the first experiment;
   it embeds per-shelf sampled arrays and material objects.
5. Do not continue bbox C++ optimization from current evidence:
   `union_all_bbox` was only about `0.023%` of the measured bbox path.
6. Do not run concurrent benchmarks or tune multi-process throughput in this
   phase.
7. Do not change door logic. Default Isaac validation should keep
   `populate_doors.door_chance=0` so door panels are not generated and door
   openings remain.

## Latest Full Baseline Determinism Check

A full 10-room baseline repeat was completed to test whether the existing full
baseline is deterministic under the current strict JSON gate.

Compared folders:

```text
outputs/gc_batch_remove_equiv/baseline/coarse
outputs/determinism_full_baseline_b/coarse
```

The new baseline B run used the original baseline behavior: seed `0`, task
`coarse`, `fast_solve.gin`, `compose_indoors.terrain_enabled=False`,
`home_room_constraints.has_fewer_rooms=False`, and
`restrict_solving.solve_max_rooms=10`. `INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS`
was unset, and heavy profiling timing env vars were not enabled.

Baseline B completed with `MAIN TOTAL` `4:25:03.044391`. No timeout,
traceback, OOM, killed, or segfault marker was found.

`scripts/compare_indoor_outputs.py` result:

```text
matched_json_file_count: 2
DIFFERENT MaskTag.json numeric_max_abs_diff=1
  $.back.bottom: left 22, right 21
  $.front.top: left 21, right 22
SAME solve_state.json numeric_max_abs_diff=0
numeric_max_abs_diff: 1
FINAL: FAIL
```

The full baseline A/A repeats the same `MaskTag.json` label-ID swap seen in
the full baseline-vs-batch A/B. This means the `MaskTag.json` swap is not
currently attributable to `INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1`.

Static blend comparison was run only as diagnostic evidence:

```text
STATIC_SCENE_FAIL
USD_RELEVANT_DIFF: yes
UNUSED_DATABLOCK_DIFF: no
UNUSED_DATABLOCK_DIFF_ONLY: no
static_scene_diff_count: 60
unused_datablock_diff_count: 0
```

Because both single-room and full baseline-vs-baseline comparisons can fail the
saved-blend static scene diagnostic, saved `.blend` static-scene differences
alone are not a valid batch-remove rejection reason.

Updated next diagnostic order:

1. Keep `INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1` opt-in; do not mainline it.
2. Do not run walltime for acceptance while the strict/relevant gate is
   undefined or failing under baseline A/A.
3. Treat `solve_state.json SAME` as the strongest current evidence that the
   solver state is stable for the full baseline repeat.
4. Root-cause or explicitly scope the baseline nondeterminism in
   `MaskTag.json` label-ID assignment and saved-blend linked scene summaries.
5. Do not relax `scripts/compare_indoor_outputs.py` in the same round as an
   optimization. Any gate split must be a separate compare-policy proposal.
6. If a future gate distinguishes strict JSON, Isaac static scene, and
   GT/segmentation equivalence, calibrate that gate against baseline A/A first.
7. Only after the relevant baseline-calibrated gate is defined should
   baseline-vs-batch be used to decide whether batch remove changes the scene.

## Latest Determinism Ablation

Before judging `INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1`, confirm baseline
self-determinism. The new tools are:

```bash
python scripts/compare_blend_static_scene.py outputs/a/coarse outputs/b/coarse
EXPERIMENT_SMOKE_SINGLE_ROOM=1 EXPERIMENT_TIMEOUT_SECONDS=3600 bash scripts/run_determinism_ablation.sh
```

The 2026-06-20 smoke A/A completed without timeout or error markers. Both
baseline A/A and candidate A/A passed `scripts/compare_indoor_outputs.py`:
`MaskTag.json` and `solve_state.json` were `SAME`, and
`numeric_max_abs_diff` was `0`.

Both smoke A/A pairs failed `scripts/compare_blend_static_scene.py` with
`STATIC_SCENE_FAIL` and `USD_RELEVANT_DIFF: yes`. The differences were linked
scene differences, not unused-datablock-only differences. They included
wall/floor/ceiling material slot changes and some wall mesh vertex/edge/polygon
count changes, while object counts and object type counts matched.

This means the saved `.blend` differences in the previous full
baseline-vs-batch A/B cannot yet be attributed to batch remove. At least in
smoke mode, baseline same-seed A/A is JSON-deterministic but not static-blend
deterministic under the new comparator.

Next diagnostic order:

1. Keep batch remove opt-in and do not mainline it.
2. Do not run walltime for acceptance while the relevant equivalence gate is
   failing or undefined.
3. Use the completed full 10-room baseline A/A recorded above as the current
   baseline-calibration evidence.
4. Because full baseline-vs-baseline shows the same MaskTag label-ID swap and
   linked static-scene diagnostic differences, redefine the strict/static gates
   before blaming batch remove.
5. If a later baseline-calibrated gate passes for baseline-vs-baseline but
   fails for baseline-vs-batch, treat batch remove as a likely source of scene
   change and continue root-cause analysis.
6. Keep unused Blender datablock differences separate from USD-relevant linked
   scene differences. Unused node group differences alone should not be treated
   the same as object, mesh, material-slot, transform, or linked node-tree
   differences.
7. If `MaskTag.json` proves to affect only GT annotation and not the linked
   static scene, consider a separately reviewed Isaac-static-scene-specific
   equivalence gate. Do not relax `compare_indoor_outputs.py` in the same
   round as an optimization.

## Latest MaskTag Investigation

The full 10-room `INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1` A/B completed and
has a clear runtime signal: baseline `MAIN TOTAL` was `4:11:49.774668`, while
candidate_batch was `3:07:38.553985`. The signal is not accepted as a validated
speedup because strict equivalence still failed.

The only comparable JSON failure was `MaskTag.json`: `front.top` and
`back.bottom` swapped tag IDs `21` and `22`. `solve_state.json` was equal after
the compare script's canonicalization, so this does not by itself show a solver
layout change. `MaskTag.json` is a tag-to-integer-label mapping used for
semantic tag lookup and GT/tag-segmentation interpretation; the inspected USD
export and Isaac Sim static import paths do not read it.

Do not conclude that the current candidate is Isaac-static-equivalent. A
read-only Blender summary of the saved baseline-vs-batch blends found matching
object names and counts but different mesh totals, several
mesh/material/transform differences, and extra candidate node groups. However,
the later full baseline A/A also failed the static blend diagnostic with linked
scene differences, so saved `.blend` static differences are not currently a
batch-remove-specific rejection signal. Before any walltime run or promotion
of batch remove, define a baseline-calibrated relevant gate or root-cause the
baseline nondeterminism.

If a future run has only a pure `MaskTag.json` ID-order difference and no
USD-relevant scene differences, it may be worth proposing separate validation
gates for strict equivalence, Isaac static scene equivalence, and GT annotation
equivalence. That should be a separate compare-policy proposal, not an
immediate relaxation.

## Suggested Next Round

1. Keep the current optimization scope to a single indoor coarse scene. Do not
   run concurrent benchmarks, do not tune `manage_jobs.num_concurrent`, and do
   not investigate 32-thread or multi-process throughput until single-scene
   behavior-preserving optimization is stable and A/B validated.
2. Treat `INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1` as the current opt-in
   cleanup candidate only. The 2026-06-19 smoke lowered timeout-sample
   `node_groups` remove duration from 366.131s in the baseline to 46.350s in
   the candidate, while the candidate advanced farther and removed more node
   groups. This remains a strong timing signal, not a validated optimization.
3. Treat the 2026-06-20 full 10-room A/B as a completed equivalence failure.
   Both baseline and candidate completed, but `compare_indoor_outputs.py`
   printed `FINAL: FAIL`: `solve_state.json` was `SAME`, while
   `MaskTag.json` differed with `numeric_max_abs_diff: 1` at
   `$.back.bottom` and `$.front.top`.
4. Do not run or interpret a full wall-clock A/B for batch remove until the
   normal 10-room equivalence run prints `FINAL: PASS`. The 2026-06-20
   wall-clock run was intentionally skipped because the equivalence gate failed.
5. Investigate the `MaskTag.json` difference before any further promotion of
   batch remove. Determine whether the front/back count swap is a real visible
   behavior change, a comparison-scope issue, or a Blender data-block lifecycle
   effect from `bpy.data.batch_remove`. This investigation found that
   `MaskTag.json` itself is a tag-label mapping, but the saved blends also
   differ in mesh/material/transform summaries. Any code change or revised
   comparison policy must be followed by a fresh same seed/gin/task 10-room
   A/B.
6. Use `EXPERIMENT_SMOKE_SINGLE_ROOM=1` only as a harness smoke. Passing
   single-room A/B validates the script and catches obvious differences, but it
   does not prove the 10-room mainline target is behavior-preserving or faster.
   The 2026-06-19 single-room smoke did pass compare on both new scripts, but
   wall-clock was effectively flat at `0.999x`, so it is not speed evidence for
   the full target.
7. If reducing iteration cost for diagnosis, clearly label any smaller run as a
   smoke or near-mainline diagnostic. A singleroom PASS or reduced-room PASS
   must not replace the normal 10-room behavior-preserving proof.
8. Keep `LargeShelfFactory` and repeated node group prefixes as the root-cause
   attribution target. The attribution sample measured `LargeShelfFactory` at
   139.219s and 5,661 removed node groups; repeated prefixes included
   `nodegroup_tagged_cube`, `nodegroup_division_board`,
   `nodegroup_screw_head`, and `nodegroup_side_board`.
9. Do not continue expanding `INFINIGEN_GC_NODE_GROUP_INTERVAL` experiments.
   The interval=20 smoke was not a valid speedup: both baseline and candidate
   timed out, no comparable JSON was produced, and raw `node_groups_remove`
   increased from 369.071s to 443.414s. Naive deferred node group cleanup
   creates large burst removes and is not the main path.
10. If batch remove later passes full A/B, run
   `scripts/run_gc_batch_remove_walltime.sh` to measure wall-clock speed without
   heavy timing instrumentation before promoting the opt-in path. If the
   `MaskTag.json` difference persists, first determine whether it is a pure
   GT/tag-label mapping difference or accompanied by USD-relevant static scene
   differences. Keep batch remove opt-in/rejected for mainline use until the
   relevant equivalence gate passes, and shift back to precise reuse, caching,
   or reduced duplicate node group creation in the dominant factories instead
   of broad delayed cleanup if the scene differences remain unexplained.
11. Inspect the factory paths and node tree generation for the factories that
   dominate node group churn, starting with `LargeShelfFactory`, then
   `SimpleBookcaseFactory`, `SimpleDeskFactory`, `KitchenIslandFactory`, and
   the kitchen appliance factories observed in the batch smoke.
12. If repeated node group prefixes are semantically equivalent for the same
   factory parameters, consider an opt-in reuse/cache/reduce-duplicate-creation
   experiment. Preserve node group identity and Blender-visible lifecycle
   behavior unless same seed/gin/task A/B proves equivalence.
13. If inspection shows the node group names are highly parameterized or not
   safely reusable, continue with a finer cleanup strategy instead of broad
   delayed cleanup. Any cleanup strategy must remain opt-in until it passes
   A/B comparison.
14. Keep the standalone geometry kernels out of the default indoor solver
   path. The 2026-06-19 bbox sample measured `union_all_bbox` at 0.075s out of
   334.068s of `bbox_mesh_from_hipoly` time, or 0.023%, so do not prioritize
   default C++ bbox integration from current evidence.
15. Treat `AssetFactory.spawn_asset` / factory lifecycle as the current first
   investigation target. The latest GC sample measured
   `garbage_collect_context_duration` at 177.848s out of 278.502s of
   `spawn_asset` time, or 63.859%; `create_asset_duration` was secondary at
   99.383s, or 35.685%, and `delete_placeholder_duration` was only 0.228s, or
   0.082%.
16. Treat `bpy.data.node_groups` removal as the current first behavior-preserving
   experiment target. The GC target sample measured 183.972s in target
   `exit_cleanup`, 183.378s in `remove_duration`, and 181.131s in
   `node_groups` alone. `enter_snapshot` was only 0.422s, and broad scan time
   excluding remove was about 0.594s.
17. Use the opt-in `INFINIGEN_GC_NODE_GROUP_INTERVAL` experiment only behind the
   environment variable. Unset or `1` keeps default behavior; values greater
   than `1` throttle only `bpy.data.node_groups` cleanup. This may change
   Blender data-block name allocation or leave residual node groups, so it must
   pass same seed/gin/task A/B before being treated as usable.
18. Do not treat the interval=20 smoke as a validated speedup. Both runs timed
   out, `compare_indoor_outputs.py` found no comparable JSON, and raw
   `node_groups_remove` increased from 369.071s to 443.414s in the partial
   sample despite 558 skipped cleanup opportunities. Prefer targeted node group
   attribution, reuse, or cache investigation instead of changing the interval.
19. If trying GC scope adjustment, node-group-specific cleanup, less frequent
   cleanup, deferred cleanup, batch cleanup, or factory bbox/cache reuse,
   preserve random number consumption, proposal order, accept/reject decisions,
   object parent/transform/delete semantics, and final output. Validate with
   `scripts/compare_indoor_outputs.py`.
20. Use `INFINIGEN_PROFILE_GC=1` or `INFINIGEN_PROFILE_TIMING=1` to collect
   `infinigen_gc_timing.csv`, then run `scripts/analyze_gc_timing.py`.
21. Use `INFINIGEN_PROFILE_ASSET_FACTORY=1` or `INFINIGEN_PROFILE_TIMING=1` to
   collect `infinigen_asset_factory_timing.csv`, then run
   `scripts/analyze_asset_factory_timing.py`.
22. Use `INFINIGEN_PROFILE_BBOX=1` or `INFINIGEN_PROFILE_TIMING=1` to collect
   `infinigen_bbox_timing.csv`, then run `scripts/analyze_bbox_timing.py` only
   if bbox behavior changes are under consideration.
23. Run `python -m pytest tests/test_geometry_kernels.py -q` and
   `python scripts/bench_geometry_kernels.py` after every kernel change.
24. When build environments cannot compile the geometry extension, use
   `INFINIGEN_DISABLE_GEOMETRY_CPP=True python -m pip install -e .` and verify
   the NumPy fallback remains importable.
25. Consider an opt-in bbox C++ experiment only if a later timing sample
   contradicts the current 0.023% `union_all_bbox` share.
26. Before any solver-facing use, run same seed/gin/task A/B with
   `scripts/compare_indoor_outputs.py` and require matching coarse JSON.
27. Do not fix the suspected `union_all_bbox` max update while doing this
   opt-in kernel integration. Treat that as a separate behavior change.

## Existing Optimization Guidance

1. Start the behavior-preserving optimization phase by running an A/B baseline
   and candidate comparison with `scripts/compare_indoor_outputs.py`.
2. Keep the same seed, gin files, gin parameter overrides, task, output target,
   solve steps, room count, and object availability for each A/B.
3. Start with behavior-preserving Python/Blender optimizations, not a C++
   rewrite.
4. Target the largest wasted `Addition.apply` clusters first:
   - `KitchenIslandFactory` - 257.877s wasted apply in the 1800s timing sample.
   - `LargeShelfFactory` - 209.884s wasted apply.
   - `BeverageFridgeFactory` - 82.742s wasted apply.
   - `TableDiningFactory` - 72.458s wasted apply.
   - `LargePlantContainerFactory` - 61.787s wasted apply.
5. Investigate cheap preflight rejection only as a risky candidate. It cannot
   enter the main path unless it preserves random number consumption, proposal
   order, accept/reject decisions, and final output.
6. Cache deterministic placeholder, bbox, and high-poly mesh bound computations
   only where the generated result is equivalent for the same factory
   parameters.
7. Investigate whether accepted assets can be finalized later while failed
   proposals use equivalent lightweight bounds/proxies for early checks.
   Validate visually, with timing, and with A/B output comparison before relying
   on this.
8. Memoize local negative placement/relation candidates inside a stage only if
   it does not change random-path behavior, retry order, or final output.
9. Keep `garbage_collect_duration` visible, but do not make it the first target.
   In the timing CSV, apply dominates: 1160.159s apply versus 172.236s
   evaluate, 187.095s revert, and a row-level 287.308s garbage-collect sum with
   repeated step-level rows.

Do not use reduced content, fewer rooms, fewer solve steps, disabled object
classes, or lower quality as the main acceleration strategy.

## C++ Rewrite Candidates

Only consider these after the Python/Blender behavior-preserving pass, and only
for pure computation kernels that do not touch `bpy`, random numbers, solver
control flow, proposal order, or accept/reject logic:

1. Numeric bbox min/max reductions and high-poly mesh bounds extraction.
2. AABB overlap and broad-phase collision checks.
3. Room/floor/wall bounds and containment checks over numeric arrays.
4. Batch collision matrix construction for many boxes or sampled candidates.
5. Constraint loss aggregation once inputs are already numeric arrays.

Avoid C++ rewrites for:

- `bpy` object creation/deletion
- `spawn_asset` or factory orchestration
- `GarbageCollect` / `bpy.data` cleanup
- material/node generation
- the simulated annealing solver control flow
- random number sampling
- proposal / accept / reject logic

See `docs/CPP_REWRITE_CANDIDATES.md` before writing any C++.

## A/B Equivalence Commands

Compare two coarse outputs:

```bash
python scripts/compare_indoor_outputs.py outputs/a/coarse outputs/b/coarse
```

With explicit tolerances:

```bash
python scripts/compare_indoor_outputs.py \
  --rtol 1e-6 \
  --atol 1e-6 \
  --max-diffs 20 \
  outputs/a/coarse \
  outputs/b/coarse
```

If the script prints `NO_COMPARABLE_JSON_FOUND`, the validation failed because
there was no comparable JSON evidence.

## Timing Commands

Run the timing profile:

```bash
INFINIGEN_PROFILE_TIMING=1 bash scripts/profile_indoor_solver.sh
```

If a full run is too slow, use a bounded sample:

```bash
INFINIGEN_PROFILE_TIMING=1 timeout 1800s bash scripts/profile_indoor_solver.sh
```

Analyze the CSV:

```bash
python scripts/analyze_indoor_timing.py
```

The default CSV path is:

```text
outputs/profile_indoor_baseline/coarse/indoor_solver_timing.csv
```

## Deferred Sanity Check

Add a focused sanity test for `infinigen/assets/utils/bbox_from_mesh.py::union_all_bbox` before changing it. The current `maxs` update logic looks suspicious and should be verified independently from timing work.

## Current Guardrails

- Keep original generation behavior available.
- Every optimization must pass A/B equivalence validation before being treated
  as mainline.
- Prefer opt-in `fast` / `isaac` config paths for speed experiments.
- Keep changes small enough to profile and roll back.
- Use C++ only for pure computation kernels.
- Do not trade away generated content or quality for speed.
- Do not commit generated `outputs`, `.blend`, `.usd`, `.usdc`, `.prof`, or `.zip` files.
