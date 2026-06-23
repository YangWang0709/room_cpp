# C++ Stable Pose Benchmark Results

## Scope

Filtered non-creature NatureShelfTrinkets stable-pose factories were benchmarked.

The filter was:

```text
CoralFactory,BlenderRockFactory,BoulderFactory,PineconeFactory,MolluskFactory,AugerFactory,ClamFactory,ConchFactory,MusselFactory,ScallopFactory,VoluteFactory
```

`CarnivoreFactory` and `HerbivoreFactory` were excluded because an earlier
unfiltered 20-sample run failed in both baseline and cpp+canary with the same
`AttributeError` pattern, and those creature paths skip stable pose.

This benchmark did not run a full scene and did not enable the
`INFINIGEN_FAST_NATURE_TRINKET_STABLE_POSE` fast path.

## Environment

| Item | Value |
| --- | --- |
| Benchmark date | 2026-06-23 |
| Repository | `/home/ubuntu22/infinigen/repo_snapshot` |
| Starting commit | `444387d8d2782958ab33a9058c87f57a13fe3ea8` |
| Branch | `main` |
| Conda env | `infinigen` |
| Python | `3.11.15` |
| trimesh | `3.22.5` |

Preflight checks passed:

```text
python setup.py build_ext --inplace -v
pytest tests/test_stable_pose_wrapper.py tests/test_stable_pose_kernels.py -q
```

The pytest result was `23 passed in 0.92s`.

Stable-pose-related environment variables were explicitly unset before the
benchmark runs, then set per run:

```text
unset INFINIGEN_FAST_NATURE_TRINKET_STABLE_POSE
unset INFINIGEN_STABLE_POSE_BACKEND
unset INFINIGEN_VALIDATE_CPP_STABLE_POSE
unset INFINIGEN_DISABLE_CPP_STABLE_POSE
```

## Commands

The filtered smoke and benchmark commands used this shared filter:

```bash
NON_CREATURE_FILTER="CoralFactory,BlenderRockFactory,BoulderFactory,PineconeFactory,MolluskFactory,AugerFactory,ClamFactory,ConchFactory,MusselFactory,ScallopFactory,VoluteFactory"
```

Baseline runs used:

```bash
INFINIGEN_PROFILE_NATURE_SHELF_TRINKETS=1 \
INFINIGEN_STABLE_POSE_BACKEND=trimesh \
python scripts/bench_nature_shelf_trinkets_factory.py \
  --samples SAMPLE_COUNT \
  --seed 0 \
  --base-factory-filter "$NON_CREATURE_FILTER" \
  --output_folder outputs/bench_cpp_stable_pose_nature_filtered/baseline_SAMPLE_COUNT
```

C++ no-canary timing used:

```bash
INFINIGEN_PROFILE_NATURE_SHELF_TRINKETS=1 \
INFINIGEN_PROFILE_STABLE_POSE=1 \
INFINIGEN_STABLE_POSE_BACKEND=cpp \
python scripts/bench_nature_shelf_trinkets_factory.py \
  --samples 100 \
  --seed 0 \
  --base-factory-filter "$NON_CREATURE_FILTER" \
  --output_folder outputs/bench_cpp_stable_pose_nature_filtered/cpp_100
```

C++ canary correctness runs used:

```bash
INFINIGEN_PROFILE_NATURE_SHELF_TRINKETS=1 \
INFINIGEN_PROFILE_STABLE_POSE=1 \
INFINIGEN_STABLE_POSE_BACKEND=cpp \
INFINIGEN_VALIDATE_CPP_STABLE_POSE=1 \
python scripts/bench_nature_shelf_trinkets_factory.py \
  --samples SAMPLE_COUNT \
  --seed 0 \
  --base-factory-filter "$NON_CREATURE_FILTER" \
  --output_folder outputs/bench_cpp_stable_pose_nature_filtered/cpp_canary_SAMPLE_COUNT
```

## 20-sample filtered smoke

| Run | Success | Failure | Total duration | stable_pose_duration | obj2trimesh_duration | Fast path used | Fallback/canary failed |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| baseline trimesh | 20 | 0 | `38.854s` | `20.606s` | `10.068s` | 0 | No matches |
| cpp+canary | 20 | 0 | `47.658s` | `28.618s` | `10.598s` | 0 | No matches |

The cpp+canary smoke is expected to be slower than baseline because it runs both
the C++ backend and trimesh validation.

Slowest baseline factories by stable-pose time:

| Factory | Rows | stable_pose_duration | Total duration |
| --- | ---: | ---: | ---: |
| `ClamFactory` | 3 | `6.733s` | `8.197s` |
| `MusselFactory` | 3 | `5.207s` | `6.687s` |
| `CoralFactory` | 3 | `3.878s` | `15.048s` |
| `ConchFactory` | 4 | `2.078s` | `3.311s` |
| `AugerFactory` | 2 | `1.033s` | `1.615s` |

Slowest cpp+canary factories by stable-pose time:

| Factory | Rows | stable_pose_duration | Total duration |
| --- | ---: | ---: | ---: |
| `ClamFactory` | 3 | `9.881s` | `11.354s` |
| `MusselFactory` | 3 | `7.751s` | `9.215s` |
| `CoralFactory` | 3 | `4.346s` | `16.375s` |
| `ConchFactory` | 4 | `2.987s` | `4.229s` |
| `AugerFactory` | 2 | `1.417s` | `2.006s` |

## 100-sample filtered benchmark

| Run | Success | Failure | Total duration | stable_pose_duration | obj2trimesh_duration | Fast path used | Fallback/canary failed |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| baseline trimesh | 100 | 0 | `182.382s` | `119.139s` | `32.471s` | 0 | No matches |
| cpp no-canary | 100 | 0 | `138.484s` | `76.486s` | `31.334s` | 0 | No matches |
| cpp+canary | 100 | 0 | `233.619s` | `171.020s` | `32.244s` | 0 | No matches |

For the 100-sample timing run, cpp no-canary was faster than baseline:

| Metric | Baseline | C++ no-canary | Ratio | Improvement |
| --- | ---: | ---: | ---: | ---: |
| Total duration | `182.382s` | `138.484s` | `0.759` | `24.07%` faster |
| stable_pose_duration | `119.139s` | `76.486s` | `0.642` | `35.80%` faster |

The cpp+canary run was slower than baseline by design because it validates C++
results against trimesh on every stable pose call.

## Per base factory summary

Slowest 100-sample baseline factories by stable-pose time:

| Factory | Rows | stable_pose_duration | Total duration |
| --- | ---: | ---: | ---: |
| `ClamFactory` | 14 | `50.199s` | `56.985s` |
| `MusselFactory` | 14 | `24.544s` | `31.347s` |
| `ScallopFactory` | 6 | `10.731s` | `13.683s` |
| `ConchFactory` | 14 | `7.311s` | `11.554s` |
| `CoralFactory` | 5 | `7.068s` | `26.211s` |
| `MolluskFactory` | 18 | `5.982s` | `9.005s` |
| `AugerFactory` | 9 | `5.364s` | `8.323s` |

Slowest 100-sample cpp no-canary factories by stable-pose time:

| Factory | Rows | stable_pose_duration | Total duration |
| --- | ---: | ---: | ---: |
| `ClamFactory` | 14 | `29.707s` | `36.561s` |
| `MusselFactory` | 14 | `15.196s` | `22.006s` |
| `ScallopFactory` | 6 | `6.725s` | `9.698s` |
| `CoralFactory` | 5 | `6.376s` | `23.961s` |
| `ConchFactory` | 14 | `4.810s` | `9.192s` |
| `MolluskFactory` | 18 | `3.809s` | `6.964s` |
| `AugerFactory` | 9 | `3.666s` | `6.662s` |

Factories with failures or fallback in the filtered runs: none.

## Creature failure note

The earlier unfiltered 20-sample run had matching baseline and cpp+canary
failures:

| Factory | Failure count | Error type |
| --- | ---: | --- |
| `CarnivoreFactory` | 5 | `AttributeError` |
| `HerbivoreFactory` | 1 | `AttributeError` |

Because both baseline and cpp+canary failed identically, and because creature
factories skip stable pose in this path, these failures are not attributed to
the C++ stable pose backend.

## Conclusion

The filtered non-creature NatureShelfTrinkets benchmark passed at 20 and 100
samples with zero failures, zero fast stable-pose uses, and no fallback or canary
failure log matches.

The C++ no-canary backend improved 100-sample total duration by `24.07%` and
stable-pose duration by `35.80%` versus the trimesh baseline. The cpp+canary
run also completed successfully, so the next reasonable step is a visual check,
followed by a small 1-room smoke if the visual output looks correct.

It is still worth continuing the Cython implementation toward typed C loops.
Even after the current C++ backend improvement, stable pose remains `76.486s` of
the 100-sample filtered run, and the current path still leaves Python/Numpy/list
and dict overhead in the `.pyx` layer.
