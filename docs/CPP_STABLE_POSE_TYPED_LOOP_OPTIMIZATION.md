# C++ Stable Pose Typed Loop Optimization

## Scope

This pass optimized one hot section in
`infinigen/core/constraints/cpp/stable_pose_kernels.pyx`: the static
probability inner loop used while scoring candidate stable faces.

No solver behavior, benchmark CSV schema, fast NatureShelf path, or full-scene
generation path was changed.

## Baseline

Previous v1 100-sample filtered NatureShelf benchmark:

| Run | Success | Failure | Total duration | stable_pose_duration |
| --- | ---: | ---: | ---: | ---: |
| cpp no-canary v1 | 100 | 0 | `138.484s` | `76.486s` |

Current reference rerun before this optimization:

| Run | Success | Failure | Total duration | stable_pose_duration | obj2trimesh_duration |
| --- | ---: | ---: | ---: | ---: | ---: |
| `cpp_100_current` | 100 | 0 | `140.230s` | `77.186s` | `32.166s` |

The benchmark used the filtered non-creature NatureShelf factory set:

```text
CoralFactory,BlenderRockFactory,BoulderFactory,PineconeFactory,MolluskFactory,AugerFactory,ClamFactory,ConchFactory,MusselFactory,ScallopFactory,VoluteFactory
```

`INFINIGEN_FAST_NATURE_TRINKET_STABLE_POSE` remained unset.

## Change

The inspected `.pyx` still had several Python-level sections, including
neighbor bookkeeping, dictionary aggregation, barycentric projection, and a
per-face static probability list comprehension.

This pass only changed the per-face static probability scoring:

- Added a Cython scalar helper using `sqrt`, `acos`, `tan`, `atan`, and
  `isfinite` from `libc.math`.
- Replaced the Python list comprehension over faces with a typed loop writing
  into a NumPy `float64` array through a memoryview.
- Kept the existing zero-norm behavior of returning `0.0`.
- Left downstream NumPy projection, adjacency traversal, sorting, and transform
  construction unchanged.

## Correctness

Verification completed:

| Check | Result |
| --- | --- |
| `python setup.py build_ext --inplace -v` | Passed |
| `pytest tests/test_stable_pose_wrapper.py tests/test_stable_pose_kernels.py tests/test_nature_shelf_trinkets_factory.py -q` | `32 passed, 3 warnings` |
| cpp+canary 100-sample benchmark after optimization | 100 success, 0 failures |
| cpp+canary log scan | No `fallback`, `canary failed`, `StablePoseValidationError`, or validation error matches |
| Numeric CSV scan | All parsed numeric fields finite for no-canary and canary CSVs |

A direct `_compute_static_prob` test now checks finite cases against
`trimesh.poses._compute_static_prob`. For a center of mass exactly on a vertex,
trimesh's private helper returns `nan`; the C++ helper keeps the existing C++
backend behavior and returns `0.0`.

## Performance

Optimized 100-sample no-canary run:

| Run | Success | Failure | Total duration | stable_pose_duration | obj2trimesh_duration |
| --- | ---: | ---: | ---: | ---: | ---: |
| `cpp_100_after_opt` | 100 | 0 | `121.052s` | `61.249s` | `29.997s` |

Comparison against the current reference:

| Metric | Before | After | Speedup | Reduction |
| --- | ---: | ---: | ---: | ---: |
| Total duration | `140.230s` | `121.052s` | `1.158x` | `13.7%` |
| stable_pose_duration | `77.186s` | `61.249s` | `1.260x` | `20.6%` |

The optimized cpp+canary run completed successfully but is intentionally slower
because it validates against trimesh on every call:

| Run | Success | Failure | Total duration | stable_pose_duration |
| --- | ---: | ---: | ---: | ---: |
| `cpp_canary_100_after_opt` | 100 | 0 | `214.817s` | `153.619s` |

## 10-room Smoke

Before this optimization, the C++ backend passed 10-room no-creature smoke with
canary enabled and without canary enabled, and the USDC export from the
no-canary output succeeded. See
`docs/CPP_STABLE_POSE_10ROOM_SMOKE_RESULTS.md`.

Because this optimization substantially changed the `.pyx` hot loop, a typed
10-room no-creature cpp+canary rerun remains the next validation step after this
commit if time allows.

## Conclusion

The static probability typed loop is accepted as a usable candidate: tests pass,
the 100-sample cpp+canary benchmark passes, and the no-canary performance
benchmark improves both total duration and stable-pose duration.

Further speed work should target the remaining Python-level sections in the
stable-pose core, especially projection, adjacency traversal, and probability
aggregation. The creature lofting issue remains separate from stable pose.
