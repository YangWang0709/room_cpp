# Worklog

## 2026-06-23 - 9950X3D production scene queue tooling

### Round Goal

Stop CPU parallel strategy tuning for the current line and implement the
production queue based on the validated 9950X3D `JOBS=4` CCD split. No solver,
asset factory, proposal / accept / reject logic, or
`scripts/run_isaac_static_optimized_10room.sh` default behavior was changed.

Current clean candidate:

```text
JOBS=4
CPU_SETS="0-3,16-19;4-7,20-23;8-11,24-27;12-15,28-31"
```

Correct CCD / L3 groups:

```text
CCD0 / L3: 0-7,16-23
CCD1 / L3: 8-15,24-31
```

`0-15;16-31` remains incorrect for CCD grouping.

### Implementation

Added:

```text
scripts/run_9950x3d_production_scene_queue.sh
scripts/analyze_9950x3d_production_queue.py
```

The queue assigns seeds round-robin across fixed workers:

```text
worker0: seed100 coarse -> seed100 export -> seed104 coarse -> seed104 export
worker1: seed101 coarse -> seed101 export -> seed105 coarse -> seed105 export
worker2: seed102 coarse -> seed102 export -> seed106 coarse -> seed106 export
worker3: seed103 coarse -> seed103 export -> seed107 coarse -> seed107 export
```

Each worker is a bash subshell with one fixed CPU set. Each coarse and export
command uses `taskset -c <CPU_SET>`. Export runs serially inside the same
worker after that seed's coarse output exists, so the script does not layer
extra global export concurrency on top of coarse generation.

The production queue enables the stable Isaac static speed flags by default:

```text
INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1
INFINIGEN_REUSE_LARGESHELF_CHILD_NODEGROUPS=1
INFINIGEN_FAST_NATURE_TRINKET_STABLE_POSE=1
compose_indoors.terrain_enabled=False
home_room_constraints.has_fewer_rooms=False
restrict_solving.solve_max_rooms=10
populate_doors.door_chance=0
```

`INFINIGEN_REUSE_PLANT_TEMPLATE_GEOMETRY` remains default-off and is only set
when `ENABLE_WHEAT_REUSE=1`.

### Outputs

Default output root:

```text
outputs/production_9950x3d_isaac_queue
```

Each seed writes independent coarse, USD, log, timing, env, and status files.
The analyzer writes:

```text
summary.csv
summary.md
```

Fatal markers include Traceback, segmentation fault, killed/OOM signals, CUDA
errors, and uncaught exceptions. Blender shutdown `Not freed memory blocks`
messages are tracked separately as leak warnings and are not counted as true
fatal markers by themselves.

### Recommendation

Use the production queue for the next real batch after dry-run validation. If
USD export becomes the measured limiter, benchmark export queueing or
`EXPORT_JOBS` separately. Do not commit generated `outputs`, logs, CSVs,
`.blend`, `.usd`, `.usdc`, profiles, zips, or cache directories.

## 2026-06-23 - Seed21 Concrete kwarg fix and clean CCD4 rerun

### Round Goal

Fix the seed 21 `Concrete.generate(vertical=...)` failure from the 9950X3D
`JOBS=4` CCD split full-timeout run, then rerun the same four seeds without
Wheat reuse and without USD export. No solver behavior, proposal / accept /
reject logic, asset factories, stable Isaac defaults, or Wheat reuse defaults
were changed.

Correct CCD / L3 groups:

```text
CCD0 / L3: 0-7,16-23
CCD1 / L3: 8-15,24-31
```

`0-15;16-31` is not CCD grouping.

### Fix

Root cause: `room_walls()` passed `vertical/alternating/shape` to every wall
material generator. Seed 21 selected `ceramic.Concrete`, but
`Concrete.generate()` did not accept `vertical`.

Updated `infinigen/core/constraints/example_solver/room/decorate.py` to call
room material generators through `call_material_generator()`, which filters
unsupported kwargs with `inspect.signature()`. Seed 21 passed standalone coarse
validation after the patch and wrote `scene.blend` without a new Traceback.

### Clean Rerun Result

| case | jobs | CPU sets | complete | timeout | failed | scenes/hour | avg wall s | max wall s | max RSS KB |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| CCD4 clean after seed21 fix | 4 | `0-3,16-19;4-7,20-23;8-11,24-27;12-15,28-31` | 4 | 0 | 0 | 1.825 | 6040.320 | 7892.000 | 11183508 |

All four seeds exited `0` and wrote `scene.blend`. There was no Traceback, no
OOM, no swap use, no killed process, no CUDA error, and no segmentation fault.
The analyzer still reports `fatal=4` because all complete Blender logs contain
small `Error: Not freed memory blocks` shutdown messages; these are treated as
false-positive fatal markers for this benchmark.

### Recommendation

`JOBS=4` with the 4-way CCD split is now the current 9950X3D multi-scene coarse
generation candidate default:

```text
CPU_SETS="0-3,16-19;4-7,20-23;8-11,24-27;12-15,28-31"
JOBS=4
```

Do not test `JOBS=5/6` next unless running a separate scaling experiment.
Proceed to fullopt_wheat quality validation as a separate opt-in line if
desired. Keep USD export parallelism deferred for a separate benchmark. Outputs
remain local experiment data and must not be committed.

Local report:

```text
outputs/bench_9950x3d_compare_snapshots/compare_ccd4_clean_after_seed21_fix.md
```

## 2026-06-23 - 9950X3D JOBS=3 and JOBS=4 full-timeout follow-up

### Round Goal

Continue the 9950X3D multi-scene CPU parallel benchmark without changing
generation logic, solver behavior, asset factories, stable Isaac defaults,
Wheat reuse defaults, or USD export behavior. This round measured:

```text
JOBS=3 bounded
JOBS=4 CCD split full-timeout coarse-only
```

Correct CCD / L3 groups:

```text
CCD0 / L3: 0-7,16-23
CCD1 / L3: 8-15,24-31
```

`0-15;16-31` is not CCD grouping.

### Result

| case | jobs | CPU sets | complete | timeout | failed | scenes/hour | max RSS KB | progress_score |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| JOBS=3 bounded | 3 | `0-4,16-20;5-9,21-25;10-15,26-31` | 0 | 3 | 0 | 0.000 | 3306032 | 302082 |
| JOBS=4 CCD split full-timeout | 4 | `0-3,16-19;4-7,20-23;8-11,24-27;12-15,28-31` | 3 | 0 | 1 | 1.378 | 11260204 | 407391 |

JOBS=3 was stable but did not beat the 4-way CCD split bounded signal. The
JOBS=4 full-timeout run produced three complete coarse scenes and no timeout,
swap, OOM, or killed process. Seed 21 failed late in `room_walls` with:

```text
TypeError: Concrete.generate() got an unexpected keyword argument 'vertical'
```

Wheat reuse was not enabled, and USD export was not enabled. The analyzer's
`fatal=4` includes Blender `Error: Not freed memory blocks` shutdown messages
from completed seeds; the actionable failure is seed 21's Traceback.

### Recommendation

Keep `JOBS=4` with the 4-way CCD split as the current throughput candidate,
but do not treat it as a clean unattended full-run default until the seed 21
failure is understood or shown to be seed/content-specific. Do not proceed to
JOBS=5/6 yet. Keep `EXPORT_USD` / `EXPORT_JOBS` for a separate benchmark, and
do not enter fullopt_wheat quality validation directly from this failed
coarse-only sample. `TIMEOUT_SECONDS=14400` was sufficient for this sample.

Local report:

```text
outputs/bench_9950x3d_compare_snapshots/compare_jobs3_vs_jobs4_fulltimeout.md
```

Generated outputs remain local experiment data and must not be committed.

## 2026-06-22 - 9950X3D manual CCD benchmark comparison

### Round Goal

Fix the single-mode path issue in the 9950X3D benchmark script, preserve the
user's 2-way CCD result, then compare:

```text
2-way CCD
4-way CCD split
2-way physical cores only
```

No Infinigen generation logic, solver behavior, asset factories, stable Isaac
script defaults, or Wheat reuse defaults were changed.

### Script Fix

Updated `scripts/run_9950x3d_parallel_scene_bench.sh` so single-mode output
paths stay tied to the current case directory. The script now creates per-seed
case/log directories before launch, records `output_root` and `case_dir` in
case metadata, allows `CLEAN=1` for independent `outputs/bench_9950x3d_*`
benchmark roots, refuses to clean comparison snapshots, and uses an output-root
lock plus active-process check to avoid overlapping runs deleting each other's
logs.

Dry-run validation confirmed `single_jobs2_manual` no longer references
`cases/jobs1_none/logs/seed_10`.

### Benchmark Result

Correct observed CCD / L3 groups:

```text
CCD0 / L3: 0-7,16-23
CCD1 / L3: 8-15,24-31
```

`0-15;16-31` is not a CCD split.

Summary:

| case | jobs | CPU sets | complete | timeout | failed | fatal | max RSS KB | progress_score |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 2-way CCD | 2 | `0-7,16-23;8-15,24-31` | 0 | 2 | 0 | 0 | 2818032 | 200849 |
| 4-way CCD split | 4 | `0-3,16-19;4-7,20-23;8-11,24-27;12-15,28-31` | 0 | 4 | 0 | 0 | 3015204 | 403039 |
| 2-way physical-only | 2 | `0-7;8-15` | 0 | 2 | 0 | 0 | 3122024 | 200878 |

All scenes timed out at 1800s, so `scenes/hour` is zero for all cases. None
showed Traceback, killed/OOM, fatal markers, or swap. The current bounded
recommendation is `JOBS=4` with the 4-way CCD split for aggregate progress,
but `JOBS=3` should be tested before accepting a full-run default. Keep
`EXPORT_USD=0` until coarse generation completes under a longer/full timeout.

Combined local report:

```text
outputs/bench_9950x3d_compare_snapshots/compare_9950x3d_parallel_results.md
```

Generated outputs are local experiment data and must not be committed.

## 2026-06-22 - 9950X3D parallel scene benchmark tooling

### Round Goal

Add hardware / system benchmark tooling for Ryzen 9 9950X3D multi-scene
throughput. This round is script and documentation work only: no solver
changes, no asset factory changes, no proposal / accept / reject changes, no
C++, no GPU optimization, no single-Blender Python threads, and no change to
`scripts/run_isaac_static_optimized_10room.sh` defaults.

### Implementation

Added:

```text
scripts/run_9950x3d_parallel_scene_bench.sh
scripts/analyze_9950x3d_parallel_scene_bench.py
```

The benchmark runs one seed per independent Python-Blender process and uses
bash job control rather than GNU parallel. It records topology and system
state before cases:

```text
topology/cpu_topology.txt
topology/cpu_topology.json
topology/recommended_cpu_sets.md
```

Topology is derived from `lscpu -e=CPU,CORE,SOCKET,NODE,CACHE` shared LLC
groups, with a recorded fallback to continuous halves only when cache grouping
is unavailable. This is intended to test CCD-aware placement without hard
coding that CPU `0-15` maps to a specific CCD. Real runs should also watch CPU
governor / frequency state, temperature, memory, swap, and I/O; thermal
throttling or swap/OOM invalidates a throughput recommendation.

Supported CPU strategies:

```text
none
compact_llc
split_llc
physical_cores_only
smt_pairs
manual
```

Default matrix:

```text
JOBS=1 CPU_STRATEGY=none
JOBS=2 CPU_STRATEGY=split_llc
JOBS=2 CPU_STRATEGY=physical_cores_only
JOBS=4 CPU_STRATEGY=split_llc
JOBS=4 CPU_STRATEGY=physical_cores_only
```

The default timeout is `1800s`; this is a bounded comparison, not a full
completion requirement. `JOBS=8` is not part of the default matrix and requires
`ALLOW_JOBS8=1`.

### Defaults And Guardrails

Generation uses the accepted Isaac static switches:

```text
INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1
INFINIGEN_REUSE_LARGESHELF_CHILD_NODEGROUPS=1
INFINIGEN_FAST_NATURE_TRINKET_STABLE_POSE=1
restrict_solving.solve_max_rooms=10
populate_doors.door_chance=0
```

`INFINIGEN_REUSE_PLANT_TEMPLATE_GEOMETRY=1` is intentionally off by default.
Only `ENABLE_WHEAT_REUSE=1` enables it for explicit experiments because Wheat
reuse has targeted benchmark evidence but is not yet the stable full 10-room
default.

Each job forces low-level library thread counts to `1`:

```text
OMP_NUM_THREADS=1
OPENBLAS_NUM_THREADS=1
MKL_NUM_THREADS=1
NUMEXPR_NUM_THREADS=1
BLIS_NUM_THREADS=1
```

USD export is off by default. If `EXPORT_USD=1`, export starts after all coarse
generation in the case finishes and defaults to `EXPORT_JOBS=1`.

### Next Use

Run a dry-run first:

```bash
DRY_RUN=1 BENCH_MODE=matrix SEEDS=10,11,12,13 TIMEOUT_SECONDS=300 \
bash scripts/run_9950x3d_parallel_scene_bench.sh
```

Then run the bounded 1800s matrix. Compare `scenes/hour`, failure rate,
timeout count, max RSS, swap/OOM markers, and last progress lines. If `JOBS=2`
is stable, test `JOBS=3` before treating `JOBS=4` or higher as the throughput
default.

## 2026-06-22 - Opt-in Wheat plant geometry reuse experiment

### Round Goal

Implement the first narrow Plant geometry reuse experiment without changing
default behavior. This round only affects `WheatMonocotFactory` when:

```bash
INFINIGEN_REUSE_PLANT_TEMPLATE_GEOMETRY=1
```

The stable `scripts/run_isaac_static_optimized_10room.sh` defaults were not
changed. Solver behavior, proposal / accept / reject logic, plant count, plant
complexity, batch-remove behavior, LargeShelf reuse, NatureShelf fast pose,
concurrency, and C++ paths were not changed.

### Implementation

Added a Wheat-only raw mesh template cache in:

```text
infinigen/assets/objects/monocot/grasses.py
```

The cache stores mesh data from `WheatMonocotFactory.create_raw()` after
leaf/stem geometry and the applied `make_geo_flower()` step. Cache hits create
a new object from a copied cached mesh. The cache datablocks are kept out of
the scene and named with `(no gc)` so they survive local garbage collection.

Still per instance:

```text
WheatEarMonocotFactory.create_asset()
ear bend
decorate_monocot()
cluster placement
pot/dirt/container work
```

Not reused:

```text
complete Wheat plant object
complete pot+plant+dirt assembly
Grasses / Veratrum / Agave / Maize / other Plant factories
```

Because cache hits skip original raw leaf/stem generation, this opt-in
experiment changes Wheat internal random consumption and is not a
bitwise-equivalence path.

### Timing

Extended `INFINIGEN_PROFILE_PLANT_ASSETS=1` CSV rows with:

```text
plant_template_reuse_enabled
plant_template_reuse_used
plant_template_cache_hit
plant_template_cache_miss
plant_template_cache_key
plant_template_cache_size
plant_template_reuse_scope
plant_template_fallback_count
```

`scripts/analyze_plant_assets_timing.py` now reports Wheat cache hit/miss
counts, hit rate, fallback count, and original/reuse duration rows.

### Benchmark

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

Result:

| metric | baseline | candidate |
| --- | ---: | ---: |
| rows | 30 | 30 |
| failures | 0 | 0 |
| measured total | `229.654s` | `144.198s` |
| benchmark wall time | `236.935s` | `149.062s` |
| average | `7.655s` | `4.807s` |
| max | `14.606s` | `7.445s` |
| `plant_spawn_duration` | `203.202s` | `117.766s` |
| `leaf_generation_duration` | `58.830s` | `18.603s` |
| `stem_generation_duration` | `46.990s` | `16.119s` |
| `branch_generation_duration` | `66.677s` | `62.409s` |
| created meshes | 1,910 | 1,418 |
| created objects | 1,790 | 1,210 |

Candidate cache stats: `58` hits, `30` misses, `65.909%` hit rate, and `0`
fallbacks.

### Visual Gate

Generated:

```text
outputs/bench_wheat_template_reuse_ab/visual_check_wheat/wheat_template_reuse_check.blend
```

Manual inspection should check for copied Wheat appearance, broken leaves,
stems or ears, flying objects, scale errors, severe intersections, and obvious
complexity loss. If it passes, the next step is a full 10-room quality
validation with the Plant switch. `GrassesMonocotFactory` remains the second
candidate, but should wait for Wheat visual acceptance.

## 2026-06-22 - Concrete Plant geometry reuse candidate investigation

### Round Goal

Investigate the minimum opt-in feasibility for concrete monocot geometry reuse
without implementing reuse. This round did not optimize Plant generation, did
not reduce plant count or complexity, did not add material reuse, did not add
concurrency or C++, and did not change
`scripts/run_isaac_static_optimized_10room.sh`.

### Changes

Enhanced optional Plant timing behind:

```bash
INFINIGEN_PROFILE_PLANT_ASSETS=1
```

The CSV now records:

```text
concrete_plant_factory_class
geometry_template_candidate_key
geometry_reuse_risk_level
leaf_count / stem_count / branch_count
leaf_mesh_count / stem_mesh_count / branch_mesh_count
leaf_generation_duration / stem_generation_duration / branch_generation_duration
```

Updated:

```text
infinigen/assets/objects/tableware/plant_container.py
scripts/bench_plant_assets_factory.py
scripts/analyze_plant_assets_timing.py
docs/PLANT_POPULATE_INVESTIGATION.md
docs/PLANT_TEMPLATE_GEOMETRY_REUSE_PLAN.md
docs/PROFILE_RESULTS.md
docs/NEXT_STEPS.md
```

The benchmark also supports:

```bash
--concrete-plant-filter WheatMonocotFactory,GrassesMonocotFactory
```

### Source Investigation

Focused concrete monocot paths:

```text
WheatMonocotFactory    infinigen/assets/objects/monocot/grasses.py
GrassesMonocotFactory  infinigen/assets/objects/monocot/grasses.py
VeratrumMonocotFactory infinigen/assets/objects/monocot/veratrum.py
AgaveMonocotFactory    infinigen/assets/objects/monocot/agave.py
```

Shared call chain:

```text
PlantContainerFactory.create_asset()
  MonocotFactory.spawn_asset()
    MonocotFactory.create_asset()
      concrete_monocot_factory.create_asset()
        create_raw()
          make_collection()
            build_instance()
              build_leaf()
          build_stem()
          surface.add_geomod(..., apply=True)
        optional branch / ear / husk create_asset()
        decorate_monocot()
```

### Benchmark

Command:

```bash
INFINIGEN_PROFILE_PLANT_ASSETS=1 \
python scripts/bench_plant_assets_factory.py \
  --samples 50 \
  --seed 0 \
  --output_folder outputs/bench_plant_assets_concrete_deep
```

Result: `50/50` samples, `0` failures. CSV:

```text
outputs/bench_plant_assets_concrete_deep/infinigen_plant_assets_timing.csv
```

Measured total was `214.538s`, average `4.291s`, max `13.230s`, and benchmark
wall time `217.514s`. `plant_spawn_duration` was `170.618s` / `79.5%`.
Leaf generation was `87.873s`, branch generation was `31.567s`, and stem
generation was `28.268s`. Material generation was only `0.991s`, so Plant
material reuse is still not the first target.

Top concrete duration classes were `WheatMonocotFactory` (`50.353s`),
`VeratrumMonocotFactory` (`39.694s`), `GrassesMonocotFactory` (`37.763s`),
and `AgaveMonocotFactory` (`22.650s`).

### Judgment

The first future implementation candidate is a narrow, default-off
`WheatMonocotFactory` geometry-template experiment. `GrassesMonocotFactory`
is the second candidate. Do not start with `VeratrumMonocotFactory` or
`AgaveMonocotFactory`; their branch systems and leaf deformation are higher
visual-risk sources of random variation.

`geometry_template_candidate_key` is intentionally coarse and repeated at the
concrete-family level. It is useful for grouping and risk review, but is not a
safe cache key by itself.

## 2026-06-22 - Deep Plant asset timing investigation

### Round Goal

Investigate `PlantContainerFactory` / `LargePlantContainerFactory` as the next
populate-stage candidate after the accepted Isaac static configuration. No
Plant optimization was added. The stable
`scripts/run_isaac_static_optimized_10room.sh` defaults were not changed.
Solver behavior, proposal / accept / reject logic, batch-remove behavior,
LargeShelf reuse, NatureShelf fast pose, door configuration, concurrency,
C++ paths, plant count, and plant complexity were not changed.

### Changes

Enhanced optional timing behind:

```bash
INFINIGEN_PROFILE_PLANT_ASSETS=1
```

The CSV now records the concrete monocot factory class, container duration,
leaf / stem / branch timing when safely observable, modifier apply duration,
material and node-group prefix tops, and the existing before/after datablock
counts. The timing remains default-off.

Updated:

```text
scripts/bench_plant_assets_factory.py
scripts/analyze_plant_assets_timing.py
docs/PLANT_POPULATE_INVESTIGATION.md
```

### Benchmark

Command:

```bash
INFINIGEN_PROFILE_PLANT_ASSETS=1 \
python scripts/bench_plant_assets_factory.py \
  --samples 30 \
  --seed 0 \
  --output_folder outputs/bench_plant_assets_deep
```

Result: `30/30` samples, `0` failures. CSV:

```text
outputs/bench_plant_assets_deep/infinigen_plant_assets_timing.csv
```

Measured total was `127.811s`, average `4.260s`, and max `10.106s`.
`plant_spawn_duration` was `99.939s` / `78.2%`. Concrete monocot geometry was
the main cost: leaf generation `50.844s`, branch generation `20.284s`, and
stem generation `16.744s`. Created datablocks were `1,142` meshes, `30`
materials, `0` textures, `176` node groups, and `1,022` objects.

Top concrete monocot factories by total duration were
`VeratrumMonocotFactory`, `GrassesMonocotFactory`, `WheatMonocotFactory`, and
`MaizeMonocotFactory`.

### Judgment

Material reuse is not the first Plant target in this benchmark. Node-group
reuse might be useful only for fixed helper groups, but the larger speed lever
appears to be leaf / stem / branch geometry template work. The first future
Plant optimization switch to consider is:

```bash
INFINIGEN_REUSE_PLANT_TEMPLATE_GEOMETRY=1
```

It must remain opt-in, narrow, and quality-gated because plant silhouettes and
leaf/stem variation are visually important.

## 2026-06-22 - Standard optimized Isaac static 10-room command

Added `scripts/run_isaac_static_optimized_10room.sh` as the standard command
for the current manually checked Isaac Sim static indoor configuration. This
round did not add any optimization and did not change solver behavior,
`batch_remove`, `LargeShelfFactory` reuse, `NatureShelfTrinketsFactory` fast
pose behavior, door logic, or gin defaults.

The current recommended Isaac Sim static environment configuration is:

```text
INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1
INFINIGEN_REUSE_LARGESHELF_CHILD_NODEGROUPS=1
INFINIGEN_FAST_NATURE_TRINKET_STABLE_POSE=1
compose_indoors.terrain_enabled=False
home_room_constraints.has_fewer_rooms=False
restrict_solving.solve_max_rooms=10
populate_doors.door_chance=0
```

The generated and exported USD/USDC scene from this configuration has now been
manually inspected in Isaac Sim. Visual quality was good, with no obvious
quality issue. The target for this configuration is Isaac static scene
quality-preserving behavior, not bitwise-identical output. The practical gate
is realistic rendering, enough environment complexity, no obvious flying
objects, no obvious severe intersections, no obvious black materials, door
openings retained without door panels, and USD/USDC import working in Isaac
Sim.

The three opt-in acceleration points remain default-off in Infinigen itself:

```text
batch_remove node group deletion
LargeShelf child node group reuse
NatureShelf shell-like fast stable pose
```

Use the script to run different seeds, clean a seed output, or export USDC
without hand-copying the long command.

## 2026-06-22 - Populate multi-track profiling and expanded shell fast pose

### Round Goal

Advance four independent populate-stage lines without mixing their switches.
P0 extends the opt-in NatureShelf shell fast-pose experiment. P1/P2/P3 add
source investigation and timing only. No solver behavior, proposal /
accept / reject logic, room count, clutter count, default behavior,
concurrency, or C++ path was changed.

### P0 NatureShelf Expanded Shell Fast Pose

Extended the opt-in fast stable-pose allow-list behind:

```bash
INFINIGEN_FAST_NATURE_TRINKET_STABLE_POSE=1
```

The allow-list now includes:

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

Expanded shell A/B used seed `0`, `100` samples, and:

```text
--base-factory-filter ClamFactory,MusselFactory,ScallopFactory,ConchFactory,AugerFactory,VoluteFactory,MolluskFactory
```

CSVs:

```text
outputs/bench_nature_fast_pose_expanded_shell/baseline/infinigen_nature_shelf_trinkets_timing.csv
outputs/bench_nature_fast_pose_expanded_shell/candidate_fast/infinigen_nature_shelf_trinkets_timing.csv
```

Result:

| metric | baseline | candidate |
| --- | ---: | ---: |
| rows | 100 | 100 |
| failures | 0 | 0 |
| total duration | `153.955s` | `8.200s` |
| speedup |  | `18.8x` |
| stable pose | `120.248s` | `0.000s` |
| obj2trimesh | `19.937s` | `0.000s` |
| fast rows | 0 | 100 |
| mesh/object/material delta |  | `0 / 0 / 0` |

Generated small visual check blend:

```text
outputs/bench_nature_fast_pose_expanded_shell/visual_check_fast/nature_shelf_trinkets_bench.blend
```

It is not committed. Manual Blender/Isaac inspection is still required before
any full 10-room quality validation with the expanded fast flag.

### P1 BookStack Timing

Added:

```bash
INFINIGEN_PROFILE_BOOKSTACK=1
```

and:

```text
scripts/analyze_bookstack_timing.py
scripts/bench_bookstack_factory.py
docs/BOOKSTACK_POPULATE_INVESTIGATION.md
```

First 30-sample targeted run:

```text
outputs/bench_bookstack/infinigen_bookstack_timing.csv
```

Result: `30/30` benchmark samples, `0` failures, `307` CSV rows, measured CSV
total `4.827s`. Stack rows created `277` materials and `277` node groups
inclusively; nested `BookFactory` rows record the per-book side of the same
work. The benchmark stdout showed `findfont` warnings, but create-asset timing
did not record image growth because cover `Text` materials are built in
`BookFactory.__init__()`. No BookStack optimization was added.

### P2 Plant Timing

Added:

```bash
INFINIGEN_PROFILE_PLANT_ASSETS=1
```

and:

```text
scripts/analyze_plant_assets_timing.py
scripts/bench_plant_assets_factory.py
docs/PLANT_POPULATE_INVESTIGATION.md
```

First 20-sample `LargePlantContainerFactory` targeted run:

```text
outputs/bench_plant_assets/infinigen_plant_assets_timing.csv
```

Result: `20/20` samples, `0` failures, total `81.426s`, avg `4.071s`, max
`11.451s`. The dominant measured substage was `plant_spawn_duration`
(`62.942s`). Created datablocks: `624` meshes, `20` materials, `122` node
groups, and `544` objects. No plant optimization was added.

### P3 Datablock Growth Attribution

Added:

```bash
INFINIGEN_PROFILE_DATABLOCK_GROWTH=1
```

Integrated final-populate CSV:

```text
<output_folder>/infinigen_datablock_growth_timing.csv
```

Fallback:

```text
/tmp/infinigen_datablock_growth_timing.csv
```

Analyzer:

```text
scripts/analyze_datablock_growth.py
```

This records per-factory material, texture, node-group, mesh, object, and
image growth, plus created-name samples and prefix tops. No integrated
10-room sample was run in this round because recent bounded 1800s runs did not
reach final `populate_assets`; this line is instrumentation-ready for the next
bounded or full quality run. No global reuse optimization was added.

### Judgment

P0 is the only line in this round that produced a speedup. It should not move
to a full 10-room Isaac static quality validation until the expanded shell
visual check blend passes manual inspection. P1/P2/P3 are timing /
investigation only and should feed the next profiling decision without
reducing clutter complexity or enabling default optimizations.

## 2026-06-22 - Opt-in fast stable pose for shell trinkets

### Round Goal

Add a first opt-in `NatureShelfTrinketsFactory` fast stable-pose experiment for
low-risk shell trinkets only. Default behavior must remain unchanged. No
solver behavior, random-flow control, room count, clutter count, batch-remove
behavior, LargeShelf reuse behavior, concurrency, or C++ code was changed.

### Changes

Added:

```bash
INFINIGEN_FAST_NATURE_TRINKET_STABLE_POSE=1
```

When unset, `NatureShelfTrinketsFactory` uses the original
`obj2trimesh()` plus `trimesh.poses.compute_stable_poses()` path. When set,
only these wrapped base factories use the fast path:

```text
ClamFactory
MusselFactory
ScallopFactory
```

Fast mode is deliberately not applied to:

```text
CoralFactory
HerbivoreFactory
CarnivoreFactory
PineconeFactory
ConchFactory
AugerFactory
VoluteFactory
MolluskFactory
BlenderRockFactory
BoulderFactory
```

For the three shell factories, fast mode skips `obj2trimesh()` and
`compute_stable_poses()`, preserves `base_factory.spawn_asset()`, and leaves
the existing scale / bbox bottom-alignment placement path in place. It does
not create or remove objects, meshes, materials, textures, or node groups. It
does not sample any new random yaw, so there is no intentional random-number
consumption change.

Extended `INFINIGEN_PROFILE_NATURE_SHELF_TRINKETS=1` CSV rows with:

```text
fast_stable_pose_enabled
fast_stable_pose_used
stable_pose_mode
fast_stable_pose_duration
skipped_compute_stable_poses
```

Updated `scripts/analyze_nature_shelf_trinkets.py` to report original vs fast
mode counts and duration, skipped compute counts, per-base factory speedups,
failures, and datablock / object count deltas. It can now compare two CSVs:

```bash
python scripts/analyze_nature_shelf_trinkets.py baseline.csv candidate.csv
```

Updated `scripts/bench_nature_shelf_trinkets_factory.py` so
`--keep-blend true` preserves generated samples in a small grid for manual
visual inspection.

### Benchmark Result

An unfiltered 100-sample baseline completed with `100` rows and `0` failures.
The matching unfiltered candidate was started with fast mode enabled, but it
stalled on sample 14, a non-fast `CoralFactory` row, and was terminated after
the Python signal timeout did not interrupt the underlying computation. Treat
that candidate as incomplete and not as fast-mode speed evidence.

A shell-only A/B was then run with:

```bash
--base-factory-filter ClamFactory,MusselFactory,ScallopFactory
```

The filter uses seed rejection and does not override the
`NatureShelfTrinketsFactory` base-factory choice.

Shell-only CSVs:

```text
outputs/bench_nature_shelf_trinkets_pose_ab/baseline_shell/infinigen_nature_shelf_trinkets_timing.csv
outputs/bench_nature_shelf_trinkets_pose_ab/candidate_fast_shell/infinigen_nature_shelf_trinkets_timing.csv
```

Shell-only result:

| metric | baseline | candidate |
| --- | ---: | ---: |
| CSV data rows | 100 | 100 |
| successful samples | 100 | 100 |
| failures | 0 | 0 |
| total duration | `268.269s` | `10.937s` |
| `stable_pose_duration` | `217.894s` | `0.000s` |
| `obj2trimesh_duration` | `31.233s` | `0.000s` |
| fast rows used | 0 | 100 |
| skipped compute rows | 0 | 100 |
| meshes created | 100 | 100 |
| objects created | 100 | 100 |
| materials created | 0 | 0 |

Per base factory:

| base factory | baseline total | candidate total | speedup |
| --- | ---: | ---: | ---: |
| `ClamFactory` | `128.370s` | `4.173s` | `30.8x` |
| `MusselFactory` | `76.398s` | `3.594s` | `21.3x` |
| `ScallopFactory` | `63.502s` | `3.171s` | `20.0x` |

### Visual Check Artifact

Generated a small fast-mode visual check blend:

```text
outputs/bench_nature_shelf_trinkets_pose_ab/visual_check_fast_shell/nature_shelf_trinkets_bench.blend
```

It contains 12 fast-mode Clam / Mussel / Scallop samples arranged in a grid
with wire placeholders. This file is not committed. It still needs manual
Blender or Isaac inspection for floating, inverted shells, bad bottom
alignment, support-surface intersection, and unacceptable visual orientation.

### Judgment

The shell-only A/B shows a very large timing win and no benchmark failures or
datablock / object count anomalies within the fast-mode scope. It is worth
entering a manual visual gate next. If the small blend looks acceptable, the
next full-scene quality gate should run with:

```text
INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1
INFINIGEN_REUSE_LARGESHELF_CHILD_NODEGROUPS=1
INFINIGEN_FAST_NATURE_TRINKET_STABLE_POSE=1
populate_doors.door_chance=0
```

Do not include Coral in this fast mode yet. Do not pursue exact stable-pose
cache before a later sample shows repeated exact candidate keys. Do not reduce
clutter count or add concurrency.

## 2026-06-22 - NatureShelfTrinkets stable pose complexity

### Round Goal

Enhance `NatureShelfTrinketsFactory` timing and the targeted benchmark to
record stable-pose input mesh complexity and cache-candidate details. No
optimization was added, no stable pose was skipped, no stable-pose cache was
used, no NatureShelfTrinkets generation behavior was changed, no random flow
or solver behavior was changed, no clutter was removed, no concurrency was
introduced, and no C++ path was connected.

### Changes

Extended the optional timing behind:

```bash
INFINIGEN_PROFILE_NATURE_SHELF_TRINKETS=1
```

New CSV fields include:

```text
mesh_vertex_count
mesh_face_count
mesh_edge_count
bbox_min_x/y/z
bbox_max_x/y/z
bbox_extent_x/y/z
obj2trimesh_duration
stable_pose_count
stable_pose_best_prob
stable_pose_cache_candidate_key
```

The cache candidate key is diagnostic only. It includes the wrapped base
factory, mesh complexity, bbox extent, and a hash of the stable-pose input
mesh. It does not change generation, does not cache any result, and does not
change the selected stable pose.

Updated:

```text
scripts/bench_nature_shelf_trinkets_factory.py
scripts/analyze_nature_shelf_trinkets.py
```

The benchmark now defaults to `--samples 100`, supports
`--csv-path`, supports `--keep-blend true/false`, and supports optional
`--base-factory-filter` through seed rejection. The filter does not override
`NatureShelfTrinketsFactory` base-factory selection.

The analyzer now reports stable-pose duration vs mesh complexity, average
vertex / face counts by base factory, slowest stable-pose rows with bbox
extent and pose count, and repeated `stable_pose_cache_candidate_key` signals.

### Benchmark Result

Run:

```bash
INFINIGEN_PROFILE_NATURE_SHELF_TRINKETS=1 \
python scripts/bench_nature_shelf_trinkets_factory.py \
  --samples 100 \
  --seed 0 \
  --output_folder outputs/bench_nature_shelf_trinkets_100
```

CSV:

```text
outputs/bench_nature_shelf_trinkets_100/infinigen_nature_shelf_trinkets_timing.csv
```

Result:

| metric | value |
| --- | ---: |
| CSV data rows | 100 |
| successful samples | 100 |
| failed samples | 0 |
| total measured `create_asset` duration | `177.305s` |
| average duration | `1.773s` |
| max duration | `7.040s` |

Substage split:

| substage | total | share |
| --- | ---: | ---: |
| `stable_pose_duration` | `95.971s` | `54.1%` |
| `obj2trimesh_duration` | `26.151s` | `14.7%` |
| stable-pose pipeline | `122.121s` | `68.9%` |
| `base_factory_spawn_duration` | `46.610s` | `26.3%` |

Base factory duration leaders:

| base factory | count | total | avg | max |
| --- | ---: | ---: | ---: | ---: |
| `ClamFactory` | 11 | `49.970s` | `4.543s` | `7.040s` |
| `MusselFactory` | 12 | `27.341s` | `2.278s` | `3.136s` |
| `CoralFactory` | 5 | `25.904s` | `5.181s` | `6.514s` |
| `HerbivoreFactory` | 11 | `18.575s` | `1.689s` | `1.967s` |
| `CarnivoreFactory` | 14 | `14.111s` | `1.008s` | `1.287s` |

Stable-pose mesh complexity:

| base factory | avg vertices | avg faces | stable total | stable avg |
| --- | ---: | ---: | ---: | ---: |
| `ClamFactory` | 262,648 | 528,384 | `44.381s` | `4.035s` |
| `MusselFactory` | 264,196 | 528,384 | `21.202s` | `1.767s` |
| `CoralFactory` | 1,719,138 | 3,445,702 | `7.209s` | `1.442s` |
| `ConchFactory` | 176,443 | 352,886 | `6.746s` | `0.519s` |

Across `75` stable-pose rows, average mesh complexity was `298,988` vertices
and `599,225` faces. Correlation between `stable_pose_duration` and vertex /
face count was only `0.131`; correlation with `stable_pose_count` was `0.275`.
The slowest `compute_stable_poses()` rows were `ClamFactory` samples. The
slowest `CoralFactory` rows were often dominated by `obj2trimesh_duration` on
multi-million-face meshes.

Cache signal:

| metric | value |
| --- | ---: |
| candidate keys | 75 |
| unique candidate keys | 75 |
| repeated candidate keys | 0 |

Created datablocks:

| kind | total |
| --- | ---: |
| materials | 123 |
| textures | 0 |
| node groups | 142 |
| meshes | 673 |
| objects | 214 |

Material and node-group creation still mostly came from creature paths, but
materials / textures / node groups were not the first duration bottleneck in
this benchmark.

### Judgment

`NatureShelfTrinketsFactory`'s new measured internal bottleneck is the
stable-pose pipeline, not material / texture / node-group creation. Exact
stable-pose cache is not recommended yet because the diagnostic mesh-hash key
did not repeat in the 100-sample run. If a speed experiment is attempted next,
it should be a separate opt-in stable-pose simplification or mesh-complexity
experiment, starting with `ClamFactory` and `MusselFactory`. `CoralFactory`
should be investigated separately for `obj2trimesh` conversion cost.

Do not reduce clutter count, do not add concurrency, and do not change solver
or random flow. Any future cache or simplification must be opt-in and must pass
a visual-quality gate.

## 2026-06-22 - NatureShelfTrinkets targeted microbenchmark

### Round Goal

Add a targeted `NatureShelfTrinketsFactory` microbenchmark to measure
`create_asset()` and wrapped base-factory cost without running another full
10-room indoor generation. No optimization was added, no small objects were
removed, no generation logic or solver behavior was changed, no random number
flow was changed, no concurrency was introduced, and no C++ path was connected.

### Changes

Added:

```text
scripts/bench_nature_shelf_trinkets_factory.py
```

The benchmark defaults to `30` samples, seed `0`, and:

```text
outputs/bench_nature_shelf_trinkets
```

Each sample creates a `NatureShelfTrinketsFactory(factory_seed)`, creates a
placeholder, calls `create_asset(inst_seed, placeholder=placeholder)`, records
the existing NatureShelfTrinkets timing row, and deletes generated objects
before continuing. This is an internal microbenchmark only; it does not
represent complete-scene walltime or Isaac quality.

Added a safe CSV override for targeted runs:

```bash
INFINIGEN_NATURE_SHELF_TRINKETS_TIMING_CSV=/path/to/infinigen_nature_shelf_trinkets_timing.csv
```

Default timing behavior is unchanged when the variable is unset.

Updated:

```text
scripts/analyze_nature_shelf_trinkets.py
```

The analyzer now summarizes by `base_factory_class`, including total / average
/ max duration, `base_factory_spawn_duration`, `stable_pose_duration`,
`apply_modifiers_duration`, created materials, textures, node groups, meshes,
and objects. It also reports slowest base factories, slowest samples,
datablock creation top lists, and whether `stable_pose` or
`base_factory.spawn_asset` is the primary measured cost.

### Benchmark Result

The full 10-room bounded sample from the previous round timed out after 1800s
inside `[solve_large]` and never reached `populate_assets`, so it could not
produce NatureShelfTrinkets timing rows. The targeted benchmark avoided that
full-scene cost.

Run:

```bash
INFINIGEN_PROFILE_NATURE_SHELF_TRINKETS=1 \
python scripts/bench_nature_shelf_trinkets_factory.py \
  --samples 30 \
  --seed 0 \
  --output_folder outputs/bench_nature_shelf_trinkets
```

CSV:

```text
outputs/bench_nature_shelf_trinkets/infinigen_nature_shelf_trinkets_timing.csv
```

Result:

| metric | value |
| --- | ---: |
| CSV data rows | 30 |
| successful samples | 30 |
| failed samples | 0 |
| total measured `create_asset` duration | `47.566s` |
| average duration | `1.586s` |
| max duration | `5.477s` |

Base factory duration leaders:

| base factory | count | total | avg | max |
| --- | ---: | ---: | ---: | ---: |
| `CoralFactory` | 3 | `13.743s` | `4.581s` | `5.477s` |
| `ClamFactory` | 3 | `7.924s` | `2.641s` | `4.305s` |
| `MusselFactory` | 3 | `6.518s` | `2.173s` | `2.926s` |
| `HerbivoreFactory` | 4 | `6.080s` | `1.520s` | `1.575s` |
| `ConchFactory` | 5 | `4.142s` | `0.828s` | `0.907s` |
| `CarnivoreFactory` | 5 | `3.909s` | `0.782s` | `0.880s` |

Substage split:

| substage | total | share |
| --- | ---: | ---: |
| `stable_pose_duration` | `32.143s` | `67.6%` |
| `base_factory_spawn_duration` | `15.275s` | `32.1%` |
| `apply_modifiers_duration` | `0.003s` | about `0.0%` |

Created datablocks:

| kind | total | avg | max |
| --- | ---: | ---: | ---: |
| materials | 46 | 1.533 | 5 |
| textures | 0 | 0.000 | 0 |
| node groups | 68 | 2.267 | 32 |
| meshes | 242 | 8.067 | 36 |
| objects | 75 | 2.500 | 11 |

### Judgment

In this 30-sample targeted benchmark, `stable_pose_duration` is the primary
measured cost and `base_factory.spawn_asset` is secondary. The strongest next
lead is stable-pose input geometry for `CoralFactory`, followed by
`ClamFactory` and `MusselFactory`. Creature paths are still the main
material/node-group creation signal, so opt-in material or template reuse may
be worth a later separate experiment, but it is not the first duration target
from this sample.

Keep `BookStackFactory` and `LargePlantContainerFactory` as second-priority
populate targets. Do not add concurrency, reduce scene complexity, change the
solver, or change random flow in the next investigation.

## 2026-06-22 - NatureShelfTrinkets populate investigation

### Round Goal

Investigate `NatureShelfTrinketsFactory` as the first populate clutter target
without adding an optimization, reducing small object count, changing
generation logic, changing solver behavior, changing random number flow,
running concurrent generation, or connecting C++.

The then-current Isaac-inspected configuration was:

```text
INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1
INFINIGEN_REUSE_LARGESHELF_CHILD_NODEGROUPS=1
restrict_solving.solve_max_rooms=10
populate_doors.door_chance=0
```

### Findings

The bottleneck focus has moved from solver / GC mechanics toward final
populate clutter. A recent complete 10-room proxy log showed
`populate_assets` at about `3296.8s` / `54.9m` for `222` items. The top proxy
factory was `NatureShelfTrinketsFactory` with about `1921.3s` across `76`
items. `BookStackFactory` and `LargePlantContainerFactory` are the next
populate targets after NatureShelfTrinkets.

`NatureShelfTrinketsFactory` is defined in:

```text
infinigen/assets/objects/elements/nature_shelf_trinkets/generate.py
```

The final populate path is:

```text
populate_state_placeholders(final=True)
  os.generator.spawn_asset(i=inst_seed, loc=placeholder.location, rot=...)
    AssetFactory.spawn_asset()
      NatureShelfTrinketsFactory.create_placeholder()
      NatureShelfTrinketsFactory.create_asset()
        base_factory.spawn_asset(np.random.randint(1e7), ...)
        optional join_objects(asset.children)
        apply_transform / apply_modifiers
        optional obj2trimesh() + trimesh.poses.compute_stable_poses()
        scale and reposition into the placeholder dimensions
```

The wrapper samples one base factory from coral, rock, pinecone, mollusk, and
creature factories. The wrapper itself does not directly load font, text, or
image assets. It does call wrapped factories that create procedural shader
materials, Blender texture datablocks, meshes, and in creature paths many
geometry node groups / part objects.

### Changes

Added investigation documentation:

```text
docs/NATURE_SHELF_TRINKETS_INVESTIGATION.md
```

Added optional timing behind:

```bash
INFINIGEN_PROFILE_NATURE_SHELF_TRINKETS=1
```

When unset, default behavior is unchanged. When set, each
`NatureShelfTrinketsFactory.create_asset()` call writes one CSV row to:

```text
<output_folder>/infinigen_nature_shelf_trinkets_timing.csv
```

If the solver output folder cannot be discovered, it falls back to:

```text
/tmp/infinigen_nature_shelf_trinkets_timing.csv
```

The row records total duration, wrapped base factory class, placeholder name,
substage timings, before/after Blender datablock counts, created material /
texture / node-group / mesh / object counts, created material / texture /
node-group names, child-object counts, success, and error type.

Added:

```text
scripts/analyze_nature_shelf_trinkets.py
```

The script reports total / average / max duration, created datablock summaries,
substage totals, duration by wrapped base factory, slowest instances, repeated
material / texture / node-group name signals, and a recommended next
optimization direction.

### Short Sampling Attempt

A bounded 1800s sample was attempted with:

```text
seed 0
task coarse
fast_solve.gin
compose_indoors.terrain_enabled=False
home_room_constraints.has_fewer_rooms=False
restrict_solving.solve_max_rooms=10
populate_doors.door_chance=0
INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1
INFINIGEN_REUSE_LARGESHELF_CHILD_NODEGROUPS=1
INFINIGEN_PROFILE_NATURE_SHELF_TRINKETS=1
```

The host `python` lacked `bpy`, and the host Blender Python lacked `yaml`.
The valid attempt therefore ran in the `infinigen` container from a temporary
copy of the current host checkout at `/tmp/infinigen_profile_run`, writing to
the mounted output folder:

```text
outputs/profile_nature_shelf_trinkets_seed0_1800_container/coarse
```

The run exited with timeout code `124` at 1800s. It did not reach
`populate_assets` or `NatureShelfTrinketsFactory.create_asset()`, so no
`infinigen_nature_shelf_trinkets_timing.csv` was produced. The log was still
inside `[solve_large]`, dominated near the end by repeated
`KitchenIslandFactory` proposals. The last clutter report before timeout
showed:

| metric | value |
| --- | ---: |
| state size | 111 |
| trimesh objects | 112 |
| Blender objects | 465 |
| meshes | 464 |
| materials | 7,154 |
| textures | 7,154 |

No traceback, OOM, killed, or segfault marker was found in this bounded
attempt. Treat it only as evidence that the 1800s window is too short to
collect final NatureShelfTrinkets populate rows for this configuration.

### Judgment

`NatureShelfTrinketsFactory` is worth first-class populate instrumentation
because it dominates the proxy populate timing and wraps several heavy
procedural asset families. Material / texture / node-group reuse is plausible
for a later opt-in experiment, but only after timing identifies repeated
templates and a separate quality gate protects visual complexity, randomness,
and material diversity.

Do not add concurrency. Do not reduce scene complexity or small-object counts
unless a later quality gate explicitly allows that tradeoff. Do not change
solver behavior or random number flow while investigating this populate path.

## 2026-06-21 - Opt-in LargeShelf child node group reuse

### Round Goal

Implement the first opt-in `LargeShelfFactory` child node group reuse
experiment without changing default behavior, solver behavior, random number
flow, proposal / accept / reject logic, `batch_remove` behavior, door logic,
concurrent execution, or C++ code. Run only a bounded short timing sample and
decide whether the opt-in path is worth full quality validation.

### Changes

Added:

```bash
INFINIGEN_REUSE_LARGESHELF_CHILD_NODEGROUPS=1
```

When unset, default behavior is unchanged. When set, `large_shelf.py` uses a
module-level cache for these child node groups only:

- `nodegroup_screw_head`
- `nodegroup_side_board`
- `nodegroup_bottom_board`
- `nodegroup_back_board`

The cache key is the function name for these fixed-structure node groups. The
cache validates that the cached Blender node group datablock is still live
before returning it. If the datablock was removed, the entry is discarded and
the node group is recreated.

The first experiment intentionally does not reuse:

- top-level `geometry_nodes`, because it embeds per-object arrays, scalar
  defaults, and material objects.
- `nodegroup_division_board`, because it participates in the tag-support path
  and its timing is inclusive of nested child work.
- `nodegroup_tagged_cube`, because it writes the `TAG_support_surface`
  attribute and is tied to MaskTag/tag lifecycle risk.

Extended `INFINIGEN_PROFILE_SHELF_NODEGROUPS=1` CSV output with
`reuse_enabled`, `cache_hit`, `cache_key`, `cache_size`, and
`returned_nodegroup_name`. Updated `scripts/analyze_shelf_nodegroups.py` to
report cache hits, misses, hit rate, estimated saved create calls, and reused
prefix summaries.

### Short Timing Sample

Both runs used:

```text
seed 0
task coarse
fast_solve.gin
compose_indoors.terrain_enabled=False
home_room_constraints.has_fewer_rooms=False
restrict_solving.solve_max_rooms=10
populate_doors.door_chance=0
INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1
INFINIGEN_PROFILE_SHELF_NODEGROUPS=1
timeout 900s
```

Candidate additionally used:

```bash
INFINIGEN_REUSE_LARGESHELF_CHILD_NODEGROUPS=1
```

Both runs exited with timeout code `124` at 900s. This is a short timing sample
only, not a complete profile and not a quality gate. No traceback, OOM, or
segfault was observed.

CSVs:

```text
outputs/profile_shelf_reuse_ab/baseline/coarse/infinigen_shelf_nodegroup_timing.csv
outputs/profile_shelf_reuse_ab/candidate/coarse/infinigen_shelf_nodegroup_timing.csv
```

| metric | baseline | candidate |
| --- | ---: | ---: |
| CSV data rows | 5,918 | 5,918 |
| `LargeShelfFactory` spawns | 163 | 163 |
| actual node groups created | 5,918 | 3,363 |
| mean actual node groups per spawn | 36.307 | 20.632 |
| `spawn_summary` total duration | 60.096s | 36.718s |
| cache hits | 0 | 2,555 |
| cache misses | 0 | 86 |
| cache hit rate | 0.000% | 96.744% |

Target prefix total duration:

| prefix | baseline | candidate |
| --- | ---: | ---: |
| `nodegroup_screw_head` | 14.993s | 0.095s |
| `nodegroup_side_board` | 3.400s | 0.144s |
| `nodegroup_bottom_board` | 2.001s | 0.153s |
| `nodegroup_back_board` | 1.023s | 0.146s |

The four target prefixes dropped from `21.417s` to `0.538s`, and actual node
group creation dropped by `2,555`, matching the cache hit count.

### Judgment

The short sample shows a clear creation-cost reduction and no crash signal, so
the opt-in child reuse path is worth a full 10-room Isaac static quality
validation. Do not expand reuse before that validation passes.

The next validation should keep the Isaac static environment defaults:

```text
INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1
INFINIGEN_REUSE_LARGESHELF_CHILD_NODEGROUPS=1
restrict_solving.solve_max_rooms=10
populate_doors.door_chance=0
```

`batch_remove` remains the current main acceleration switch because it reduces
deletion cost. LargeShelf child reuse addresses repeated creation cost that
`batch_remove` does not solve. Do not continue bbox C++ work, do not run
concurrent benchmarks, and do not change door logic.

## 2026-06-21 - LargeShelf node group timing sample

### Round Goal

Run a shelf node group timing sample and analyze whether `LargeShelfFactory`
child node group reuse is worth a future opt-in experiment. Do not add an
optimization, do not change `LargeShelf` node group logic, do not do node
group reuse, do not change solver behavior, do not change proposal / accept /
reject logic, do not change `batch_remove`, do not run concurrent benchmarks,
and do not commit generated outputs.

### Run

The requested `/opt/infinigen` container checkout was stale during this round,
so its attempt is not used as timing evidence. The valid run used the current
host checkout at:

```text
9f183b83346acb90c66c9a39aa48c7090ce01287
```

Command characteristics:

```text
INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1
INFINIGEN_PROFILE_SHELF_NODEGROUPS=1
seed 0
task coarse
fast_solve.gin
compose_indoors.terrain_enabled=False
home_room_constraints.has_fewer_rooms=False
restrict_solving.solve_max_rooms=10
populate_doors.door_chance=0
output_folder outputs/profile_shelf_nodegroups_seed0/coarse
```

The valid run timed out at `3600s`, so this is a bounded sample rather than a
complete coarse profile.

### CSV

```text
outputs/profile_shelf_nodegroups_seed0/coarse/infinigen_shelf_nodegroup_timing.csv
```

| metric | value |
| --- | ---: |
| file lines including header | 24,525 |
| data rows | 24,524 |
| `nodegroup_create` rows | 23,083 |
| `spawn_summary` rows | 1,441 |
| LargeShelfFactory spawns | 1,441 |
| mean node groups created per spawn | 17.019 |
| total `spawn_summary` duration | 549.705s |

Prefix total duration:

| prefix | calls | total duration | mean duration |
| --- | ---: | ---: | ---: |
| `nodegroup_division_board` | 5,629 | 278.151s | 0.049s |
| `nodegroup_screw_head` | 5,629 | 125.246s | 0.022s |
| `nodegroup_side_board` | 3,170 | 43.601s | 0.014s |
| `nodegroup_tagged_cube` | 5,629 | 37.736s | 0.007s |
| `nodegroup_bottom_board` | 1,585 | 25.735s | 0.016s |
| `nodegroup_back_board` | 1,441 | 23.490s | 0.016s |

Slowest `LargeShelfFactory` spawns:

| spawn_id | duration | created node groups |
| --- | ---: | ---: |
| 152 | 1.122s | 74 |
| 133 | 1.070s | 65 |
| 132 | 1.051s | 65 |
| 145 | 1.002s | 65 |
| 153 | 0.985s | 65 |
| 130 | 0.982s | 65 |
| 128 | 0.971s | 65 |
| 159 | 0.936s | 47 |
| 144 | 0.885s | 56 |
| 117 | 0.830s | 56 |

### Judgment

The first-round child reuse candidates
(`nodegroup_screw_head`, `nodegroup_side_board`,
`nodegroup_bottom_board`, and `nodegroup_back_board`) accounted for
`218.072s`, about `6.1%` of the `3600s` timeout window. This is above the
threshold for a small opt-in reuse experiment.

There is clear repeated-template signal. `nodegroup_division_board`,
`nodegroup_screw_head`, and `nodegroup_tagged_cube` each appeared `5,629`
times; `nodegroup_side_board` appeared `3,170` times;
`nodegroup_bottom_board` appeared `1,585` times; and
`nodegroup_back_board` appeared once per spawn.

Do not start with top-level `geometry_nodes`, `nodegroup_division_board`, or
`nodegroup_tagged_cube`. The top-level graph embeds per-shelf sampled arrays
and materials, while the division/tagged path participates in tag-support
behavior. The first opt-in reuse experiment should start only with
`nodegroup_screw_head`, `nodegroup_side_board`, `nodegroup_bottom_board`, and
`nodegroup_back_board`.

`batch_remove` remains the current main acceleration switch because it reduces
deletion cost. The shelf node group timing sample shows a separate repeated
creation cost that `batch_remove` does not solve. Do not continue bbox C++ work
from the current evidence, do not run concurrent benchmarks, and do not change
door logic. Default Isaac static-environment tests should keep
`populate_doors.door_chance=0` so door panels are not generated while door
openings remain.

### Changes

Documentation only:

- `docs/LARGESHELF_NODEGROUP_INVESTIGATION.md`
- `docs/PROFILE_RESULTS.md`
- `docs/NEXT_STEPS.md`
- `docs/WORKLOG.md`

## 2026-06-21 - LargeShelf node group generation investigation

### Round Goal

Investigate `LargeShelfFactory` repeated shelf node group generation without
adding a reuse optimization, changing solver behavior, changing random number
flow, changing proposal / accept / reject logic, changing `batch_remove`
behavior, running concurrent benchmarks, or connecting C++.

### Findings

`LargeShelfFactory` is defined in
`infinigen/assets/objects/shelves/large_shelf.py`.

The active creation chain is:

```text
LargeShelfBaseFactory.create_asset()
  get_asset_params()
  surface.add_geomod(obj, geometry_nodes, apply=True, input_kwargs=obj_params)
    geometry_nodes(...)
      nodegroup_side_board()
      nodegroup_back_board()
      nodegroup_bottom_board()
      nodegroup_division_board(..., tag_support=True)
        nodegroup_tagged_cube()
        nodegroup_screw_head()
```

All high-frequency shelf child node groups are currently decorated with
`singleton=False`, so each call creates a new `bpy.data.node_groups` datablock.
The repeated prefixes from the GC attribution sample map directly to
`large_shelf.py` and `shelves/utils.py`:
`nodegroup_tagged_cube`, `nodegroup_division_board`,
`nodegroup_screw_head`, `nodegroup_side_board`,
`nodegroup_bottom_board`, and `nodegroup_back_board`.

The child node group functions inspected here do not call random APIs directly.
Per-object variation is supplied through sampled parameters and exposed node
group inputs. `nodegroup_division_board(material, tag_support=False)` accepts a
`material` argument, but the inspected body does not use it; materials are set
in the parent `geometry_nodes` tree with `Nodes.SetMaterial`.

### Changes

Added `docs/LARGESHELF_NODEGROUP_INVESTIGATION.md`.

Added opt-in timing instrumentation behind:

```bash
INFINIGEN_PROFILE_SHELF_NODEGROUPS=1
```

When enabled, `large_shelf.py` writes
`infinigen_shelf_nodegroup_timing.csv` under the solver output folder when
available, otherwise `/tmp`. It records profiled child node group creation
calls, inclusive durations, per-spawn actual node group counts, and prefix
counts. Default behavior remains off.

Added `scripts/analyze_shelf_nodegroups.py` to summarize prefix creation
counts, total and average duration, per-spawn node group counts, and obvious
repeated template signals.

### Judgment

`batch_remove` remains the strongest opt-in deletion-cost switch, but it does
not address duplicate node group creation cost. The next speed investigation
should focus on `LargeShelfFactory` shelf child node group reuse or reduced
duplicate creation, behind a separate opt-in flag and after timing confirms
the creation cost.

Do not continue optimizing bbox C++ from current evidence:
`union_all_bbox` was only about `0.023%` of the measured bbox path. Do not run
concurrent benchmarks for this phase. Do not change door logic; default Isaac
tests should keep `populate_doors.door_chance=0` so no door panels are
generated while door openings remain.

## 2026-06-20 - Full baseline determinism check

### Round Goal

Run one full 10-room baseline repeat, without source changes, new
optimizations, batch-remove behavior changes, walltime benchmarking, gin
changes, profiling timing env vars, or committed generated outputs. Compare it
against the existing full baseline from the batch-remove A/B to determine
whether the current strict JSON gate is deterministic for the baseline itself.

Existing baseline A:

```text
outputs/gc_batch_remove_equiv/baseline/coarse
```

New baseline B:

```text
outputs/determinism_full_baseline_b/coarse
```

The baseline B command used seed `0`, task `coarse`, `fast_solve.gin`,
`compose_indoors.terrain_enabled=False`,
`home_room_constraints.has_fewer_rooms=False`, and
`restrict_solving.solve_max_rooms=10`. The environment explicitly left
`INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS` unset and did not enable
`INFINIGEN_PROFILE_TIMING`, `INFINIGEN_PROFILE_GC`,
`INFINIGEN_PROFILE_ASSET_FACTORY`, `INFINIGEN_PROFILE_BBOX`, or
`INFINIGEN_GC_NODE_GROUP_INTERVAL`.

### Baseline B Result

The full baseline B run completed with exit code `0`:

| stage | time |
| --- | ---: |
| solve_large | 1:43:27.660911 |
| solve_medium | 0:49:11.966927 |
| solve_small | 0:39:34.920525 |
| populate_assets | 1:04:21.216173 |
| MAIN TOTAL | 4:25:03.044391 |

No timeout, traceback, OOM, killed, or segmentation fault marker was found.
Blender printed a small non-fatal `Not freed memory blocks` shutdown message
after saving.

### JSON Compare

Command:

```bash
python scripts/compare_indoor_outputs.py \
  outputs/gc_batch_remove_equiv/baseline/coarse \
  outputs/determinism_full_baseline_b/coarse
```

Result:

```text
matched_json_file_count: 2
missing_files: 0
extra_files: 0
DIFFERENT MaskTag.json numeric_max_abs_diff=1
  $.back.bottom: left 22, right 21
  $.front.top: left 21, right 22
SAME solve_state.json numeric_max_abs_diff=0
numeric_max_abs_diff: 1
FINAL: FAIL
```

This is the same `MaskTag.json` label-ID swap previously observed in the full
baseline-vs-batch A/B.

### Static Blend Diagnostic

`scripts/compare_blend_static_scene.py` was run as a diagnostic only. It is not
the deciding gate for this round because the single-room baseline A/A already
showed saved `.blend` static-scene instability.

Result summary:

```text
STATIC_SCENE_FAIL
USD_RELEVANT_DIFF: yes
UNUSED_DATABLOCK_DIFF: no
UNUSED_DATABLOCK_DIFF_ONLY: no
DIFF_CLASS: USD_RELEVANT_DIFF
static_scene_diff_count: 60
unused_datablock_diff_count: 0
```

Both blends had 809 objects, the same object type counts, 744 linked mesh
datablocks, 1165 linked materials, 163 linked node groups, 2139 total node
groups, and 1977 unused node groups. The differences were linked scene
differences, including `NatureShelfTrinketsFactory` mesh vertex/edge/polygon
counts and small pillow/towel transform differences.

### Judgment

The full 10-room baseline is not deterministic under the current strict JSON
gate: `solve_state.json` is stable, but `MaskTag.json` can swap the
`back.bottom` and `front.top` tag label IDs `21` and `22` even without
`INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1`.

Therefore the earlier full baseline-vs-batch `MaskTag.json` difference is not,
by itself, evidence that batch remove changed generation behavior. The saved
blend static-scene differences also cannot be used alone as a batch-remove
rejection reason, because baseline-vs-baseline now fails the static scene
diagnostic as well.

This does not validate batch remove. The opt-in candidate still has not passed
an agreed relevant equivalence gate, and it must remain opt-in. Do not run
walltime for acceptance, do not mainline batch remove, and do not relax
`scripts/compare_indoor_outputs.py` in the same round. The next work should
define or root-cause the baseline nondeterminism, especially the MaskTag label
ID insertion order and saved-blend linked-scene variation, before using the
strict gate to judge batch remove.

## 2026-06-20 - Determinism and static blend diagnostics

### Round Goal

Add diagnostics to decide whether saved `.blend` static-scene differences in
the full 10-room batch-remove A/B are introduced by
`INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1` or can appear in same-seed baseline
A/A runs. Do not add an optimization, change batch-remove behavior, change gin,
change solver flow, change random number/proposal/accept-reject behavior, run
walltime, or commit generated outputs.

### Changes

Added `scripts/compare_blend_static_scene.py`.

The script accepts either two `.blend` files or two coarse output folders
containing `scene.blend`. When run from normal Python it re-executes itself
under Blender background mode using `BLENDER_BIN`, `blender` on PATH, or the
repo-local `blender/blender`. It opens the blends read-only and does not save.

It compares a USD/Isaac-relevant linked static scene summary:

- object count, object names, object type, parent, render/viewport visibility
- object location, rotation, scale, and world matrix with tolerance
- per-object mesh datablock name and vertex/edge/polygon counts
- per-object material slot names and linked material names
- linked node group names reachable from object modifiers and material node
  trees

It also reports unused mesh/material/node group datablocks separately. Unused
datablock differences are not treated as static scene mismatches unless linked
scene data also differs. Final output includes `STATIC_SCENE_PASS` or
`STATIC_SCENE_FAIL`, `USD_RELEVANT_DIFF`, `UNUSED_DATABLOCK_DIFF`, and
`UNUSED_DATABLOCK_DIFF_ONLY`.

Added `scripts/run_determinism_ablation.sh`.

The script runs same-seed A/A pairs for the current indoor coarse target. It
supports:

```bash
PYTHON_BIN=...
EXPERIMENT_TIMEOUT_SECONDS=...
EXPERIMENT_SMOKE_SINGLE_ROOM=1
RUN_BASELINE_AA=1
RUN_CANDIDATE_AA=auto
```

The normal mode uses seed `0`, task `coarse`, `fast_solve.gin`,
`compose_indoors.terrain_enabled=False`,
`home_room_constraints.has_fewer_rooms=False`, and
`restrict_solving.solve_max_rooms=10`. Smoke mode adds `singleroom.gin`, sets
`home_room_constraints.has_fewer_rooms=True`, and sets
`restrict_solving.solve_max_rooms=1`. Baseline A/A runs with
`INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS` unset. Candidate A/A runs with
`INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1`; in `auto` mode it runs by default
only for smoke.

### Smoke Result

Command:

```bash
EXPERIMENT_SMOKE_SINGLE_ROOM=1 \
EXPERIMENT_TIMEOUT_SECONDS=3600 \
PYTHON_BIN=/home/ubuntu22/miniconda3/envs/infinigen/bin/python \
bash scripts/run_determinism_ablation.sh
```

The script exited with status `1` because static blend comparison failed, not
because generation failed. All four generation runs completed:

| pair | run | `MAIN TOTAL` |
| --- | --- | ---: |
| baseline A/A | baseline_a | 0:02:44.950478 |
| baseline A/A | baseline_b | 0:02:43.698548 |
| candidate A/A | candidate_a | 0:02:47.432543 |
| candidate A/A | candidate_b | 0:02:46.587387 |

JSON compare:

| pair | result |
| --- | --- |
| baseline_a vs baseline_b | `FINAL: PASS`, `MaskTag.json` SAME, `solve_state.json` SAME, `numeric_max_abs_diff: 0` |
| candidate_a vs candidate_b | `FINAL: PASS`, `MaskTag.json` SAME, `solve_state.json` SAME, `numeric_max_abs_diff: 0` |

Static blend compare:

| pair | result | diff summary |
| --- | --- | --- |
| baseline_a vs baseline_b | `STATIC_SCENE_FAIL`, `USD_RELEVANT_DIFF: yes` | 23 linked scene diffs, no unused datablock diffs |
| candidate_a vs candidate_b | `STATIC_SCENE_FAIL`, `USD_RELEVANT_DIFF: yes` | 26 linked scene diffs, no unused datablock diffs |

In both pairs, object count was 179 with object type counts
`LIGHT: 19`, `MESH: 154`, `CAMERA: 2`, and `EMPTY: 4`. Linked mesh and material
counts matched. The static differences were linked scene differences, mainly
room wall/floor/ceiling material slot differences and some wall mesh
vertex/edge/polygon count differences. They were not unused-data-block-only
differences.

### Judgment

This smoke shows that same-seed baseline A/A is deterministic for the current
JSON gate, but not deterministic for the saved `.blend` static scene summary.
Therefore the saved blend differences observed in the earlier full
baseline-vs-batch A/B are not yet proven to be introduced by batch remove.

Do not use this as an acceptance result for batch remove. The full 10-room
batch-remove A/B still has a clear runtime signal (`4:11:49.774668` baseline
versus `3:07:38.553985` candidate), but strict equivalence still fails and
batch remove remains opt-in only. Before mainlining or running walltime, the
gate must distinguish strict JSON equivalence, Isaac static scene equivalence,
and GT/mask/segmentation equivalence, with baseline A/A variability measured
first.

The full 10-room A/A was not run in this round because smoke static-scene A/A
already failed. A later round did run the full baseline repeat; see
`2026-06-20 - Full baseline determinism check` above. That later result showed
baseline-vs-baseline also has the `MaskTag.json` label-ID swap and linked
static-scene diagnostic differences, so the strict/static gates need
baseline-calibration before blaming batch remove.

## 2026-06-20 - MaskTag difference investigation

### Round Goal

Investigate the `MaskTag.json` difference from the completed full 10-room
`INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1` A/B without adding an optimization,
changing batch removal behavior, changing solver flow, changing random number
or proposal order, changing accept/reject logic, running walltime, or relaxing
`scripts/compare_indoor_outputs.py`.

### Findings

`MaskTag.json` is written by `infinigen/core/execute_tasks.py` through
`infinigen/core/tagging.py::AutoTag.save_tag`. It serializes
`tag_system.tag_dict`, the mapping from semantic tag names to integer IDs used
by the per-face Blender mesh attribute named `MaskTag`.

`back.bottom` and `front.top` are combined canonical surface tags. Canonical
`back` is local x minimum, `front` is local x maximum, `bottom` is local z
minimum, and `top` is local z maximum. The values `21` and `22` are tag label
IDs, not object IDs, mesh IDs, material IDs, proposal IDs, or collection IDs.

The two `MaskTag.json` files had the same 119 keys. The only differences were:

| tag ID | baseline | candidate_batch |
| ---: | --- | --- |
| 21 | `front.top` | `back.bottom` |
| 22 | `back.bottom` | `front.top` |

`solve_state.json` is not byte-identical, but it is equal after
`scripts/compare_indoor_outputs.py` canonicalization. The byte difference comes
from unordered tag-list ordering such as `-Subpart(front)` and
`-Subpart(back)` appearing in opposite order. This supports the previous
`SAME solve_state.json numeric_max_abs_diff=0` result.

Additional output checks found that this A/B is not Isaac static scene
equivalent from the saved blend evidence:

- `pipeline_coarse.csv` object counts matched at every stage, but memory
  columns differed.
- `optim_records.csv` had the same 5830 rows. Ignoring timing columns, only 23
  floating point text differences were found, with maximum absolute difference
  `1.4210854715202004e-14`; no accept/reject or move sequence difference was
  found by this check.
- `polycounts.txt` differed, with candidate having more vertices/faces/tris.
- Blender background inspection found matching object names and object counts,
  but different total mesh vertices/polygons, 3 object transform differences
  above `1e-9`, 31 mesh-info differences, material-name differences, and 25
  extra candidate node groups.

### Judgment

The `MaskTag.json` ID swap alone is an annotation/tag mapping difference. It
does not by itself prove a furniture layout, geometry, or material change. The
inspected USD export and Isaac Sim helper paths do not read `MaskTag.json`, so
the JSON mapping alone should not affect Isaac Sim static USD import.

However, this specific full 10-room A/B cannot be treated as strict-equivalent
or Isaac-static-equivalent because the saved `scene.blend` and polycount
evidence show non-JSON scene differences. `INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1`
therefore remains opt-in only. Do not run the wall-clock A/B, do not mainline
batch remove, and do not relax the compare gate from this result.

If future evidence shows a pure `MaskTag.json` ID-order difference while the
USD-relevant scene is proven equivalent, consider proposing separate gates for
strict equivalence, Isaac static scene equivalence, and GT annotation
equivalence. That is only a recommendation; no compare rule was changed in this
round.

## 2026-06-20 - Full 10-room batch remove equivalence result

### Round Goal

Run the full 10-room `INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1` equivalence A/B
without changing source, gin configuration, solver flow, proposal order,
accept/reject logic, random number calls, object availability, or solve steps.
Do not run the wall-clock A/B unless the full equivalence run completes and
`scripts/compare_indoor_outputs.py` prints `FINAL: PASS`.

### Command

```bash
PYTHON_BIN=/home/ubuntu22/miniconda3/envs/infinigen/bin/python \
EXPERIMENT_TIMEOUT_SECONDS=28800 \
bash scripts/run_gc_batch_remove_equivalence.sh
```

The run used the normal full target: seed `0`, task `coarse`,
`fast_solve.gin`, `compose_indoors.terrain_enabled=False`,
`home_room_constraints.has_fewer_rooms=False`, and
`restrict_solving.solve_max_rooms=10`. Heavy timing instrumentation was not
enabled: `INFINIGEN_PROFILE_TIMING`, `INFINIGEN_PROFILE_GC`,
`INFINIGEN_PROFILE_ASSET_FACTORY`, and `INFINIGEN_PROFILE_BBOX` were unset.

### Result

Both sides completed before the 28800s timeout:

| run | status | pipeline `MAIN TOTAL` |
| --- | --- | ---: |
| baseline | complete | 4:11:49.774668 |
| candidate_batch | complete | 3:07:38.553985 |

The compare failed:

```text
matched_json_file_count: 2
missing_files: 0
extra_files: 0
file_results:
  DIFFERENT MaskTag.json numeric_max_abs_diff=1
    - $.back.bottom: left 22, right 21
    - $.front.top: left 21, right 22
  SAME solve_state.json numeric_max_abs_diff=0
numeric_max_abs_diff: 1
FINAL: FAIL
```

No traceback, OOM, kill, or segmentation fault marker was found in the
baseline, candidate, or compare logs.

### Judgment

This is a complete full 10-room A/B, but it is not behavior-equivalent because
`MaskTag.json` differs. The shorter candidate `MAIN TOTAL` is not accepted as
speed evidence because the equivalence gate failed. The wall-clock script was
therefore not run.

`INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1` must remain opt-in only. It must not
be mainlined or promoted to a default-on path from this result. The next step is
to understand the `MaskTag.json` difference, especially whether batch removal
changes Blender data-block lifecycle, tag assignment, or deletion ordering in a
way that is visible to generated outputs. A no-heavy-instrumentation wall-clock
A/B should only be run after the full 10-room compare prints `FINAL: PASS`.

## 2026-06-19 - Batch remove validation and wall-clock scripts

### Round Goal

Add the missing validation harnesses for the current strongest opt-in
candidate, `INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1`, without adding any new
optimization. This round keeps the default behavior unchanged and does not
change solver flow, random number calls, proposal order, accept/reject logic,
solve steps for the normal 10-room target, object availability, or mainline gin
configuration.

### Changes

Added `scripts/run_gc_batch_remove_equivalence.sh`.

The script runs a sequential same seed/gin/task A/B:

- baseline with `INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS` unset:
  `outputs/gc_batch_remove_equiv/baseline/coarse`
- candidate with `INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1`:
  `outputs/gc_batch_remove_equiv/candidate_batch/coarse`

By default both sides use seed `0`, task `coarse`, `fast_solve.gin`,
`compose_indoors.terrain_enabled=False`,
`home_room_constraints.has_fewer_rooms=False`, and
`restrict_solving.solve_max_rooms=10`. The script explicitly unsets the heavy
timing variables `INFINIGEN_PROFILE_TIMING`, `INFINIGEN_PROFILE_GC`,
`INFINIGEN_PROFILE_ASSET_FACTORY`, and `INFINIGEN_PROFILE_BBOX`.

`EXPERIMENT_TIMEOUT_SECONDS` defaults to `14400`. Setting it to `0` or an empty
string disables `timeout`. After both runs, the script calls
`scripts/compare_indoor_outputs.py` and prints an explicit warning when either
side times out or when `NO_COMPARABLE_JSON_FOUND` appears.

Added `scripts/run_gc_batch_remove_walltime.sh`.

The wall-clock script uses the same baseline/candidate command shape without
heavy instrumentation. It records per-run exit code, shell-measured wall time,
and `/usr/bin/time -v` max RSS when available, then writes
`outputs/gc_batch_remove_walltime/summary.txt` and runs
`scripts/compare_indoor_outputs.py`.

Both scripts support:

```bash
EXPERIMENT_SMOKE_SINGLE_ROOM=1
```

In smoke mode they add `singleroom.gin`, set
`home_room_constraints.has_fewer_rooms=True`, and set
`restrict_solving.solve_max_rooms=1`. This is only a script and obvious
equivalence smoke. It does not prove that the normal 10-room indoor coarse path
is behavior-preserving or faster.

### Current Judgment

Batch remove remains the strongest current single-scene candidate, but it has
not passed a complete A/B. The 600s timeout smoke lowered measured
`node_groups` remove duration from 366.131s to 46.350s while the candidate
removed more node groups, but both sides timed out and no comparable JSON was
produced. That is profiling evidence only.

The acceptance bar is now explicit:

1. Complete the normal 10-room baseline and candidate runs.
2. Require `scripts/compare_indoor_outputs.py` to print `FINAL: PASS`.
3. Show a wall-clock reduction with `scripts/run_gc_batch_remove_walltime.sh`
   without heavy timing instrumentation.

Until all three are true, `INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1` must remain
opt-in and must not be treated as mainline behavior.

### Validation

Static checks passed:

```bash
python -m py_compile scripts/compare_indoor_outputs.py
bash -n scripts/run_gc_batch_remove_equivalence.sh
bash -n scripts/run_gc_batch_remove_walltime.sh
git diff --check
```

Single-room smoke was run only to validate the harness and catch obvious
differences:

```bash
EXPERIMENT_SMOKE_SINGLE_ROOM=1 \
EXPERIMENT_TIMEOUT_SECONDS=3600 \
PYTHON_BIN=/home/ubuntu22/miniconda3/envs/infinigen/bin/python \
bash scripts/run_gc_batch_remove_equivalence.sh

EXPERIMENT_SMOKE_SINGLE_ROOM=1 \
EXPERIMENT_TIMEOUT_SECONDS=3600 \
PYTHON_BIN=/home/ubuntu22/miniconda3/envs/infinigen/bin/python \
bash scripts/run_gc_batch_remove_walltime.sh
```

Both smoke compares passed with `matched_json_file_count: 2`,
`MaskTag.json` and `solve_state.json` both `SAME`, and
`numeric_max_abs_diff: 0`. The wall-clock smoke recorded:

| run | status | wall seconds | max RSS KB |
| --- | --- | ---: | ---: |
| baseline | complete | 163.339 | 2,357,896 |
| candidate_batch | complete | 163.462 | 2,350,572 |

Smoke speedup was `0.999x`. No traceback, OOM, kill, or segmentation fault was
observed in the smoke logs. This single-room result validates the scripts only;
the normal 10-room A/B remains required.

## 2026-06-19 - Opt-in node group batch_remove experiment

### Round Goal

Add the first real opt-in cleanup optimization experiment for the current
single-scene indoor coarse bottleneck. The experiment replaces per-node-group
`target.remove(obj)` with `bpy.data.batch_remove(ids)` only for
`bpy.data.node_groups`, and only when explicitly enabled with:

```bash
INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1
```

Default behavior remains unchanged when the environment variable is unset. This
round does not change solver flow, random number calls, proposal order,
accept/reject logic, solve steps, gin configuration, object availability, or
the suspected `union_all_bbox` issue. It also does not explore concurrent
generation, `manage_jobs.num_concurrent`, 32-thread throughput, or multi-process
scheduling; the scope remains one indoor coarse scene.

### Changes

Updated `infinigen/core/util/blender.py` so untimed and timed GC keep the
original individual remove path by default. When
`INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1` and the target is exactly
`bpy.data.node_groups`, GC scans with the existing remove conditions, collects
the same data-blocks into `to_remove`, and calls `bpy.data.batch_remove(to_remove)`
once when the list is non-empty. Other targets such as meshes, materials,
textures, objects, and collections still use the original individual remove
logic.

Extended GC timing rows with:

- `remove_mode`
- `batch_remove_enabled`
- `batch_remove_count`
- `batch_remove_duration`
- `individual_remove_duration`

Updated `scripts/analyze_gc_timing.py` to summarize remove modes, node group
remove duration by mode, and batch remove totals including total batch size,
average batch size, and maximum batch size.

Added `scripts/run_gc_batch_remove_experiment.sh`, which runs a sequential
single-scene baseline and candidate with the same seed, task, gin, and
overrides, then calls `scripts/compare_indoor_outputs.py`. The baseline leaves
`INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS` unset. The candidate enables it.

### Smoke Result

Command:

```bash
PYTHON_BIN=/home/ubuntu22/miniconda3/envs/infinigen/bin/python \
EXPERIMENT_TIMEOUT_SECONDS=1200 \
bash scripts/run_gc_batch_remove_experiment.sh
```

Both sides timed out, so this is not a complete A/B. `compare_indoor_outputs.py`
found no comparable JSON:

```text
matched_json_file_count: 0
NO_COMPARABLE_JSON_FOUND
FINAL: FAIL
```

GC timing summary:

| run | status | CSV lines | node_group rows | removed_count | remove_mode | node_groups remove_duration |
| --- | --- | ---: | ---: | ---: | --- | ---: |
| baseline | timeout | 6,086 | 680 | 10,858 | individual | 366.131s |
| candidate_batch | timeout | 7,155 | 799 | 15,758 | batch_remove | 46.350s |

Candidate batch details:

| metric | value |
| --- | ---: |
| batch_remove_count total | 15,758 |
| batch_remove call rows | 781 |
| average batch size | 20.177 |
| max batch size | 695 |

The candidate reached farther than baseline before timeout, advancing into
`on_floor_freestanding_8` / `kitchen_0/0`. The timeout bottleneck there shifted
to repeated `KitchenIslandFactory` proposal work. No traceback, OOM, kill, or
segmentation fault was observed in the smoke log.

### Judgment

The timing signal is strong: opt-in `batch_remove` greatly reduced measured
`node_groups` remove time in this timeout sample, even while removing more node
groups because the candidate advanced farther. However, `batch_remove` may
change Blender's internal deletion order or data-block lifecycle, and this run
did not produce comparable JSON. It must not be mainlined from this smoke.

The current primary cause remains heavy node group cleanup from indoor factories
such as `LargeShelfFactory`, with repeated prefixes including
`nodegroup_tagged_cube`, `nodegroup_division_board`, `nodegroup_screw_head`,
and `nodegroup_side_board`. The earlier interval=20 deferred cleanup experiment
remains rejected: broad delayed cleanup created burst removes and increased
raw node group remove time.

Next behavior-preserving work should run a complete same seed/gin/task A/B for
this opt-in batch remove path, or a longer bounded profile if full completion
still times out. If the speed signal holds and A/B passes, then consider the
same path for a narrow opt-in production flag. If A/B fails or comparable JSON
is still missing, return to precise reuse, caching, or reduced duplicate node
group creation inside the dominant factories instead of broad deferred cleanup.

## 2026-06-19 - Node group GC attribution timing

### Round Goal

Stop optimization experiments and add finer attribution for the measured
`bpy.data.node_groups` remove hotspot. This round keeps default generation
behavior unchanged: it does not change `GarbageCollect` cleanup conditions,
cleanup order, solver flow, random number calls, proposal order, accept/reject
logic, solve steps, gin configuration, or generated content.

### Changes

Added optional GC attribution metadata:

- `infinigen/core/util/blender.py`
- `infinigen/core/placement/factory.py`

`GarbageCollect` now accepts optional metadata fields such as `caller`,
`generator_class`, `factory_seed`, and `inst_seed`. `AssetFactory.spawn_asset`
passes `generator_class`, `factory_seed`, `inst_seed`, and
`caller="AssetFactory.spawn_asset"` only when GC timing is enabled, keeping the
normal non-profiling path close to the previous overhead.

Added bounded node group removal name summaries on timed
`target_name == node_groups` / `exit_cleanup` rows:

- `removed_name_count`
- `removed_name_prefix_top`
- `removed_name_sample`
- `removed_name_unique_prefix_count`

The summaries are bounded. They record top prefixes and a small sample instead
of writing every removed node group name to the CSV. Prefixes strip Blender's
numeric `.001`-style suffixes. Name capture happens in the existing cleanup
loop immediately before `target.remove(obj)`, without a second traversal and
without changing remove conditions or remove order.

Updated GC analysis:

- `scripts/analyze_gc_timing.py`

The analyzer now reports node group remove totals by `generator_class`, removed
counts by `generator_class`, removed node group name prefix totals, the slowest
node group remove rows with attribution and name summaries, and guidance for
factory-specific or prefix-specific follow-up.

### Validation Notes

Ran a fresh 600s attribution sample:

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

The run timed out as expected for a bounded sample. It produced:

- CSV path: `outputs/profile_gc_attribution/coarse/infinigen_gc_timing.csv`
- CSV lines: 4,741 including header, 4,740 data rows
- context rows: 492
- target rows: 4,248
- `node_groups` exit rows: 529
- `node_groups` remove duration: 185.030s

Top `generator_class` by `node_groups` remove duration:

| generator_class | remove_duration (s) | removed_count | rows |
| --- | ---: | ---: | ---: |
| LargeShelfFactory | 139.219 | 5,661 | 153 |
| SimpleBookcaseFactory | 20.382 | 752 | 94 |
| SimpleDeskFactory | 7.316 | 344 | 86 |
| (unknown) | 6.834 | 179 | 38 |
| BeverageFridgeFactory | 6.581 | 144 | 9 |

Top removed node group prefixes:

| removed_name_prefix | removed_count |
| --- | ---: |
| nodegroup_tagged_cube | 1,672 |
| nodegroup_division_board | 1,586 |
| nodegroup_screw_head | 1,586 |
| nodegroup_side_board | 680 |
| geometry_nodes | 333 |
| nodegroup_bottom_board | 293 |
| nodegroup_back_board | 247 |

The slowest row was `direct-527` with no factory metadata, 135 removals, and
5.985s remove duration. The next slow rows were all `LargeShelfFactory`, with
repeated `nodegroup_division_board`, `nodegroup_screw_head`, and
`nodegroup_tagged_cube` prefixes.

### Judgment

The earlier `INFINIGEN_GC_NODE_GROUP_INTERVAL=20` experiment is not an
effective optimization. Both A/B sides timed out, no comparable JSON existed,
and the candidate increased raw `node_groups_remove` from 369.071s to 443.414s
despite skipping 558 node group cleanup opportunities. Naive deferred cleanup
creates large burst removes and should not be promoted.

The current next step is attribution-driven investigation. This sample points
first at `LargeShelfFactory` and repeated shelf/bookcase node group prefixes.
Follow-up optimization should prioritize precise reuse, caching, or reduced
duplicate creation of equivalent node groups, not broader deferred cleanup.
Any optimization still needs to be opt-in first and must pass same
seed/gin/task A/B validation with `scripts/compare_indoor_outputs.py`.

## 2026-06-19 - Opt-in node group GC throttling experiment

### Round Goal

Add the first behavior-preserving optimization experiment around the current
measured GC hotspot while keeping default generation behavior unchanged. The
latest GC target timing showed `bpy.data.node_groups` removal as the dominant
cost: `enter_snapshot` was 0.422s, `exit_cleanup` was 183.972s,
`remove_duration` was 183.378s, and `node_groups` alone was 181.131s.

This round does not optimize the solver, does not change gin configuration,
does not reduce solve steps, does not change random number calls, does not
change proposal ordering, does not change accept/reject logic, does not fix
`union_all_bbox`, and does not add C++ to Blender lifecycle code.

### Changes

Added an opt-in node group cleanup throttle:

- `infinigen/core/util/blender.py`

New environment variable:

```bash
INFINIGEN_GC_NODE_GROUP_INTERVAL=20
```

When unset or set to `1`, `GarbageCollect` keeps the original behavior and
cleans `bpy.data.node_groups` every time. Values greater than `1` skip the
first `N-1` node group cleanup opportunities and run the normal cleanup loop on
the `N`th opportunity. The experiment only affects `bpy.data.node_groups`;
other targets still use the original cleanup path each time.

Invalid interval values such as `0`, negative numbers, or non-integers fall
back to `1` and emit a warning once.

Extended GC timing rows with:

- `node_group_interval`
- `node_group_cleanup_skipped`
- `node_group_cleanup_due`
- `effective_cleanup`

Added analyzer support:

- `scripts/analyze_gc_timing.py`

The analyzer now reports interval values, skipped and executed node group
cleanup counts, node group total duration, node group remove duration, a rough
saved-time estimate, and maximum observed `node_groups` count.

Added experiment runner:

- `scripts/run_gc_node_group_experiment.sh`

It runs a baseline with `INFINIGEN_GC_NODE_GROUP_INTERVAL=1`, a candidate with
`INFINIGEN_GC_NODE_GROUP_INTERVAL=20`, and then compares the output folders
with `scripts/compare_indoor_outputs.py`.

### Behavior Guardrails

Default behavior remains unchanged when the new environment variable is unset
or `1`. The throttle path does not change node group remove conditions; when a
node group cleanup is due, it still uses the existing `garbage_collect` loop.
The experiment does not use `bpy.ops.outliner.orphans_purge`.

This optimization candidate is risky because delaying node group removal may
change Blender data-block name allocation or leave residual node groups visible
to later contexts. If A/B comparison fails, the throttle must not become a
mainline optimization. If A/B comparison passes, the next step is a longer
profile plus memory observation.

`GarbageCollect` touches `bpy.data` lifecycle and remains unsuitable for C++.
The earlier bbox result still stands: `union_all_bbox` was only 0.075s out of
334.068s, or 0.023%, so C++ bbox integration is not the current priority.

### Smoke Result

Ran the opt-in experiment with:

```bash
EXPERIMENT_TIMEOUT_SECONDS=1200 bash scripts/run_gc_node_group_experiment.sh
```

Both runs timed out, so this was not a complete A/B:

- baseline interval=1: timeout, 6,276 GC timing rows
- candidate interval=20: timeout, 5,259 GC timing rows
- `compare_indoor_outputs.py`: `NO_COMPARABLE_JSON_FOUND`, `FINAL: FAIL`

Node group cleanup summary:

- baseline: 702 executed node group cleanups, 0 skipped,
  `node_groups_remove` 369.071s, max node groups 1,678
- candidate: 29 executed node group cleanups, 558 skipped,
  `node_groups_remove` 443.414s, max node groups 5,646

The candidate advanced farther before timeout, but raw node group remove time
did not decrease. It increased by 74.343s in this partial sample, with large
burst removals after deferred cleanup. This interval=20 experiment is not a
validated speedup and must remain opt-in only.

## 2026-06-19 - GarbageCollect target timing

### Round Goal

Keep generation behavior unchanged while adding optional target-level timing
inside `infinigen.core.util.blender.GarbageCollect` / `garbage_collect` and
using a bounded sample to identify whether the GC cost is enter snapshot,
exit cleanup scanning, removal, or a specific `bpy.data` target.

### Changes

Added optional GC timing:

- `infinigen/core/util/blender.py`

Enable with either:

```bash
INFINIGEN_PROFILE_GC=1
```

or the existing:

```bash
INFINIGEN_PROFILE_TIMING=1
```

The timing CSV is `infinigen_gc_timing.csv`. It is written to the current
solver output folder when available, otherwise to:

```text
/tmp/infinigen_gc_timing.csv
```

Recorded rows include context-level timing for `GarbageCollect` enter/exit and
target-level timing for `enter_snapshot` and `exit_cleanup`. Target rows record
the `bpy.data` target name, target lengths, scanned count, skipped count,
removed count, remove duration, and total target duration.

The default non-timing `garbage_collect` / `GarbageCollect` behavior remains
unchanged. The timing path preserves target traversal order, `keep_in_use`,
`keep_names`, and `verbose` semantics, preserves remove conditions, and
re-raises original exceptions.

Added GC timing analysis:

- `scripts/analyze_gc_timing.py`

The script summarizes context count, enter versus exit totals, target duration
totals, scan/remove counts, slowest target rows, zero-remove high-duration
rows, and prints guidance for the next behavior-preserving experiment.

### Validation Notes

Ran a bounded 600s GC timing sample using:

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

The sample produced 4821 GC timing rows at:

```text
outputs/profile_gc_current/coarse/infinigen_gc_timing.csv
```

Analyzer result:

- context rows: 501
- target rows: 4320
- target `enter_snapshot` duration: 0.422s
- target `exit_cleanup` duration: 183.972s
- `remove_duration`: 183.378s
- estimated exit scan time excluding remove: 0.594s
- exit cleanup scanned count: 1,528,801
- exit cleanup removed count: 7,843

Target duration totals:

- `node_groups`: 181.131s, with 7,582 removals
- `meshes`: 2.433s, with 261 removals
- `materials`: 0.829s, with 0 removals
- `textures`: 0.000s, with 0 removals

The current dominant GC cost is `exit_cleanup` removal from
`bpy.data.node_groups`. `enter_snapshot` is not dominant, broad scan cost is not
dominant, and zero-remove rows are low-duration in this sample.

### Behavior Guardrails

This round is timing only. It does not optimize the solver, does not reduce
solve steps, does not disable objects, does not change gin configuration, does
not change `GarbageCollect` behavior, and does not change generated content.

The current first measured cause is `AssetFactory.spawn_asset` spending most of
its measured internal time inside `GarbageCollect` context work. In the fresh GC
sample, `garbage_collect_context_duration` was 177.848s of 278.502s
`spawn_asset` time, or 63.859%. `create_asset_duration` was secondary at
99.383s, or 35.685%; `delete_placeholder_duration` was only 0.228s, or 0.082%.

The earlier bbox timing still stands: `union_all_bbox` was only 0.075s out of
334.068s, or 0.023%, so default C++ bbox integration is not the priority.
`GarbageCollect` touches Blender `bpy.data` lifecycle and is not a C++ rewrite
target.

Any future GC scope adjustment, deferred cleanup, less frequent cleanup, batch
cleanup, or target-specific cleanup must start opt-in and pass same
seed/gin/task A/B validation with `scripts/compare_indoor_outputs.py`.

## 2026-06-19 - Asset factory spawn timing

### Round Goal

Keep generation behavior unchanged while adding optional fine-grained timing
inside `AssetFactory.spawn_asset` and using a bounded sample to identify the
next real bottleneck inside factory spawning.

### Changes

Added optional `spawn_asset` timing:

- `infinigen/core/placement/factory.py`

Enable with either:

```bash
INFINIGEN_PROFILE_ASSET_FACTORY=1
```

or the existing:

```bash
INFINIGEN_PROFILE_TIMING=1
```

The timing CSV is `infinigen_asset_factory_timing.csv`. It is written to the
current solver output folder when available, otherwise to:

```text
/tmp/infinigen_asset_factory_timing.csv
```

Recorded fields include generator class, factory seed, instance seed,
user-provided placeholder flag, distance, visibility distance, spawn
placeholder duration, placeholder finalization duration, asset-parameter
duration, `create_asset` duration, parent/transform duration, placeholder
delete duration, `GarbageCollect` context duration, total duration, success, and
error type.

The default non-timing `spawn_asset` path remains unchanged. The timing path
does not change random number usage, does not reorder placeholder or asset
creation, does not reorder object parent/transform/delete operations, and
re-raises original exceptions.

Added asset factory timing analysis:

- `scripts/analyze_asset_factory_timing.py`

The script summarizes generator totals, `create_asset`, placeholder delete,
placeholder finalization, slowest calls, duration totals, and prints guidance on
the dominant stage.

### Validation Notes

Ran a bounded 600s asset factory timing sample using:

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

The sample produced 499 `AssetFactory.spawn_asset` timing rows at:

```text
outputs/profile_asset_factory_current/coarse/infinigen_asset_factory_timing.csv
```

Analyzer result:

- total `spawn_asset` time: 276.641s
- total `garbage_collect_context_duration`: 176.647s, 63.854%
- total `create_asset_duration`: 98.738s, 35.692%
- total `delete_placeholder_duration`: 0.225s, 0.082%
- total `finalize_placeholders_duration`: 0.000s, 0.000%

`garbage_collect_context_duration` is the dominant measured stage inside
`spawn_asset`; `create_asset` is secondary. Placeholder delete and placeholder
finalization are not primary in this sample.

### Behavior Guardrails

This round still does not optimize the solver, does not connect C++ to the
solver path, and does not fix the suspected `union_all_bbox` issue. Bbox timing
showed `union_all_bbox` at only 0.075s of 334.068s, or 0.023%, so default C++
bbox integration is not the priority.

The next optimization candidate should be behavior-preserving work around
`AssetFactory.spawn_asset`, `GarbageCollect`, and factory lifecycle. Any delete
batching, deferred cleanup, or factory bbox/cache experiment must start as an
opt-in path and pass same seed/gin/task A/B output comparison before being
accepted.

## 2026-06-19 - Optional geometry build flag and bbox timing

### Round Goal

Keep the solver behavior unchanged while making the standalone geometry C++
extension optional, adding fine-grained `bbox_mesh_from_hipoly` timing, and
surveying real C++ call sites before any solver integration.

### Changes

Made the standalone geometry extension opt-out at build time:

- `setup.py`

Set:

```bash
INFINIGEN_DISABLE_GEOMETRY_CPP=True python -m pip install -e .
```

to skip `infinigen.core.constraints.cpp.geometry_kernels_cpp` while keeping the
NumPy fallback importable and usable. The default build still attempts to build
the extension. Terrain, bnurbs, and customgt build flags remain separate.

Added optional bbox timing:

- `infinigen/assets/utils/bbox_from_mesh.py`
- `infinigen/core/constraints/example_solver/timing.py`

Enable with either:

```bash
INFINIGEN_PROFILE_BBOX=1
```

or the existing:

```bash
INFINIGEN_PROFILE_TIMING=1
```

The timing CSV is `infinigen_bbox_timing.csv`. It is written to the current
solver output folder when that is available, otherwise to:

```text
/tmp/infinigen_bbox_timing.csv
```

Recorded fields include generator class, factory seed, instance seed,
`use_pholder`, spawn placeholder duration, spawn asset duration,
`union_all_bbox` duration, bbox mesh creation duration, cleanup collection
duration, delete duration, total duration, success, and error type. The timing
path does not replace any bbox logic, does not call C++ kernels, does not change
random number usage, and re-raises original exceptions.

Added bbox timing analysis:

- `scripts/analyze_bbox_timing.py`

The script summarizes generator totals, slowest calls, duration totals, and
prints guidance on whether `union_all_bbox` is large enough to justify an
opt-in C++ bbox experiment.

Added C++ call-site survey:

- `docs/CPP_CALLSITE_SURVEY.md`

The survey records candidate file paths, functions, current logic, estimated
array scale, `bpy` and random-number contact, pure-array suitability, behavior
risk, C++ suitability, and priority.

### Behavior Guardrails

This round still does not optimize the solver and does not connect C++ kernels
to the indoor solver, evaluator, `Addition.apply`, or `union_all_bbox` by
default.

`infinigen/assets/utils/bbox_from_mesh.py::union_all_bbox` still has the
suspected max update issue and remains unfixed:

```python
maxs = pmaxs if maxs is None else np.maximum(pmins, mins)
```

The next decision should be data-driven: use bbox timing to determine whether
time is in `spawn_asset`, `delete`, or `union_all_bbox` before considering an
opt-in C++ bbox integration. If C++ is integrated later, require same
seed/gin/task A/B equivalence validation.

### Validation Notes

Ran a bounded 600s bbox timing sample using:

```bash
INFINIGEN_PROFILE_TIMING=1 INFINIGEN_PROFILE_BBOX=1 timeout 600s python -m infinigen_examples.generate_indoors \
  --seed 0 \
  --task coarse \
  --output_folder outputs/profile_bbox_current/coarse \
  -g fast_solve.gin \
  -p compose_indoors.terrain_enabled=False \
     home_room_constraints.has_fewer_rooms=False \
     restrict_solving.solve_max_rooms=10
```

The sample produced 507 `bbox_mesh_from_hipoly` timing rows at:

```text
outputs/profile_bbox_current/coarse/infinigen_bbox_timing.csv
```

Analyzer result:

- total `bbox_mesh_from_hipoly` time: 334.068s
- total `spawn_asset_duration`: 266.233s, 79.7%
- total `delete_duration`: 57.480s, 17.2%
- total `union_all_bbox_duration`: 0.075s, 0.023%

This sample does not justify prioritizing default C++ integration for
`union_all_bbox` / `bbox_min_max`. The better next target remains
Blender-heavy asset spawning, deletion, and factory lifecycle work.

## 2026-06-19 - Standalone C++ geometry kernel prototypes

### Round Goal

Add the first standalone Cython/C++ numeric kernel prototypes, Python fallback,
unit tests, and microbenchmark without changing indoor solver behavior.

### Changes

Added a pure numeric kernel package:

- `infinigen/core/constraints/cpp/__init__.py`
- `infinigen/core/constraints/cpp/geometry_kernels.py`
- `infinigen/core/constraints/cpp/geometry_kernels.pyx`

Added tests and benchmarking:

- `tests/test_geometry_kernels.py`
- `scripts/bench_geometry_kernels.py`

Updated the existing Cython build list in `setup.py` with:

- `infinigen.core.constraints.cpp.geometry_kernels_cpp`

The new kernels cover:

1. `bbox_min_max(points)`
2. `bbox_union(mins, maxs)`
3. `aabb_overlap_matrix(mins_a, maxs_a, mins_b, maxs_b)`
4. `aabb_contains(outer_min, outer_max, inner_min, inner_max)`

### Behavior Guardrails

This round does not import or call the new kernels from:

- `union_all_bbox`
- `validity.py`
- evaluator modules
- annealing
- `Addition.apply`

The new package does not import `bpy`, does not import `gin`, does not call
random number generators, and does not touch `spawn_asset` or
`spawn_placeholder`.

Boundary contact is treated as inclusive overlap/containment in the standalone
AABB helpers. This is conservative for a future broad-phase because touching
pairs must still reach the existing exact collision/contact code.

`infinigen/assets/utils/bbox_from_mesh.py::union_all_bbox` still has suspicious
logic and remains unchanged:

```python
maxs = pmaxs if maxs is None else np.maximum(pmins, mins)
```

Any fix to that behavior remains separate work requiring a focused sanity test
and same seed/gin/task A/B equivalence validation.

## 2026-06-19 - Equivalence testing and C++ rewrite planning

### Round Goal

Add an A/B equivalence validation harness and document the C++ rewrite plan
without optimizing solver behavior, changing gin configuration, reducing solve
steps, disabling objects, changing random number order, or writing C++ code.

### Changes

Added A/B comparison tooling:

- `scripts/compare_indoor_outputs.py`

Added documentation:

- `docs/EQUIVALENCE_TESTING.md`
- `docs/CPP_REWRITE_CANDIDATES.md`

Updated handoff docs to make the next phase explicit:

- The next stage is behavior-preserving optimization.
- Every optimization must pass A/B equivalence validation first.
- C++ is only for pure computation kernels.
- Reduced content or lower generation quality is not the main acceleration path.
- The best current investigation target remains failed or unaccepted
  `Addition.apply` work from heavy factories.
- Cheap preflight rejection is risky unless it preserves random number order,
  proposal order, accept/reject decisions, and final outputs.

### A/B Comparator

Run:

```bash
python scripts/compare_indoor_outputs.py outputs/a/coarse outputs/b/coarse
```

The script recursively pairs `.json` files by relative path, canonicalizes
obvious run-specific fields and absolute output/temp paths, sorts known
unordered tag lists such as `tags`, `child_tags`, and `parent_tags`, compares
numeric values with `--rtol` and `--atol`, prints first differences, reports
numeric `max_abs_diff`, and ends with `PASS` or `FAIL`.

If no paired comparable JSON exists, it prints:

```text
NO_COMPARABLE_JSON_FOUND
```

That result is a failure, not a pass.

### Smoke A/B

Ran a small single-room coarse smoke A/B inside the existing `infinigen`
container using the same seed, gin, task, and parameter overrides:

```text
outputs/ab_smoke_a/coarse
outputs/ab_smoke_b/coarse
```

Compared on the host with:

```bash
python scripts/compare_indoor_outputs.py \
  outputs/ab_smoke_a/coarse \
  outputs/ab_smoke_b/coarse
```

Result:

```text
matched_json_file_count: 2
SAME MaskTag.json numeric_max_abs_diff=0
SAME solve_state.json numeric_max_abs_diff=0
FINAL: PASS
```

This smoke only validates the comparison workflow. It is not evidence that
reducing room count is an acceptable speed optimization.

### C++ Rewrite Planning

The top P0 candidates are extracted pure numeric kernels, not the current
Blender wrappers:

1. Batch bbox min/max reduction.
2. Batch bbox union.
3. AABB pair overlap matrix.
4. Axis-aligned bounds and containment checks.
5. Batch plane distance and support margin checks.

Do not rewrite `Addition.apply`, `sample_rand_placeholder`, factory
`spawn_asset` / `spawn_placeholder`, material/node generation, solver control
flow, random sampling, proposal order, or accept/reject logic in C++.

### Risk Notes

`infinigen/assets/utils/bbox_from_mesh.py::union_all_bbox` still has suspicious
logic:

```python
maxs = pmaxs if maxs is None else np.maximum(pmins, mins)
```

This round intentionally does not fix it. A fix may change generated geometry
and needs a separate sanity test plus A/B equivalence validation.

## 2026-06-19 13:25 CST - Indoor solver timing CSV analysis

### Round Goal

Confirm the timing instrumentation push, run an indoor coarse timing profile without changing generation behavior, add a CSV analysis helper, and identify behavior-preserving optimization targets.

### Git / Push

Confirmed local branch:

```text
perf/indoor-isaac-speedup
```

Confirmed and pushed:

```text
f1825d95 Add indoor solver timing instrumentation
```

The commit was pushed to:

```text
myroom/perf/indoor-isaac-speedup
```

### Profile Run

Command run inside the container:

```bash
cd /opt/infinigen
source /root/miniconda3/etc/profile.d/conda.sh
conda activate infinigen
INFINIGEN_PROFILE_TIMING=1 timeout 1800s bash scripts/profile_indoor_solver.sh
```

This was a 1800s timeout sample, not a complete profile. It timed out during:

```text
on_floor_freestanding_8 / kitchen_0/0
KitchenIslandFactory
```

Generated timing CSV:

```text
/opt/infinigen/outputs/profile_indoor_baseline/coarse/indoor_solver_timing.csv
outputs/profile_indoor_baseline/coarse/indoor_solver_timing.csv
```

CSV rows: 3061 proposal-attempt rows, plus header.

The cProfile output path was intended to be:

```text
/tmp/indoors_coarse.prof
```

This timeout run did not produce `/tmp/indoors_coarse.prof` in the container. The timing CSV is the source of truth for this round.

### Changes

Added a timing CSV summary helper:

- `scripts/analyze_indoor_timing.py`

Run it with:

```bash
python scripts/analyze_indoor_timing.py
```

or:

```bash
python scripts/analyze_indoor_timing.py path/to/indoor_solver_timing.csv
```

### Key Results

Top `generator_class` by `apply_duration` total:

| Rank | generator_class | count | apply total (s) | mean (s) | max (s) | failed | accepted |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | KitchenIslandFactory | 20 | 294.443 | 14.722 | 22.297 | 16 | 0 |
| 2 | LargeShelfFactory | 153 | 232.303 | 1.518 | 4.444 | 131 | 6 |
| 3 | TableDiningFactory | 63 | 84.746 | 1.345 | 1.469 | 54 | 1 |
| 4 | BeverageFridgeFactory | 44 | 84.472 | 1.920 | 2.097 | 43 | 1 |
| 5 | LargePlantContainerFactory | 585 | 64.825 | 0.111 | 0.301 | 537 | 8 |
| 6 | SimpleBookcaseFactory | 90 | 51.549 | 0.573 | 0.936 | 61 | 7 |
| 7 | (unknown) | 844 | 47.895 | 0.057 | 2.207 | 497 | 186 |
| 8 | SimpleDeskFactory | 112 | 45.202 | 0.404 | 0.721 | 89 | 3 |
| 9 | BathtubFactory | 126 | 43.983 | 0.349 | 0.845 | 125 | 1 |
| 10 | OvenFactory | 56 | 38.936 | 0.695 | 0.773 | 55 | 1 |

Slowest proposal attempts were all `KitchenIslandFactory` additions. Top 10 by `attempt_duration`:

| Rank | iteration | attempt | attempts | attempt (s) | apply (s) | revert (s) | total step (s) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 4 | 4 | 5 | 22.500 | 22.297 | 0.187 | 72.358 |
| 2 | 5 | 0 | 4 | 22.402 | 22.210 | 0.176 | 63.787 |
| 3 | 3 | 4 | 5 | 21.782 | 21.592 | 0.174 | 88.518 |
| 4 | 3 | 3 | 5 | 20.573 | 20.384 | 0.172 | 88.518 |
| 5 | 7 | 0 | 4 | 18.840 | 18.646 | 0.179 | 55.705 |
| 6 | 3 | 1 | 5 | 18.283 | 18.098 | 0.170 | 88.518 |
| 7 | 3 | 2 | 5 | 18.126 | 17.941 | 0.169 | 88.518 |
| 8 | 5 | 1 | 4 | 16.497 | 16.304 | 0.176 | 63.787 |
| 9 | 4 | 1 | 5 | 16.362 | 16.173 | 0.174 | 72.358 |
| 10 | 7 | 2 | 4 | 16.325 | 16.129 | 0.180 | 55.705 |

Failed proposal clusters by failed attempt count:

| Rank | generator_class | attempts | failed | failure rate | wasted apply (s) |
| --- | --- | ---: | ---: | ---: | ---: |
| 1 | LargePlantContainerFactory | 585 | 537 | 0.918 | 61.787 |
| 2 | (unknown) | 844 | 497 | 0.589 | 39.918 |
| 3 | KitchenCabinetFactory | 205 | 196 | 0.956 | 15.978 |
| 4 | CellShelfFactory | 152 | 134 | 0.882 | 12.558 |
| 5 | LargeShelfFactory | 153 | 131 | 0.856 | 209.884 |
| 6 | BathtubFactory | 126 | 125 | 0.992 | 43.868 |
| 7 | BedFactory | 95 | 92 | 0.968 | 10.582 |
| 8 | SingleCabinetFactory | 121 | 92 | 0.760 | 8.668 |
| 9 | SimpleDeskFactory | 112 | 89 | 0.795 | 33.350 |
| 10 | SimpleBookcaseFactory | 90 | 61 | 0.678 | 36.822 |

Largest wasted apply time clusters:

1. `KitchenIslandFactory` - 257.877s wasted apply
2. `LargeShelfFactory` - 209.884s wasted apply
3. `BeverageFridgeFactory` - 82.742s wasted apply
4. `TableDiningFactory` - 72.458s wasted apply
5. `LargePlantContainerFactory` - 61.787s wasted apply

Move type totals:

| move_type | count | apply (s) | evaluate (s) | revert (s) | accept (s) |
| --- | ---: | ---: | ---: | ---: | ---: |
| Addition | 2217 | 1112.264 | 109.877 | 178.612 | 0.000 |
| Resample | 114 | 27.863 | 2.396 | 8.204 | 0.662 |
| RelationPlaneChange | 217 | 14.650 | 10.944 | 0.074 | 0.000 |
| ReinitPoseMove | 111 | 3.942 | 14.598 | 0.042 | 0.000 |
| TranslateMove | 261 | 1.363 | 27.042 | 0.069 | 0.000 |

Overall row-level totals:

- `apply_duration`: 1160.159s
- `evaluate_duration`: 172.236s
- `revert_duration`: 187.095s
- `garbage_collect_duration`: 287.308s row-level sum, with repeated step-level rows; max observed 22.470s

### Conclusion

The main bottleneck in this timing sample is `Addition.apply`, especially failed or unaccepted heavy additions. `KitchenIslandFactory` dominates individual slow attempts and wasted apply time. `LargeShelfFactory` is the second largest wasted-apply cluster. Kitchen appliances and dining table proposals also contribute substantial repeated apply cost.

`evaluate_duration`, `revert_duration`, and `garbage_collect_duration` are measurable and can spike, but they are not the primary driver in this CSV. Even the row-level, over-count-prone `garbage_collect_duration` total is below `apply_duration`, and the largest slow attempts are dominated by apply work.

### Next Optimization Direction

Prioritize behavior-preserving optimization before any C++ rewrite:

1. Add cheap preflight rejection for expensive additions before full asset spawn/finalization, starting with `KitchenIslandFactory`, `LargeShelfFactory`, `BeverageFridgeFactory`, `DishwasherFactory`, `OvenFactory`, and `TableDiningFactory`.
2. Cache deterministic placeholder, bbox, and high-poly mesh bound computations per factory/scale/seed where the generated geometry is equivalent.
3. Defer expensive material/node/final object creation until after cheap geometric and relation checks when the exact same accepted asset can still be produced.
4. Reduce repeated failed retry work inside a stage by memoizing local negative placement/relation candidates without changing object availability or solve-step counts.
5. Investigate GC spikes as a secondary issue, but do not optimize it ahead of heavy addition apply cost.

Potential C++ rewrite candidates, after Python-level behavior-preserving work:

1. Numeric bbox min/max reductions and high-poly mesh bounds extraction.
2. AABB overlap and broad-phase collision checks.
3. Room/floor/wall bounds and containment checks over numeric arrays.
4. Batch candidate collision matrix construction for many boxes.
5. Constraint loss aggregation once inputs are already numeric arrays.

Do not start by rewriting `bpy` object creation/deletion, `spawn_asset`, material/node generation, or the simulated annealing solver control flow in C++.

## 2026-06-19 - Indoor solver timing instrumentation

### Round Goal

Add fine-grained, opt-in timing instrumentation for the indoor coarse solver without changing solver behavior, gin configuration, solve steps, object availability, or caching behavior.

### Changes

Added solver timing helpers:

- `infinigen/core/constraints/example_solver/timing.py`

Instrumented solver proposal steps:

- `SimulatedAnnealingSolver.retry_attempt_proposals`
- `SimulatedAnnealingSolver.step`
- `Addition.apply`
- `sample_rand_placeholder`

Timing is disabled by default. Enable it by setting:

```bash
INFINIGEN_PROFILE_TIMING=1
```

When enabled, the solver writes:

```text
<output_folder>/indoor_solver_timing.csv
```

The CSV records proposal-attempt rows with move generator name, move type, generator class when present, retry index, apply/evaluate/revert/accept/garbage-collect durations, total step duration, proposal success, and proposal acceptance.

### Notes

This round intentionally did not optimize or change generation logic.

`infinigen/assets/utils/bbox_from_mesh.py` has a suspected bug in `union_all_bbox`:

```python
maxs = pmaxs if maxs is None else np.maximum(pmins, mins)
```

This looks like it may use `pmins, mins` where `pmaxs, maxs` was intended. Do not fix as part of the timing round; add a focused sanity test in the next round before changing it.

## 2026-06-19 12:22 CST - Indoor coarse profiling baseline

### Round Goal

Establish an indoor coarse profiling baseline without optimizing source code.

### Changes

Added profiling helpers:

- `scripts/profile_indoor_solver.sh`
- `scripts/print_indoor_profile.py`

Added local handoff context:

- `AGENTS.md`
- `docs/WORKLOG.md`
- `docs/COMMANDS.md`
- `docs/PROFILE_RESULTS.md`
- `docs/NEXT_STEPS.md`

Updated ignore rules so generated profile and archive files are not committed.

### Commands

Run inside the container:

```bash
cd /opt/infinigen
source /root/miniconda3/etc/profile.d/conda.sh
conda activate infinigen
bash scripts/profile_indoor_solver.sh
python scripts/print_indoor_profile.py
```

### Result

This was a 30 minute bounded cProfile sampling run. It timed out during the `KitchenIslandFactory` stage, so it is not a complete profile.

Profile output path:

```text
/tmp/indoors_coarse.prof
```

Application-layer cumulative top 5:

1. `generate_indoors.py:206(solve_large)` - 1778.308s
2. `solve.py:144(solve_objects)` - 1778.287s
3. `annealing.py:252(step)` - 1776.001s
4. `annealing.py:187(retry_attempt_proposals)` - 1632.759s
5. `addition.py:88(apply)` - 1144.959s

Other notable hotspots:

- `sample_rand_placeholder` - 1007.360s
- `bbox_mesh_from_hipoly` - 962.604s
- `blender.py:236(garbage_collect)` - 684.869s
- `blender.py:290(delete)` - 449.876s
- `kitchen_space.py:236(create_asset)` - 322.605s

### Conclusion

The current indoor coarse baseline points to `solve_large`, `Solver.solve_objects`, simulated annealing `step`, proposal retry/apply/revert work, Blender object lifecycle costs, and `KitchenIslandFactory` as the main bottleneck area.

The bottleneck appears to be CPU / Python / Blender `bpy` / constraint-solving dominated rather than GPU/CUDA dominated.

`KitchenIslandFactory` single proposals taking roughly 55-88s are the clearest current hotspot. Kitchen appliances, `LargeShelf`, `Sofa`, and `TVStand` are also high-cost proposal areas. Constraint evaluation is not free, but appears secondary to Blender object lifecycle and asset factory creation costs in this bounded run.

### Next Step

Save this context, push the profiling baseline helpers to GitHub, then either run a complete profile or begin configuration-level speed experiments.
