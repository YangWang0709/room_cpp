# NatureShelfTrinketsFactory Investigation

## Isaac Static Quality Status

The expanded shell-like fast stable-pose path is now part of the current
recommended Isaac Sim static 10-room configuration:

```text
INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1
INFINIGEN_REUSE_LARGESHELF_CHILD_NODEGROUPS=1
INFINIGEN_FAST_NATURE_TRINKET_STABLE_POSE=1
restrict_solving.solve_max_rooms=10
populate_doors.door_chance=0
```

This configuration has been manually inspected in Isaac Sim after USD/USDC
export. Visual quality was good, with no obvious issue. The fast stable-pose
path remains opt-in and does not change Infinigen's default behavior. Its
accepted scope is shell-like trinkets; Coral remains excluded because its
shape and `obj2trimesh` cost make it a separate risk.

## Scope

This document records a behavior-preserving investigation of
`NatureShelfTrinketsFactory` as the first populate clutter target after the
solver / GC work. No optimization, concurrency, C++ path, solver change,
random-flow change, or clutter-count reduction is part of this round.

The current accepted Isaac static inspection configuration remains:

```text
INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1
INFINIGEN_REUSE_LARGESHELF_CHILD_NODEGROUPS=1
INFINIGEN_FAST_NATURE_TRINKET_STABLE_POSE=1
restrict_solving.solve_max_rooms=10
populate_doors.door_chance=0
```

## Source Path

`NatureShelfTrinketsFactory` is defined in:

```text
infinigen/assets/objects/elements/nature_shelf_trinkets/generate.py
```

It is exported through:

```text
infinigen/assets/objects/elements/__init__.py
```

It is used as an indoor shelf / handheld object candidate in:

```text
infinigen_examples/constraints/semantics.py
```

## Call Chain

The final populate path is:

```text
infinigen_examples.generate_indoors.compose_indoors()
  Solver.solve()
  populate_state_placeholders(state, final=True)
    for each placeholder with a generator:
      parse_asset_name(placeholder.name) -> inst_seed
      os.generator.spawn_asset(i=inst_seed, loc=placeholder.location, rot=...)
        AssetFactory.spawn_asset()
          spawn_placeholder()
            NatureShelfTrinketsFactory.create_placeholder()
          finalize_placeholders()
          FixedSeed(int_hash((factory_seed, inst_seed)))
          NatureShelfTrinketsFactory.create_asset()
            base_factory.spawn_asset(np.random.randint(1e7), ...)
            optional join_objects(asset.children)
            apply_transform(loc=True)
            apply_modifiers()
            optional obj2trimesh() + trimesh.poses.compute_stable_poses()
            apply_transform(rot=True)
            scale and reposition into placeholder dimensions
            apply_transform(loc=True)
```

`create_placeholder()` creates a small cube with a sampled size in `[0.1, 0.15]`.
The final populate call recreates that placeholder deterministically from the
placeholder seed rather than passing the already solved placeholder object.

## Wrapped Base Factories

`NatureShelfTrinketsFactory.__init__()` samples one base factory per factory
seed:

```text
CoralFactory
BlenderRockFactory
BoulderFactory
PineconeFactory
MolluskFactory
AugerFactory
ClamFactory
ConchFactory
MusselFactory
ScallopFactory
VoluteFactory
CarnivoreFactory
HerbivoreFactory
```

`CarnivoreFactory` and `HerbivoreFactory` are created with `hair=False`.
The other base factories go through the stable-pose path.

## Likely Slow Points

The main suspected slow regions are:

- `base_factory.spawn_asset(...)`: inclusive cost for procedural geometry,
  material creation, texture datablocks, geometry nodes, modifier application,
  remeshing, and garbage collection in the nested `AssetFactory` path.
- `join_objects(list(asset.children))`: relevant when a base factory returns a
  root object with generated child pieces.
- `butil.apply_modifiers(asset)`: can realize geometry and materialized
  modifier output before final placement.
- `obj.obj2trimesh(asset)` plus `trimesh.poses.compute_stable_poses(mesh)`:
  applies to non-creature trinkets and may be expensive for dense coral,
  shell, rock, or plant-like meshes.
- Final scale / bounds / transform work: probably smaller than the base factory
  and stable-pose stages, but now measured separately.

## Materials, Textures, And Node Groups

The wrapper itself does not directly create materials, textures, node groups,
font objects, text objects, or image datablocks. The wrapped factories do.

Observed source-level signals:

- Coral and mollusk paths create procedural shader materials with
  `surface.shaderfunc_to_material(...)`.
- Coral, mollusk, pinecone, boulder, shell, fan, tube, and related paths create
  Blender texture datablocks with `bpy.data.textures.new(...)` for displacement
  or bump variation.
- Creature paths build many procedural parts and can create many geometry node
  groups, meshes, materials, and temporary objects. Many creature part node
  groups are declared with `singleton=False`.
- No direct font/text/image loading path was found in the
  `nature_shelf_trinkets` wrapper. Texture cost here appears to be procedural
  Blender texture datablocks and shader texture nodes, not image files.

## Subobject Signal

`NatureShelfTrinketsFactory.create_asset()` explicitly checks
`list(asset.children)` and joins children when present. That is a direct signal
that some wrapped factories can return multi-object trees. The new timing CSV
records:

```text
asset_children_before_join
asset_tree_object_count_after_spawn
final_asset_child_count
created_object_count
created_mesh_count
```

These fields should separate "one dense object" cases from "many child object"
cases before any reuse proposal.

## Reuse Suitability

Potentially suitable for a later, opt-in reuse experiment:

- Pure shader/node templates whose graph structure is identical and whose
  variation can be preserved by object attributes, material inputs, or copied
  material instances with explicitly varied parameters.
- Procedural texture templates where the datablock structure is repeated and
  per-object variation can remain parameterized without changing random
  consumption or visual diversity.
- Creature or coral geometry node helper groups that are truly fixed-template
  helpers and do not embed per-object sampled values.

Not suitable for first reuse:

- Full generated assets or meshes. That would reduce clutter variation and
  change scene content.
- Stable-pose results, mesh realization, or modifier output. Those are
  object-specific and depend on the generated geometry.
- Materials whose node graph embeds per-object random colors, ramp positions,
  noise settings, or sampled material assignments directly in the datablock.
- Top-level creature/coral/mollusk node groups that encode per-instance shape
  parameters, materials, or random geometry.
- Any reuse path that changes random number consumption, proposal order,
  accept/reject behavior, or final object counts.

## Risks

The main quality risks for reuse are:

- Reduced visual complexity on shelves if many trinkets share materials or
  procedural texture settings too aggressively.
- Broken material diversity, especially for shells, coral, pinecones, and
  creature skins where random color ramps and texture settings are visible.
- Hidden random-flow changes if a reuse path skips code that currently consumes
  random samples.
- Tag or geometry-node side effects from reusing node groups that were authored
  with `singleton=False` because they are expected to be unique.
- Isaac visual regressions if dense clutter becomes repeated, simplified, or
  incorrectly scaled.

## New Timing

Optional instrumentation is enabled with:

```bash
INFINIGEN_PROFILE_NATURE_SHELF_TRINKETS=1
```

Default behavior is unchanged when the variable is unset.

CSV path:

```text
<output_folder>/infinigen_nature_shelf_trinkets_timing.csv
```

Fallback path when the solver output folder cannot be discovered:

```text
/tmp/infinigen_nature_shelf_trinkets_timing.csv
```

Targeted benchmark runs can override the CSV path explicitly with:

```bash
INFINIGEN_NATURE_SHELF_TRINKETS_TIMING_CSV=/path/to/infinigen_nature_shelf_trinkets_timing.csv
```

The timing records the wrapper class, wrapped base factory class, placeholder
name, total duration, substage durations, before/after counts for Blender
materials, textures, node groups, meshes, and objects, created datablock counts,
created material/texture/node-group names, child-object counts, success, and
error type.

Analyze with:

```bash
python scripts/analyze_nature_shelf_trinkets.py \
  outputs/<run>/coarse/infinigen_nature_shelf_trinkets_timing.csv
```

## Targeted Microbenchmark

The full 10-room bounded sample timed out after 1800s inside `[solve_large]`
and did not reach final `populate_assets`, so it could not collect
NatureShelfTrinkets timing rows. To avoid spending full-scene generation time
just to measure this wrapper, this round added:

```text
scripts/bench_nature_shelf_trinkets_factory.py
```

The script creates isolated placeholders, instantiates
`NatureShelfTrinketsFactory(factory_seed)`, calls
`create_asset(inst_seed, placeholder=placeholder)`, records the same timing
CSV, and deletes generated objects after each sample. It does not reuse assets,
does not optimize generation, and does not depend on a complete indoor scene.
It is only a microbenchmark for internal cost attribution, not a replacement
for complete-scene walltime or quality validation.

Run used:

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

Result: `30` successful samples, `0` failures, total measured
`create_asset` time `47.566s`, average `1.586s`, max `5.477s`.

Top base factories by total duration:

| base factory | count | total | avg | max |
| --- | ---: | ---: | ---: | ---: |
| `CoralFactory` | 3 | `13.743s` | `4.581s` | `5.477s` |
| `ClamFactory` | 3 | `7.924s` | `2.641s` | `4.305s` |
| `MusselFactory` | 3 | `6.518s` | `2.173s` | `2.926s` |
| `HerbivoreFactory` | 4 | `6.080s` | `1.520s` | `1.575s` |
| `ConchFactory` | 5 | `4.142s` | `0.828s` | `0.907s` |
| `CarnivoreFactory` | 5 | `3.909s` | `0.782s` | `0.880s` |

Measured substage split:

| substage | total | share |
| --- | ---: | ---: |
| `stable_pose_duration` | `32.143s` | `67.6%` |
| `base_factory_spawn_duration` | `15.275s` | `32.1%` |
| other wrapper stages | about `0.148s` | about `0.3%` |

Created datablocks in the 30-sample microbenchmark:

| kind | total | avg | max |
| --- | ---: | ---: | ---: |
| materials | 46 | 1.533 | 5 |
| textures | 0 | 0.000 | 0 |
| node groups | 68 | 2.267 | 32 |
| meshes | 242 | 8.067 | 36 |
| objects | 75 | 2.500 | 11 |

Interpretation: for this sample, stable-pose computation is the dominant
measured cost, especially for coral, clam, mussel, and conch-like assets.
Creature paths create most materials and node groups, but their total duration
is lower than the stable-pose-heavy shell/coral paths in this isolated sample.

## Stable Pose Complexity Microbenchmark

The timing now also records stable-pose input mesh complexity and pose details:

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
mesh. No cache is used and no stable-pose result is changed.

Run used:

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

Result: `100` successful samples, `0` failures, total measured
`create_asset` time `177.305s`, average `1.773s`, max `7.040s`.

Substage split:

| substage | total | share |
| --- | ---: | ---: |
| `stable_pose_duration` | `95.971s` | `54.1%` |
| `obj2trimesh_duration` | `26.151s` | `14.7%` |
| stable-pose pipeline | `122.121s` | `68.9%` |
| `base_factory_spawn_duration` | `46.610s` | `26.3%` |

Top base factories:

| base factory | count | total | avg | dominant signal |
| --- | ---: | ---: | ---: | --- |
| `ClamFactory` | 11 | `49.970s` | `4.543s` | stable pose |
| `MusselFactory` | 12 | `27.341s` | `2.278s` | stable pose |
| `CoralFactory` | 5 | `25.904s` | `5.181s` | `obj2trimesh` plus stable pose |
| `HerbivoreFactory` | 11 | `18.575s` | `1.689s` | base spawn |
| `CarnivoreFactory` | 14 | `14.111s` | `1.008s` | base spawn |

Mesh complexity and stable-pose signal:

| base factory | avg vertices | avg faces | stable total | stable avg |
| --- | ---: | ---: | ---: | ---: |
| `ClamFactory` | 262,648 | 528,384 | `44.381s` | `4.035s` |
| `MusselFactory` | 264,196 | 528,384 | `21.202s` | `1.767s` |
| `CoralFactory` | 1,719,138 | 3,445,702 | `7.209s` | `1.442s` |
| `ConchFactory` | 176,443 | 352,886 | `6.746s` | `0.519s` |

Across the `75` non-creature stable-pose rows, `stable_pose_duration` and
face / vertex count had low correlation (`0.131`). `stable_pose_duration` and
`stable_pose_count` had a modest correlation (`0.275`). This suggests that
face count alone does not explain the expensive rows. `ClamFactory` produced
the slowest `compute_stable_poses()` rows, while `CoralFactory` produced the
largest meshes and was often dominated by `obj2trimesh`.

Cache signal:

```text
candidate_keys: 75
unique_candidate_keys: 75
repeated_candidate_keys: 0
```

No repeated exact candidate key was observed in this sample, so an exact
stable-pose cache is likely to have limited benefit unless a later full-scene
populate sample shows repeated meshes. Stable-pose simplification or a
mesh-complexity guard is a stronger next investigation, but only as a separate
opt-in experiment with a visual-quality gate.

## Opt-In Fast Shell Stable Pose Experiment

Added an opt-in experiment behind:

```bash
INFINIGEN_FAST_NATURE_TRINKET_STABLE_POSE=1
```

Default behavior is unchanged when the variable is unset. The first accepted
microbenchmark covered only `ClamFactory`, `MusselFactory`, and
`ScallopFactory`. The current expanded fast-pose experiment remains narrow but
now applies to these shell-like wrapped base factories:

```text
ClamFactory
MusselFactory
ScallopFactory
ConchFactory
AugerFactory
VoluteFactory
MolluskFactory
```

Fast mode does not change `base_factory.spawn_asset()`, object count, mesh
creation, materials, textures, node groups, solver behavior, or room / clutter
counts. It skips `obj2trimesh()` and
`trimesh.poses.compute_stable_poses()` for those three factories and leaves
the generated asset in its base-factory orientation. The existing later scale
and bbox bottom-alignment code still places the trinket into the placeholder.
No extra random yaw is sampled, so the experiment does not intentionally
change random-number consumption.

Fast mode does not apply to:

```text
CoralFactory
HerbivoreFactory
CarnivoreFactory
PineconeFactory
BlenderRockFactory
BoulderFactory
```

Coral is deliberately excluded because it has large `obj2trimesh` conversion
cost and more complex shape / support risk.

New timing fields:

```text
fast_stable_pose_enabled
fast_stable_pose_used
stable_pose_mode
fast_stable_pose_duration
skipped_compute_stable_poses
```

An unfiltered 100-sample baseline completed with `100` rows and `0` failures.
The matching unfiltered candidate was started with fast mode enabled, but it
stalled on sample 14, a non-fast `CoralFactory` row, and was terminated after
the Python signal timeout did not interrupt the underlying computation. That
partial run is not used as speed evidence for fast shell pose.

To isolate the intended fast-mode scope, a filtered shell-only A/B was run
with:

```bash
--base-factory-filter ClamFactory,MusselFactory,ScallopFactory
```

The filter uses seed rejection and does not override
`NatureShelfTrinketsFactory` base-factory selection.

Shell-only A/B result:

| metric | baseline | candidate |
| --- | ---: | ---: |
| CSV data rows | 100 | 100 |
| failures | 0 | 0 |
| total duration | `268.269s` | `10.937s` |
| `stable_pose_duration` | `217.894s` | `0.000s` |
| `obj2trimesh_duration` | `31.233s` | `0.000s` |
| fast rows used | 0 | 100 |
| skipped compute rows | 0 | 100 |
| meshes created | 100 | 100 |
| objects created | 100 | 100 |
| materials created | 0 | 0 |

Per base factory shell speedup:

| base factory | baseline total | candidate total | speedup |
| --- | ---: | ---: | ---: |
| `ClamFactory` | `128.370s` | `4.173s` | `30.8x` |
| `MusselFactory` | `76.398s` | `3.594s` | `21.3x` |
| `ScallopFactory` | `63.502s` | `3.171s` | `20.0x` |

The expanded shell-like A/B used:

```bash
--base-factory-filter ClamFactory,MusselFactory,ScallopFactory,ConchFactory,AugerFactory,VoluteFactory,MolluskFactory
```

Expanded shell result:

| metric | baseline | candidate |
| --- | ---: | ---: |
| CSV data rows | 100 | 100 |
| failures | 0 | 0 |
| total duration | `153.955s` | `8.200s` |
| total speedup |  | `18.8x` |
| `stable_pose_duration` | `120.248s` | `0.000s` |
| `obj2trimesh_duration` | `19.937s` | `0.000s` |
| fast rows used | 0 | 100 |
| skipped compute rows | 0 | 100 |
| meshes created | 100 | 100 |
| objects created | 100 | 100 |
| materials created | 0 | 0 |

Expanded per-base speedup:

| base factory | baseline total | candidate total | speedup |
| --- | ---: | ---: | ---: |
| `ClamFactory` | `59.276s` | `1.554s` | `38.1x` |
| `MusselFactory` | `35.428s` | `1.632s` | `21.7x` |
| `ScallopFactory` | `19.167s` | `1.055s` | `18.2x` |
| `ConchFactory` | `12.393s` | `1.317s` | `9.4x` |
| `AugerFactory` | `10.930s` | `1.124s` | `9.7x` |
| `MolluskFactory` | `9.971s` | `0.990s` | `10.1x` |
| `VoluteFactory` | `6.791s` | `0.528s` | `12.9x` |

A small fast-mode visual check blend was generated for manual inspection:

```text
outputs/bench_nature_shelf_trinkets_pose_ab/visual_check_fast_shell/nature_shelf_trinkets_bench.blend
outputs/bench_nature_fast_pose_expanded_shell/visual_check_fast/nature_shelf_trinkets_bench.blend
```

The expanded visual file contains 16 fast-mode samples arranged in a grid,
including the new shell-like families selected by seed rejection. These
outputs are intentionally not committed. They must be opened manually in
Blender or Isaac before accepting the experiment. Inspect for obvious
floating, inverted placement, bad bottom alignment, shelf-surface
intersection, or unacceptable loss of orientation quality.

## Current Judgment

The recent complete 10-room proxy log points to populate clutter as the new
bottleneck after solver / GC work. `NatureShelfTrinketsFactory` is the first
priority because the proxy populate phase spent about `1921.3s` across `76`
instances. `BookStackFactory` and `LargePlantContainerFactory` remain the next
populate targets.

The current source review supports material / texture / node-group reuse as a
plausible next investigation, but not as an accepted optimization yet. The new
CSV should be used first to identify which wrapped base factories create the
largest repeated datablock patterns and whether runtime is dominated by
datablock creation, mesh realization, or stable-pose computation.

Next investigation should start with the stable-pose-heavy base factories
before broad material or node-group reuse. If a later larger sample shows
`base_factory.spawn_asset` dominating instead, inspect the concrete wrapped
base factory first. If material / texture / node-group creation dominates,
consider only a narrow opt-in material or template reuse experiment with a
separate visual-quality gate.

After the 100-sample complexity benchmark, the next most useful source
investigation is more specific: inspect `ClamFactory` stable-pose input and
`trimesh.poses.compute_stable_poses()` behavior first, then `MusselFactory`,
then `CoralFactory` `obj2trimesh` conversion for very large meshes. Material,
texture, and node-group creation remain secondary for this benchmark.
