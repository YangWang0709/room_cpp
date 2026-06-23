# LargeShelf Node Group Investigation

Date: 2026-06-21

## Isaac Static Quality Status

`INFINIGEN_REUSE_LARGESHELF_CHILD_NODEGROUPS=1` is now part of the current
recommended Isaac Sim static 10-room configuration:

```text
INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1
INFINIGEN_REUSE_LARGESHELF_CHILD_NODEGROUPS=1
INFINIGEN_FAST_NATURE_TRINKET_STABLE_POSE=1
restrict_solving.solve_max_rooms=10
populate_doors.door_chance=0
```

This combined opt-in configuration has been manually inspected in Isaac Sim
after USD/USDC export. Visual quality was good, with no obvious quality issue.
The LargeShelf child node-group reuse remains opt-in and default-off. Do not
expand reuse to top-level shelf node groups, tagged support node groups, or
other factories without a separate investigation and quality gate.

## Scope

This document tracks the `LargeShelfFactory` shelf node group generation path
and the first opt-in child node group reuse experiment. The reuse experiment
does not change solver behavior, random number flow, proposal / accept /
reject logic, `batch_remove` behavior, C++ code, concurrent execution, or door
logic. Default behavior remains unchanged unless
`INFINIGEN_REUSE_LARGESHELF_CHILD_NODEGROUPS=1` is set.

## Opt-In Child Reuse Experiment - 2026-06-21

First-round reuse was added only for the child node groups that are pure
parameterized geometry templates:

| cached prefix | cache key |
| --- | --- |
| `nodegroup_screw_head` | function name |
| `nodegroup_side_board` | function name |
| `nodegroup_bottom_board` | function name |
| `nodegroup_back_board` | function name |

The cache is module-level and enabled only with:

```bash
INFINIGEN_REUSE_LARGESHELF_CHILD_NODEGROUPS=1
```

The cache checks that the cached Blender node group datablock is still live
before returning it. If Blender has removed the datablock, the entry is
discarded and the node group is recreated normally. Exceptions from node group
creation are not swallowed.

The first experiment deliberately does not reuse:

| prefix | reason |
| --- | --- |
| top-level `geometry_nodes` | embeds per-object arrays, scalar defaults, and material objects |
| `nodegroup_division_board` | participates in the tagged support path and has inclusive nested timing |
| `nodegroup_tagged_cube` | writes the `TAG_support_surface` attribute through `tagging.tag_nodegroup` |

When `INFINIGEN_PROFILE_SHELF_NODEGROUPS=1` is enabled, the CSV now also
records `reuse_enabled`, `cache_hit`, `cache_key`, `cache_size`, and
`returned_nodegroup_name`. The analyzer reports cache hits, misses, hit rate,
estimated saved create calls, and per-prefix reused summaries.

### Short A/B Timing Sample

A bounded 900s timing sample was run for baseline and candidate with:

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
```

The candidate additionally set:

```bash
INFINIGEN_REUSE_LARGESHELF_CHILD_NODEGROUPS=1
```

Both runs exited with `timeout` code `124` at 900s. This is a short timing
sample only, not a complete coarse profile and not a quality gate. No
traceback, OOM, or segfault was observed in either run.

CSV paths:

```text
outputs/profile_shelf_reuse_ab/baseline/coarse/infinigen_shelf_nodegroup_timing.csv
outputs/profile_shelf_reuse_ab/candidate/coarse/infinigen_shelf_nodegroup_timing.csv
```

Summary:

| metric | baseline | candidate |
| --- | ---: | ---: |
| CSV data rows | 5,918 | 5,918 |
| `LargeShelfFactory` spawns | 163 | 163 |
| actual node groups created | 5,918 | 3,363 |
| mean actual node groups per spawn | 36.307 | 20.632 |
| `spawn_summary` total duration | 60.096s | 36.718s |
| `spawn_summary` mean duration | 0.369s | 0.225s |
| cache hit count | 0 | 2,555 |
| cache miss count | 0 | 86 |
| cache hit rate | 0.000% | 96.744% |

Target prefix timing:

| prefix | baseline duration | candidate duration | baseline calls | candidate calls |
| --- | ---: | ---: | ---: | ---: |
| `nodegroup_screw_head` | 14.993s | 0.095s | 1,557 | 1,557 |
| `nodegroup_side_board` | 3.400s | 0.144s | 614 | 614 |
| `nodegroup_bottom_board` | 2.001s | 0.153s | 307 | 307 |
| `nodegroup_back_board` | 1.023s | 0.146s | 163 | 163 |

The target-prefix duration total dropped from `21.417s` to `0.538s` in the
matched 163-spawn sample. Actual created node groups dropped by `2,555`, which
matches the candidate cache hit count.

Judgment: the opt-in child reuse experiment has a clear timing signal and is
worth a full 10-room Isaac static quality validation before considering any
broader reuse. Do not expand reuse to `nodegroup_division_board`,
`nodegroup_tagged_cube`, or top-level `geometry_nodes` until this first child
reuse path passes quality validation.

## Timing Sample - 2026-06-21

A bounded timing sample was collected with:

```bash
INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1
INFINIGEN_PROFILE_SHELF_NODEGROUPS=1
--seed 0
--task coarse
-g fast_solve.gin
restrict_solving.solve_max_rooms=10
populate_doors.door_chance=0
```

The valid run used the current host checkout at
`9f183b83346acb90c66c9a39aa48c7090ce01287`. The `/opt/infinigen`
container checkout was stale during this round, so the container attempt is
not used as timing evidence.

The valid run timed out at `3600s`, so this is not a complete coarse profile.
It still produced:

```text
outputs/profile_shelf_nodegroups_seed0/coarse/infinigen_shelf_nodegroup_timing.csv
```

CSV row counts:

| metric | value |
| --- | ---: |
| file lines including header | 24,525 |
| CSV data rows | 24,524 |
| `nodegroup_create` rows | 23,083 |
| `spawn_summary` rows | 1,441 |

LargeShelf spawn summary:

| metric | value |
| --- | ---: |
| LargeShelfFactory spawns | 1,441 |
| total `spawn_summary` duration | 549.705s |
| mean `spawn_summary` duration | 0.381s |
| mean node groups created per spawn | 17.019 |
| min / max node groups created per spawn | 14 / 74 |

The per-spawn node group count includes the per-object top-level
`geometry_nodes` tree. The child node group average is about `16.019` calls per
spawn.

Prefix totals from `nodegroup_create` rows:

| prefix | calls | total duration | mean duration |
| --- | ---: | ---: | ---: |
| `nodegroup_division_board` | 5,629 | 278.151s | 0.049s |
| `nodegroup_screw_head` | 5,629 | 125.246s | 0.022s |
| `nodegroup_side_board` | 3,170 | 43.601s | 0.014s |
| `nodegroup_tagged_cube` | 5,629 | 37.736s | 0.007s |
| `nodegroup_bottom_board` | 1,585 | 25.735s | 0.016s |
| `nodegroup_back_board` | 1,441 | 23.490s | 0.016s |

There are only six shelf child prefixes in this CSV, so the top-20 prefix
tables contain these six rows.

The first-round child reuse candidates requested for this investigation
accounted for:

```text
nodegroup_screw_head + nodegroup_side_board +
nodegroup_bottom_board + nodegroup_back_board = 218.072s
```

That is about `6.1%` of the `3600s` bounded run. The inclusive prefix duration
sum is `533.958s`, but it double-counts nested work because
`nodegroup_division_board` includes the nested `nodegroup_tagged_cube` and
`nodegroup_screw_head` calls.

Judgment: shelf child node group creation is a real secondary bottleneck in
this timeout sample and is worth a small opt-in reuse experiment. It is not a
replacement for `batch_remove`: `batch_remove` remains the main deletion-cost
switch, while reuse would target repeated creation cost.

## Source Path

`LargeShelfFactory` is defined in:

```text
infinigen/assets/objects/shelves/large_shelf.py
```

It is re-exported from:

```text
infinigen/assets/objects/shelves/__init__.py
```

## Creation Chain

The active chain is:

```text
LargeShelfFactory.sample_params()
LargeShelfBaseFactory.create_asset()
  get_asset_params()
    sample_params()
    update_translation_params()
    get_material_func()
  surface.add_geomod(obj, geometry_nodes, apply=True, input_kwargs=obj_params)
    geometry_nodes(...)
      nodegroup_side_board()
      nodegroup_back_board()
      nodegroup_bottom_board()
      nodegroup_division_board(material=board_material, tag_support=True)
        nodegroup_tagged_cube()
        nodegroup_screw_head()
  tagging.tag_system.relabel_obj(obj)
```

`surface.add_geomod(..., apply=True)` creates and applies the top-level
geometry node modifier. The top-level `geometry_nodes` tree is per-spawn
because it bakes this shelf's sampled dimensions, per-cell arrays, and material
objects into value and material nodes.

## High Frequency Prefix Sources

The searched prefixes come from these locations:

| prefix | source | call frequency per shelf spawn |
| --- | --- | --- |
| `nodegroup_tagged_cube` | `infinigen/assets/objects/shelves/utils.py` | one per division board when `tag_support=True` |
| `nodegroup_division_board` | `large_shelf.py` | `len(shelf_cell_width) * len(division_board_z_translation)` |
| `nodegroup_screw_head` | `large_shelf.py` | one per division board |
| `nodegroup_side_board` | `large_shelf.py` | `len(side_board_x_translation)` |
| `nodegroup_bottom_board` | `large_shelf.py` | `len(shelf_cell_width)` |
| `nodegroup_back_board` | `large_shelf.py` | one per shelf spawn |

For `LargeShelfFactory`, `tag_support` is set to `True` in
`get_asset_params()`, so the `tagged_cube` path is normally active.

## New vs Reused Today

All high-frequency shelf child node groups are decorated with:

```text
@node_utils.to_nodegroup(..., singleton=False, type="GeometryNodeTree")
```

`node_utils.to_nodegroup(..., singleton=False)` always calls
`bpy.data.node_groups.new(name, type)` when the decorated function is invoked.
Therefore these child node groups are newly created for each call today.
Blender then suffixes repeated datablock names, such as
`nodegroup_screw_head.001`.

## Randomness And Parameters

The child node group creation functions inspected here do not call NumPy
random APIs directly. Random sampling happens earlier in `get_asset_params()`,
where dimensions, cell counts, screw parameters, attachment parameters, and
material labels are sampled.

Most per-object variation enters the child groups through exposed node group
inputs:

- width, depth, height, thickness
- x/z translations
- screw radius/depth/gaps
- tag support mode for division boards

`nodegroup_division_board(material, tag_support=False)` accepts a `material`
argument, but the inspected function body does not use it. The actual shelf
materials are assigned in the parent `geometry_nodes` tree with
`Nodes.SetMaterial`.

## Side Effects

There are still Blender-visible side effects that make reuse a validation
problem rather than a mechanical refactor:

- Each `singleton=False` call creates a new `bpy.data.node_groups` datablock
  with Blender-managed naming and lifecycle.
- `nodegroup_tagged_cube` stores the `TAG_support_surface` face attribute via
  `tagging.tag_nodegroup`.
- The parent `geometry_nodes` tree assigns `frame_material` and
  `board_material` through `SetMaterial`.
- `get_material_func()` creates material datablocks before the geometry node
  modifier is built.
- `tagging.tag_system.relabel_obj(obj)` consumes the applied geometry tag
  attributes after the modifier is applied.

Changing child node group identity may change unused datablock inventories,
Blender name allocation, or tag/material lifecycle details even when final
geometry appears unchanged. That risk is especially relevant because current
baseline A/A diagnostics already show strict JSON and saved-blend instability.

## Looks Reusable

These child groups looked like good first opt-in reuse candidates after timing
confirmed their creation cost, and they are the only groups enabled by
`INFINIGEN_REUSE_LARGESHELF_CHILD_NODEGROUPS=1` today:

- `nodegroup_screw_head`: pure parameterized geometry; no material, tag, or
  random dependency was found.
- `nodegroup_side_board`: pure parameterized board geometry.
- `nodegroup_bottom_board`: pure parameterized board geometry.
- `nodegroup_back_board`: pure parameterized board geometry.

`nodegroup_tagged_cube` and `nodegroup_division_board` may still be theoretical
future candidates, but they are deliberately deferred. `nodegroup_tagged_cube`
stores a tag attribute, and `nodegroup_division_board` participates in the
tag-support path and has inclusive nested timing. If either is revisited later,
it needs separate opt-in gating, cache keys for any graph-shaping arguments
such as `tag_support`, and a tag/material quality check.

## Not Suitable For First Reuse

The top-level `geometry_nodes` modifier tree should not be the first reuse
target. It embeds per-shelf sampled arrays, scalar value defaults, and material
objects into the graph. Reusing it would require a larger parameterization
rewrite and would be more likely to change behavior.

`nodegroup_division_board` and `nodegroup_tagged_cube` should also stay out of
the first reuse experiment. `nodegroup_division_board` is the largest measured
prefix, but its duration is inclusive of nested tagged-cube and screw-head
creation, and it participates in `tag_support=True` geometry. `tagged_cube`
stores the support-surface tag attribute. Reusing either one first would mix
performance work with tag/material lifecycle risk.

Broad delayed cleanup is also not the next path. The interval cleanup smoke
already showed large burst removals. `batch_remove` addresses deletion cost
when enabled, but it does not reduce duplicate node group creation cost.

## Instrumentation Added

`INFINIGEN_PROFILE_SHELF_NODEGROUPS=1` enables opt-in timing only for this
path. When unset, no CSV is written and generation behavior should remain the
same.

When enabled, `large_shelf.py` writes:

```text
infinigen_shelf_nodegroup_timing.csv
```

under the solver output folder when available, otherwise under `/tmp`.

The CSV records:

- each profiled child node group creation call
- inclusive duration for that creation call
- node group counts before and after the call
- new node group names created by that call
- per-spawn actual node group count before and after `create_asset`
- per-spawn child node group prefix call counts
- per-spawn actual created node group prefix counts

The `nodegroup_division_board` duration is inclusive of its nested
`nodegroup_tagged_cube` and `nodegroup_screw_head` calls. The analyzer reports
prefix call counts separately, so nested repeated templates remain visible.

Analyze the CSV with:

```bash
python scripts/analyze_shelf_nodegroups.py \
  outputs/<run>/coarse/infinigen_shelf_nodegroup_timing.csv
```

## Recommended Next Opt-In Experiment

The timing sample crossed the threshold for a small opt-in reuse experiment,
not a solver change:

1. Keep `INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1` as the separate opt-in
   deletion-cost switch; do not change its behavior.
2. Add a new opt-in shelf child node group reuse flag, for example
   `INFINIGEN_REUSE_SHELF_NODEGROUPS=1`.
3. Start with `nodegroup_screw_head`, `nodegroup_side_board`,
   `nodegroup_bottom_board`, and `nodegroup_back_board`.
4. Treat `nodegroup_tagged_cube` and `nodegroup_division_board` as second
   phase reuse candidates because of tag-support behavior.
5. Do not reuse the top-level `geometry_nodes` tree in the first experiment.
6. Validate with the normal single-scene indoor coarse target and the current
   acceptance criteria: realistic rendering, no obvious complexity loss, no
   obvious bugs, Isaac Sim usable, no door panels, and door openings retained.
   Default Isaac tests should keep `populate_doors.door_chance=0`.
7. Do not run concurrent benchmarks for this phase.
