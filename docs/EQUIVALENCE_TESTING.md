# Equivalence Testing

## Purpose

The indoor speedup work must preserve the generated scene, not only reduce wall
time. The current bottleneck is dominated by failed or unaccepted
`Addition.apply` attempts, especially heavy factories such as
`KitchenIslandFactory` and `LargeShelfFactory`. Many tempting shortcuts can make
the run faster by changing what the solver tries or accepts. Those changes are
not behavior-preserving optimizations unless an A/B comparison shows that the
same seed, gin configuration, task, and output target still produce the same or
acceptably equivalent indoor scene.

The comparison baseline is the original behavior at a known commit. The
candidate is the optimized commit. The A/B output comparison is a guardrail for
future Python and C++ work.

## Isaac Static Quality-Preserving Target

The current recommended Isaac Sim static environment configuration is not a
bitwise-identical target. It is an opt-in quality-preserving static scene
target for full 10-room indoor generation:

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
export and looked good, with no obvious quality issue. The acceptance gate for
this path is practical static scene quality: realistic rendering, sufficient
environment complexity, no obvious flying objects, no obvious severe
intersections, no obvious black materials, door openings retained without
door panels, and USD/USDC import working in Isaac Sim.

The three opt-in speed points are:

- batch node-group deletion with `INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1`
- `LargeShelfFactory` child node-group reuse with
  `INFINIGEN_REUSE_LARGESHELF_CHILD_NODEGROUPS=1`
- shell-like `NatureShelfTrinketsFactory` fast stable pose with
  `INFINIGEN_FAST_NATURE_TRINKET_STABLE_POSE=1`

These switches still do not change the original default behavior when unset.
Use `scripts/run_isaac_static_optimized_10room.sh` for this Isaac static path.

## Behavior-Preserving Optimization

A behavior-preserving optimization keeps the solver's observable behavior
unchanged for the same inputs:

- Same seed.
- Same gin files and gin parameter overrides.
- Same task, especially `--task coarse` for the current priority.
- Same output target type.
- Same solve steps.
- Same room/object availability.
- Same proposal order and accept/reject logic.
- Same random number call order.
- Same Blender-visible side effects for accepted and rejected proposals.

The implementation can be faster internally, but it must not reduce scene
content or change quality as the main acceleration strategy.

## High-Risk Changes

These changes can alter generation results and must not be treated as ordinary
performance optimizations:

- Reducing solve steps.
- Disabling small objects.
- Disabling floating objects.
- Reducing the number of rooms.
- Changing constraint weights.
- Changing proposal order.
- Changing random number call order.
- Changing simulated annealing accept/reject logic.
- Skipping Blender object creation or deletion when later code depends on those
  side effects.
- Changing Blender data-block deletion mode or order. For example, using
  `bpy.data.batch_remove` for node groups may change Blender's internal
  deletion order or data-block lifecycle even when the removed object set is
  unchanged.
- Delaying or throttling `bpy.data` garbage collection. For example,
  `INFINIGEN_GC_NODE_GROUP_INTERVAL>1` can change node group data-block name
  allocation, lifetime, and residual data-block visibility before the next
  cleanup.
- Adding cheap preflight rejection that rejects a proposal earlier than the
  original path. Even when the rejection is logically correct, it can change
  random number consumption, proposal ordering, retry behavior, and final
  output.

Cheap preflight can only move into the main optimization path after it has been
shown not to alter random number order, proposal order, accept/reject decisions,
or final output.

## Required A/B Workflow

Every optimization must have an A/B validation record:

1. Generate a baseline output from the baseline commit.
2. Generate an optimized output from the candidate commit.
3. Use the same seed for both runs.
4. Use the same gin files and parameter overrides.
5. Use the same task, normally `--task coarse`.
6. Use distinct output folders.
7. Compare the two output folders with:

```bash
python scripts/compare_indoor_outputs.py outputs/a/coarse outputs/b/coarse
```

The comparison script recursively scans `.json` files, pairs them by relative
path, canonicalizes obvious run-specific fields, sorts known unordered tag
lists such as `tags`, `child_tags`, and `parent_tags`, compares numeric values
with a default tolerance of `1e-6`, and reports `PASS` or `FAIL`.

Useful tolerance controls:

```bash
python scripts/compare_indoor_outputs.py \
  --rtol 1e-6 \
  --atol 1e-6 \
  --max-diffs 20 \
  outputs/a/coarse \
  outputs/b/coarse
```

If the script prints `NO_COMPARABLE_JSON_FOUND`, the run is not a pass. Record
that no comparable JSON was available and add a better comparison target before
using the run as evidence.

## Static Blend Scene Comparison

`scripts/compare_blend_static_scene.py` compares two saved `.blend` files, or
two coarse output folders containing `scene.blend`, without saving anything:

```bash
python scripts/compare_blend_static_scene.py outputs/a/coarse outputs/b/coarse
python scripts/compare_blend_static_scene.py left.blend right.blend
```

When `bpy` is not importable from the active Python, the script re-runs itself
under Blender background mode. Set `BLENDER_BIN=/path/to/blender` if the repo
local Blender is not available.

The comparison focuses on the linked static scene that matters for USD/Isaac
static import:

- object count, object names, object types, parents, and visibility
- object location, rotation, scale, and world matrix with tolerance
- linked mesh datablock names and per-object vertex/edge/polygon counts
- material slot names and linked material names
- linked node group names from modifiers and material node trees

It also reports unused mesh/material/node group datablocks separately. Unused
datablock differences should be investigated, but they are not the same as
USD-relevant linked scene differences. The final labels are:

```text
STATIC_SCENE_PASS
STATIC_SCENE_FAIL
USD_RELEVANT_DIFF: yes|no
UNUSED_DATABLOCK_DIFF: yes|no
UNUSED_DATABLOCK_DIFF_ONLY: yes|no
DIFF_CLASS: USD_RELEVANT_DIFF|UNUSED_DATABLOCK_DIFF_ONLY|NO_DIFF
```

Do not use this script to relax the JSON gate by default. Use it to decide
whether a strict JSON failure is accompanied by USD-relevant linked scene
changes, and to separate linked scene differences from unused Blender
datablock churn.

## Determinism Ablation

Before attributing a baseline-vs-candidate difference to an optimization,
verify that the baseline can reproduce itself under the same seed and
configuration:

```bash
EXPERIMENT_SMOKE_SINGLE_ROOM=1 \
EXPERIMENT_TIMEOUT_SECONDS=3600 \
PYTHON_BIN=/home/ubuntu22/miniconda3/envs/infinigen/bin/python \
bash scripts/run_determinism_ablation.sh
```

For a full 10-room diagnostic:

```bash
EXPERIMENT_TIMEOUT_SECONDS=28800 \
PYTHON_BIN=/home/ubuntu22/miniconda3/envs/infinigen/bin/python \
bash scripts/run_determinism_ablation.sh
```

By default, full mode runs baseline A/A only. Set `RUN_CANDIDATE_AA=1` to also
run candidate A/A. Smoke mode runs both baseline A/A and candidate A/A in
`auto` mode.

The 2026-06-20 smoke A/A result:

- baseline A/A JSON compare: `FINAL: PASS`
- candidate A/A JSON compare: `FINAL: PASS`
- baseline A/A static blend compare: `STATIC_SCENE_FAIL`,
  `USD_RELEVANT_DIFF: yes`
- candidate A/A static blend compare: `STATIC_SCENE_FAIL`,
  `USD_RELEVANT_DIFF: yes`

Both static failures were linked scene differences, not
unused-datablock-only differences. This means smoke same-seed baseline is JSON
deterministic but not saved-blend static-scene deterministic under the new
summary comparator.

The 2026-06-20 full 10-room baseline A/A result used:

```text
baseline A: outputs/gc_batch_remove_equiv/baseline/coarse
baseline B: outputs/determinism_full_baseline_b/coarse
```

Baseline B completed with `MAIN TOTAL` `4:25:03.044391`, no timeout, and no
traceback, OOM, killed, or segfault marker. It used the original baseline
behavior with `INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS` unset.

Full baseline A/A JSON comparison:

```text
matched_json_file_count: 2
DIFFERENT MaskTag.json numeric_max_abs_diff=1
  $.back.bottom: left 22, right 21
  $.front.top: left 21, right 22
SAME solve_state.json numeric_max_abs_diff=0
numeric_max_abs_diff: 1
FINAL: FAIL
```

Full baseline A/A static blend diagnostic:

```text
STATIC_SCENE_FAIL
USD_RELEVANT_DIFF: yes
UNUSED_DATABLOCK_DIFF: no
UNUSED_DATABLOCK_DIFF_ONLY: no
static_scene_diff_count: 60
unused_datablock_diff_count: 0
```

This full result changes the interpretation of the batch-remove A/B: the
`MaskTag.json` `front.top` / `back.bottom` label-ID swap and saved-blend
static-scene differences can occur in baseline-vs-baseline. They are not, by
themselves, evidence that `INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1` changed
the scene.

Interpretation rules:

1. If baseline-vs-baseline fails for `MaskTag.json` or linked static scene
   data, redefine the relevant gate before blaming the optimization.
2. If baseline-vs-baseline passes but baseline-vs-candidate fails, the
   optimization is a stronger suspect and should remain opt-in while the
   concrete difference is investigated.
3. Keep strict equivalence, Isaac static scene equivalence, and GT annotation
   equivalence separate. `MaskTag.json` is directly relevant to GT/tag
   segmentation, while linked object/mesh/material/transform differences are
   relevant to USD/Isaac static scenes.
4. Do not promote `INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1` until the relevant
   gate passes on the normal 10-room target.
5. Do not treat a current strict JSON failure as an optimization rejection when
   the same JSON difference appears in baseline A/A. First decide whether the
   nondeterministic field is part of strict reproducibility, GT annotation
   equivalence, Isaac static scene equivalence, or a known baseline artifact.
6. Any compare-policy change must be proposed separately from optimization
   work. Do not silently relax `scripts/compare_indoor_outputs.py`.

## Node Group Batch Remove Experiment

`INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1` is an opt-in experiment only. When
unset, `GarbageCollect` keeps the original individual `node_groups.remove(obj)`
loop. The experiment only targets `bpy.data.node_groups`; meshes, materials,
textures, objects, and other targets continue to use the original individual
remove path.

The removed node group set and skip rules must stay unchanged:

- Skip data-blocks with users when `keep_in_use=True`.
- Skip names listed in `keep_names`.
- Skip names containing `(no gc)`.

Even with the same object set, `bpy.data.batch_remove` may change Blender's
internal deletion order or data-block lifecycle. It must therefore pass a same
seed/gin/task A/B before it can be considered behavior-preserving.

Use the full equivalence A/B:

```bash
EXPERIMENT_TIMEOUT_SECONDS=14400 \
bash scripts/run_gc_batch_remove_equivalence.sh
```

This script does not enable `INFINIGEN_PROFILE_TIMING`,
`INFINIGEN_PROFILE_GC`, `INFINIGEN_PROFILE_ASSET_FACTORY`, or
`INFINIGEN_PROFILE_BBOX`. By default it uses the normal 10-room indoor coarse
target:

```text
seed 0
task coarse
fast_solve.gin
compose_indoors.terrain_enabled=False
home_room_constraints.has_fewer_rooms=False
restrict_solving.solve_max_rooms=10
```

It writes:

```text
outputs/gc_batch_remove_equiv/baseline/coarse
outputs/gc_batch_remove_equiv/candidate_batch/coarse
```

Use the no-instrumentation wall-clock A/B after equivalence:

```bash
EXPERIMENT_TIMEOUT_SECONDS=14400 \
bash scripts/run_gc_batch_remove_walltime.sh
```

The wall-clock script writes `outputs/gc_batch_remove_walltime/summary.txt`
with per-run exit code, wall time, max RSS when available, speedup, and compare
status.

Both scripts support a single-room smoke:

```bash
EXPERIMENT_SMOKE_SINGLE_ROOM=1 \
EXPERIMENT_TIMEOUT_SECONDS=3600 \
bash scripts/run_gc_batch_remove_equivalence.sh
```

Smoke mode adds `singleroom.gin`, sets
`home_room_constraints.has_fewer_rooms=True`, and sets
`restrict_solving.solve_max_rooms=1`. A single-room PASS is useful only for
checking the script and catching obvious differences. It is not evidence that
the normal 10-room target is behavior-preserving or faster.

The 2026-06-19 single-room smoke completed for both new scripts. Equivalence
and wall-clock compares printed `FINAL: PASS` with `matched_json_file_count: 2`
and `numeric_max_abs_diff: 0`. The wall-clock smoke measured baseline
`163.339s` and candidate `163.462s`, or `0.999x`; max RSS was `2,357,896 KB`
for baseline and `2,350,572 KB` for candidate. No traceback, OOM, kill, or
segmentation fault was observed. This validates the harness only; the normal
10-room A/B remains required.

The 2026-06-19 smoke run produced a strong timing signal but did not validate
equivalence: baseline and candidate both timed out, `compare_indoor_outputs.py`
reported `NO_COMPARABLE_JSON_FOUND`, and the final compare status was `FAIL`.
Partial timing showed baseline `node_groups` remove duration at 366.131s and
candidate batch remove duration at 46.350s, while the candidate progressed
farther and removed more node groups. This is not comparable A/B evidence.

Acceptance requires all of the following:

1. The normal 10-room baseline and candidate both complete.
2. `compare_indoor_outputs.py` prints `FINAL: PASS`.
3. The no-heavy-instrumentation wall-clock script shows a speedup.

Do not use this experiment for concurrent throughput work. The current scope is
single indoor coarse scene speed only. Do not tune `manage_jobs.num_concurrent`
or run 32-thread/multiprocess benchmarks until single-scene
behavior-preserving optimization is stable and validated.

## Node Group GC Throttling Experiment

`INFINIGEN_GC_NODE_GROUP_INTERVAL` is an opt-in experiment only. When unset or
set to `1`, `GarbageCollect` keeps the original behavior and cleans
`bpy.data.node_groups` every time. Values greater than `1` skip node group
cleanup opportunities until the interval is due, while other targets such as
meshes, materials, and textures still use the normal cleanup path.

This experiment is risky because delaying node group removal can change Blender
data-block name allocation and can leave residual node groups visible to later
contexts. It is not a C++ optimization; it touches `bpy.data` lifecycle state.

Use the scripted A/B:

```bash
EXPERIMENT_TIMEOUT_SECONDS=1200 bash scripts/run_gc_node_group_experiment.sh
```

If the candidate differs from the baseline, times out without comparable JSON,
or shows obvious errors or memory growth, it must not become a mainline
optimization. If it passes, repeat with a longer profile and explicit memory
observation before considering a narrower opt-in production path.

### 2026-06-19 interval=20 result

The interval=20 smoke did not validate the optimization. Both baseline and
candidate timed out, `compare_indoor_outputs.py` found no comparable JSON, and
the candidate increased raw `node_groups_remove` from 369.071s to 443.414s
despite skipping 558 cleanup opportunities. This points to large burst removes
from broad deferred cleanup.

Do not promote interval=20 and do not continue by simply expanding the
interval. The current next step is attribution: identify the factories and node
group name prefixes that cause removal cost, then consider precise reuse,
caching, or reduced duplicate node group creation. Any such optimization must
be opt-in first and must pass the same seed/gin/task A/B workflow above.

## Attribution-Only Instrumentation

GC attribution timing is allowed as profiling instrumentation because it should
not change generated behavior. The current instrumentation records optional
`GarbageCollect` metadata such as `caller`, `generator_class`, `factory_seed`,
and `inst_seed`, plus bounded node group name prefix/sample summaries when
profiling is enabled.

Attribution data is not equivalence evidence by itself. It only identifies the
next optimization target. If attribution suggests a reusable node group prefix
or a factory-specific cache, validate the resulting candidate with the required
A/B workflow before treating it as behavior-preserving.

## Recommended Scale-Up

Start with a small smoke A/B to verify the comparison workflow itself. A
single-room run is acceptable for the smoke test, but it is only validating the
test harness. It is not evidence that reducing rooms is a valid optimization.

After the smoke test passes, repeat the A/B on the normal indoor coarse target,
including the full room count and normal solve steps used by the baseline.
Keep the scale-up focused on one scene until the behavior-preserving speedup is
accepted. Multi-scene scheduling, 32-thread throughput, and
`manage_jobs.num_concurrent` tuning belong to a later phase.

## Nondeterminism

If Blender or Infinigen shows unavoidable nondeterminism, record the exact
source and the observed differences. Do not mark a run as equivalent just
because the differences are inconvenient. Prefer a tighter targeted comparison
or a repeated-run baseline study over weakening the definition of pass.
