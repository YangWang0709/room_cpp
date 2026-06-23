# C++ Stable Pose Visual / 1-room Smoke Results

## Environment

| Item | Value |
| --- | --- |
| Date | 2026-06-24 |
| Repository | `/home/ubuntu22/infinigen/repo_snapshot` |
| Opt-in filter commit | `b9de29374d6db12d5a65e657afa57e1e29b1790e` |
| Python | `3.11.15` |
| trimesh | `3.22.5` |

## Current Status

The C++ stable pose visual check passed before the no-creature 1-room smoke:

| Check | Result |
| --- | --- |
| `baseline_30` blend generated | Pass |
| `cpp_30` blend generated | Pass |
| `cpp_canary_30` blend generated | Pass |
| baseline/cpp/cpp+canary mesh transforms | Matched exactly for 60 mesh objects |
| Obvious floating / upside-down / intersection issues | None observed |
| visual fallback / canary failure log matches | None observed |

Visual check artifacts were generated under:

```text
outputs/visual_cpp_stable_pose/baseline_30/nature_shelf_trinkets_bench.blend
outputs/visual_cpp_stable_pose/cpp_30/nature_shelf_trinkets_bench.blend
outputs/visual_cpp_stable_pose/cpp_canary_30/nature_shelf_trinkets_bench.blend
outputs/visual_cpp_stable_pose/render_checks/
```

These artifacts are local outputs and are not committed.

## Creature Failure Note

An unfiltered 1-room cpp+canary smoke failed while populating a
`NatureShelfTrinketsFactory` placeholder that selected `CarnivoreFactory`:

```text
NatureShelfTrinketsFactory -> CarnivoreFactory -> lofting.factorize_nurbs_handles
AttributeError: 'int' object has no attribute 'mean'
```

This is not attributed to the C++ stable pose backend because creature
factories in `NatureShelfTrinketsFactory` skip stable pose. Earlier unfiltered
NatureShelfTrinkets benchmark runs also showed matching baseline and cpp+canary
creature failures for `CarnivoreFactory` and `HerbivoreFactory`.

## Opt-in Creature Filter

Added this smoke/testing-only environment variable:

```text
INFINIGEN_DISABLE_NATURE_SHELF_CREATURE_TRINKETS=1
```

Default behavior remains unchanged:

| Env value | Behavior |
| --- | --- |
| unset / `0` / falsey | Keep existing `CarnivoreFactory` and `HerbivoreFactory` choices |
| `1` / `true` / `yes` / `on` | Locally exclude creature trinkets before `np.random.choice` |

The static `NatureShelfTrinketsFactory.factories` list is unchanged. When the
opt-in filter is enabled, the remaining probabilities are normalized at the
choice site.

Validation:

```text
python -m py_compile infinigen/assets/objects/elements/nature_shelf_trinkets/generate.py
python -m py_compile tests/test_nature_shelf_trinkets_factory.py
pytest tests/test_stable_pose_wrapper.py tests/test_stable_pose_kernels.py tests/test_nature_shelf_trinkets_factory.py -q
python setup.py build_ext --inplace -v
git diff --check
```

The pytest result was `31 passed, 1 warning`.

## 1-room Smoke

Both no-creature 1-room smokes used:

```text
INFINIGEN_DISABLE_NATURE_SHELF_CREATURE_TRINKETS=1
INFINIGEN_STABLE_POSE_BACKEND=cpp
INFINIGEN_PROFILE_STABLE_POSE=1
```

The cpp+canary run also used:

```text
INFINIGEN_VALIDATE_CPP_STABLE_POSE=1
```

| Run | Result | Output |
| --- | --- | --- |
| cpp+canary no-creature seed0 coarse | Success | `outputs/smoke_cpp_stable_pose_1room/cpp_canary_seed0_no_creature/coarse/scene.blend` |
| cpp no-canary no-creature seed0 coarse | Success | `outputs/smoke_cpp_stable_pose_1room/cpp_seed0_no_creature/coarse/scene.blend` |
| cpp no-canary USDC export | Success | `outputs/smoke_cpp_stable_pose_1room/usdc_cpp_seed0_no_creature/export_scene.blend/export_scene.usdc` |

The cpp+canary no-creature smoke finished `[MAIN TOTAL]` in `0:02:34.604891`.
The cpp no-canary no-creature smoke finished `[MAIN TOTAL]` in `0:02:28.275931`.

## Conclusion

The opt-in no-creature filter unblocked the C++ stable pose 1-room validation
without changing default NatureShelfTrinkets behavior. Visual checks passed,
cpp+canary no-creature 1-room passed, cpp no-canary no-creature 1-room passed,
and USDC export passed.

Recommended next steps:

1. Proceed to a 10-room no-creature smoke before enabling broader scene checks.
2. Track and fix the `CarnivoreFactory` / `HerbivoreFactory` lofting bug
   separately from stable pose work.
3. Continue typed C loops in the `.pyx` stable pose path after the smoke gate,
   because the benchmark still shows stable pose as a meaningful cost center.
