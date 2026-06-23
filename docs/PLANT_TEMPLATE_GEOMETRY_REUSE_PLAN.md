# Plant Template Geometry Reuse Plan

## Scope

This tracks the opt-in Plant geometry reuse experiment. The first implemented
version only affects `WheatMonocotFactory` when explicitly enabled with:

```bash
INFINIGEN_REUSE_PLANT_TEMPLATE_GEOMETRY=1
```

The stable Isaac Sim static script
`scripts/run_isaac_static_optimized_10room.sh` remains unchanged, so the
current recommended full 10-room path does not enable this Plant experiment.

Guardrails:

- Keep default Infinigen behavior unchanged.
- Do not reduce plant count, leaf count, stem count, branch count, or visible
  plant complexity.
- Do not make all Plant assets share one template.
- Do not add concurrency or C++.
- Do not reuse materials as the first Plant optimization path.
- Any future switch must remain default-off and pass Blender/Isaac visual
  quality checks.
- Do not treat this as a bitwise-equivalent optimization. The Wheat v1 cache
  skips raw leaf/stem random generation on cache hits, so it changes internal
  Wheat random consumption by design.

## Source Paths

Container and benchmark target:

```text
infinigen/assets/objects/tableware/plant_container.py
```

Concrete monocot selection:

```text
infinigen/assets/objects/monocot/generate.py
```

Shared monocot growth implementation:

```text
infinigen/assets/objects/monocot/growth.py
```

Focused concrete factories:

```text
WheatMonocotFactory    infinigen/assets/objects/monocot/grasses.py
GrassesMonocotFactory  infinigen/assets/objects/monocot/grasses.py
VeratrumMonocotFactory infinigen/assets/objects/monocot/veratrum.py
AgaveMonocotFactory    infinigen/assets/objects/monocot/agave.py
```

## Call Chain

`LargePlantContainerFactory` uses:

```text
PlantContainerFactory.create_asset()
  self.plant_factory.spawn_asset(...)
    MonocotFactory.create_asset()
      concrete_monocot_factory.create_asset()
```

Common monocot path:

```text
MonocotGrowthFactory.create_asset()
  create_raw()
    make_collection()
      build_instance()
        build_leaf()
    build_stem()
    surface.add_geomod(make_geo_flower(), apply=True)
  decorate_monocot()
```

Factory-specific additions:

- `WheatMonocotFactory.create_asset()` calls the grass raw path, then creates
  an `ear_factory` asset, bends / rotates / places it, joins it with the grass
  stalk, and decorates the result.
- `GrassesMonocotFactory` relies mostly on repeated grass leaf and stem
  geometry; `MonocotFactory` may create and join several grass instances.
- `VeratrumMonocotFactory.create_asset()` creates raw leaves/stem, then calls a
  nested `branches_factory.create_asset()` that creates multiple ear-like
  branch assets.
- `AgaveMonocotFactory.build_leaf()` creates heavier leaf geometry with
  per-leaf deformation, boundary distance, deep-cloned profile pieces,
  displacement, joins, welds, and optional random cutting.

## Per-Instance Random Dependencies

The focused factories use per-instance random values for leaf count, stem
height, leaf angles, leaf widths, bend angles, phyllotaxis / offsets, branch or
ear placement, material/color parameters, and modifier parameters.

`WheatMonocotFactory` and `GrassesMonocotFactory` are still random, but their
leaf/stem construction is more regular than Agave or Veratrum. They are better
first candidates for a narrow opt-in template experiment if the template keeps
instance transforms, scale, yaw, and material assignment varied.

`VeratrumMonocotFactory` and `AgaveMonocotFactory` are high risk. Their
branching, leaf deformation, and silhouette variation are visually important,
and full template reuse could make plants look copied or biologically wrong.

## Possible Reuse Units

Implemented v1 reuse unit:

- `WheatMonocotFactory.create_raw()` mesh data after leaf/stem geometry and
  the applied `make_geo_flower()` geometry-node step. Cache misses run the
  original raw path and store a mesh datablock. Cache hits create a new object
  from a copied cached mesh datablock.

Still generated per instance:

- Wheat ear geometry from `WheatEarMonocotFactory.create_asset()`.
- The random bend applied to the ear.
- Final `decorate_monocot()` twist / bend / scale / yaw and material
  assignment.
- The surrounding `MonocotFactory` grass cluster placement and final
  `join_objects()` behavior.

Not reused:

- Complete Wheat plant objects.
- Complete `LargePlantContainerFactory` pot + dirt + plant assemblies.
- `GrassesMonocotFactory`, `VeratrumMonocotFactory`, `AgaveMonocotFactory`,
  `MaizeMonocotFactory`, or any non-Wheat Plant factory.

The v1 cache key includes the concrete factory class, reuse scope,
`factory_seed`, coarse flag, `face_size`, `apply`, and structural Wheat growth
parameters such as count, stem offset, normalized angle, leaf range, scale
curve, perturbation, and radius. It is a template-bucket key, not a claim that
every skipped raw mesh would have been identical under the original random
flow.

Lower-risk candidates for a future experiment:

- A narrow `GrassesMonocotFactory` or `WheatMonocotFactory` leaf/stem helper
  mesh template, with per-instance transforms and scaling preserved.
- Wheat ear helper geometry only if its bend/orientation and placement remain
  per instance.
- Fixed helper node groups only after proving they do not encode object,
  material, tag, or shape-specific state.

Do not reuse yet:

- Full plant meshes.
- Whole pot+plant+dirt assemblies.
- Top-level geometry nodes that contain per-instance shape parameters.
- Agave leaves as a first pass.
- Veratrum branch systems as a first pass.

## New Timing Evidence

The 50-sample concrete-deep benchmark used:

```bash
INFINIGEN_PROFILE_PLANT_ASSETS=1 \
python scripts/bench_plant_assets_factory.py \
  --samples 50 \
  --seed 0 \
  --output_folder outputs/bench_plant_assets_concrete_deep
```

Result: `50/50` samples, `0` failures, CSV rows `50`, measured total
`214.538s`, benchmark wall time `217.514s`. The dominant measured stage was
`plant_spawn_duration` at `170.618s`. Material generation was `0.991s`, so
Plant material reuse is not the first priority.

Concrete duration top:

| factory | count | total | avg | max |
| --- | ---: | ---: | ---: | ---: |
| `WheatMonocotFactory` | 7 | `50.353s` | `7.193s` | `13.230s` |
| `VeratrumMonocotFactory` | 8 | `39.694s` | `4.962s` | `6.107s` |
| `GrassesMonocotFactory` | 8 | `37.763s` | `4.720s` | `7.701s` |
| `AgaveMonocotFactory` | 4 | `22.650s` | `5.663s` | `6.486s` |
| `MaizeMonocotFactory` | 7 | `21.643s` | `3.092s` | `5.204s` |

Leaf / stem / branch geometry totals by focused factory:

| factory | leaf | stem | branch | total |
| --- | ---: | ---: | ---: | ---: |
| `WheatMonocotFactory` | `12.834s` | `10.326s` | `14.420s` | `37.580s` |
| `GrassesMonocotFactory` | `14.953s` | `12.413s` | `0.000s` | `27.365s` |
| `VeratrumMonocotFactory` | `7.650s` | `4.029s` | `16.270s` | `27.949s` |
| `AgaveMonocotFactory` | `13.260s` | `0.572s` | `0.000s` | `13.832s` |

`geometry_template_candidate_key` repeated at the concrete factory level, but
this key is intentionally coarse. A repeated key means "same concrete factory
shape family", not "identical mesh safe to cache". A future implementation
needs a stricter template key or a deliberate template bucket design.

## Recommendation

The first implementation candidate has now been tried as a narrow opt-in
`WheatMonocotFactory` raw-mesh template experiment. `GrassesMonocotFactory`
remains the second candidate, but should not be enabled until Wheat passes
manual Blender/Isaac visual review.

Do not start with `VeratrumMonocotFactory` or `AgaveMonocotFactory`. They are
worth further profiling, but their geometry is higher risk for visual quality
and random-shape diversity.

## Wheat V1 A/B Result

Command pair:

```bash
INFINIGEN_PROFILE_PLANT_ASSETS=1 \
python scripts/bench_plant_assets_factory.py \
  --samples 30 \
  --seed 0 \
  --concrete-plant-filter WheatMonocotFactory \
  --output_folder outputs/bench_wheat_template_reuse_ab/baseline

INFINIGEN_PROFILE_PLANT_ASSETS=1 \
INFINIGEN_REUSE_PLANT_TEMPLATE_GEOMETRY=1 \
python scripts/bench_plant_assets_factory.py \
  --samples 30 \
  --seed 0 \
  --concrete-plant-filter WheatMonocotFactory \
  --output_folder outputs/bench_wheat_template_reuse_ab/candidate_reuse
```

| metric | baseline | candidate |
| --- | ---: | ---: |
| rows | 30 | 30 |
| failures | 0 | 0 |
| measured total | `229.654s` | `144.198s` |
| benchmark wall time | `236.935s` | `149.062s` |
| avg duration | `7.655s` | `4.807s` |
| max duration | `14.606s` | `7.445s` |
| `plant_spawn_duration` | `203.202s` | `117.766s` |
| `leaf_generation_duration` | `58.830s` | `18.603s` |
| `stem_generation_duration` | `46.990s` | `16.119s` |
| `branch_generation_duration` | `66.677s` | `62.409s` |
| created meshes | 1,910 | 1,418 |
| created objects | 1,790 | 1,210 |

Candidate cache stats:

```text
cache_hits: 58
cache_misses: 30
cache_hit_rate: 65.909%
fallback_count: 0
reuse_scope: wheat_create_raw_mesh
unique_cache_keys: 30
```

Visual check blend:

```text
outputs/bench_wheat_template_reuse_ab/visual_check_wheat/wheat_template_reuse_check.blend
```

Manual review should check whether Wheat looks obviously copied, whether
leaves/stems/ears look normal, and whether there are flying, scaling, or severe
intersection issues. Do not move this into full 10-room quality validation
until the small visual check looks acceptable.
