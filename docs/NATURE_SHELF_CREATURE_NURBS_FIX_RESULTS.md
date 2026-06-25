# NatureShelf Creature NURBS Fix Results

## Root Cause

`NatureShelfTrinketsFactory` includes `CarnivoreFactory` and
`HerbivoreFactory` by default. Those factories sample `NurbsBody` and
`NurbsHead` parts from `infinigen/assets/objects/creatures/parts/nurbs_data`.

The `nurbs_data` directory was present but empty in this snapshot. Because
`*.npy` is ignored globally, the source NURBS templates had not been tracked.
With no template keys, `NurbsPart.sample_params()` computed `handles` as the
integer `0`, which then reached `lofting.factorize_nurbs_handles()` and failed
with:

```text
AttributeError: 'int' object has no attribute 'mean'
```

## Fix

- Restored the 30 creature NURBS `.npy` templates from upstream Infinigen commit
  `05a09759fe9478595a3323ec2d6e26ce3513223f`.
- Added a `.gitignore` exception so the required source templates under
  `infinigen/assets/objects/creatures/parts/nurbs_data/` are tracked.
- Added regression coverage in `tests/test_nature_shelf_trinkets_factory.py`
  that verifies the required carnivore/herbivore template prefixes are present
  and that `carnivore.tiger_genome()` and `herbivore.herbivore_genome()` can
  sample their NURBS parameters. The same test file also exercises the
  `CarnivoreFactory.create_asset()` and `HerbivoreFactory.create_asset()` paths
  with Blender-heavy postprocessing stubbed out, so the factory-level genome
  sampling path is covered without a full asset build.

The temporary `INFINIGEN_DISABLE_NATURE_SHELF_CREATURE_TRINKETS` workaround was
not changed and remains opt-in only.

## Verification

| Check | Result |
| --- | --- |
| `py_compile tests/test_nature_shelf_trinkets_factory.py` | Passed |
| `pytest tests/test_nature_shelf_trinkets_factory.py -q` | `11 passed, 1 warning` |
| unfiltered NatureShelf 20-sample benchmark | 20 success, 0 failures |
| unfiltered NatureShelf 100-sample benchmark | 100 success, 0 failures |
| unfiltered 1-room cpp smoke | Success, `scene.blend` written |
| unfiltered 10-room cpp smoke | Success, `scene.blend` written |

Unfiltered 100-sample benchmark coverage:

| Factory | Count |
| --- | ---: |
| `CarnivoreFactory` | 14 |
| `HerbivoreFactory` | 11 |

Scene smoke results:

| Run | Result | MAIN TOTAL | Output |
| --- | --- | --- | --- |
| 1-room cpp, unfiltered | Success | `0:02:23.320826` | `outputs/smoke_nature_shelf_creatures_unfiltered/one_room_cpp_seed0/coarse/scene.blend` |
| 10-room cpp, unfiltered | Success | `3:43:25.207662` | `outputs/smoke_nature_shelf_creatures_unfiltered/ten_room_cpp_seed0/coarse/scene.blend` |

Exact error scans found no matches for `AttributeError`,
`'int' object has no attribute 'mean'`, `Traceback`, `Exception`,
`StablePoseValidationError`, `canary failed`, or `fallback` in the unfiltered
NatureShelf benchmark and scene-smoke logs.

The 1-room and 10-room scene logs still contain continuing solver warnings of
the form `Solver has failed to satisfy constraints`, matching previous smoke
runs. Blender also reports tiny unfreed-memory notes on exit. These are not
creature NURBS or stable-pose failures.
