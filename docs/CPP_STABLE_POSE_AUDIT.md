# C++ Stable Pose Audit Report

## 1. Executive Summary

This audit only reviews the current Infinigen source and the installed
`trimesh` implementation. It does not implement a C++ backend, does not modify
generation behavior, and does not run a full scene.

Main findings:

- There are exactly 2 production runtime call sites of
  `trimesh.poses.compute_stable_poses(mesh)` in the audited source tree. Both
  are in `infinigen/assets/objects/elements/nature_shelf_trinkets/generate.py`
  at lines 393 and 486.
- The runtime use is currently concentrated in `NatureShelfTrinketsFactory`.
  Search results also include documentation and analysis scripts that mention
  stable pose timing fields, but they do not call `compute_stable_poses` at
  runtime.
- The installed stable pose implementation is from `trimesh==3.22.5` at
  `/home/ubuntu22/miniconda3/envs/infinigen/lib/python3.11/site-packages/trimesh/poses.py`.
- `trimesh.poses.compute_stable_poses` uses `mesh.convex_hull`, optionally
  uses `mesh.center_mass`, samples COM candidates with global `np.random`, and
  builds/traverses a `networkx` graph.
- The best first implementation route is option B: keep convex hull creation
  and high-level mesh preparation in Python/trimesh, then move the stable pose
  numeric core and graph-like propagation into a Cython/C++ extension.
- The first C++ version should not rewrite convex hull and should not add
  Eigen, pybind11, CGAL, or Qhull as new project dependencies. Trimesh already
  delegates convex hull to SciPy/Qhull and adds important repair/cache behavior.

Recommended next step: implement a global wrapper first, defaulting to the
existing trimesh backend, then add an opt-in Cython/C++ backend with canary
validation and automatic fallback.

## 2. Current Environment State

Recorded by `audit_logs/00_state.log`:

- Time: `2026-06-23T22:05:16+08:00`
- Source directory: `/home/ubuntu22/infinigen/repo_snapshot`
- Git state: not a Git repo
- Python executable:
  `/home/ubuntu22/miniconda3/envs/infinigen/bin/python`
- Python version: `Python 3.11.15`

Installed `trimesh` state from `audit_logs/03_trimesh_source_info.log`:

- `trimesh` version: `3.22.5`
- `trimesh` package file:
  `/home/ubuntu22/miniconda3/envs/infinigen/lib/python3.11/site-packages/trimesh/__init__.py`
- `trimesh.poses` file:
  `/home/ubuntu22/miniconda3/envs/infinigen/lib/python3.11/site-packages/trimesh/poses.py`
- `compute_stable_poses` start line: `20`

Packaging state:

- `pyproject.toml` declares Python `==3.11.*`.
- `pyproject.toml` depends on `trimesh<3.23.0`, `networkx`, `numpy<2`, and
  `scipy`.
- Build requirements are `setuptools`, `numpy`, and `Cython`.

## 3. All Stable Pose Call Sites in Infinigen

The global audit command was saved in `audit_logs/01_stable_pose_refs.log`.
It searched `infinigen`, `scripts`, `tests`, and `docs`.

Production runtime call sites:

| Count | File | Line | Function / path | Role |
|---:|---|---:|---|---|
| 1 | `infinigen/assets/objects/elements/nature_shelf_trinkets/generate.py` | 393 | `NatureShelfTrinketsFactory.create_asset` | Non-profiled asset creation path. Converts the Blender object to a trimesh if needed, computes stable poses, picks `np.argmax(probs)`, and applies the rotation. |
| 2 | `infinigen/assets/objects/elements/nature_shelf_trinkets/generate.py` | 486 | `NatureShelfTrinketsFactory._create_asset_timed` | Profiled path. Records mesh complexity and stable pose timing, computes poses, picks best probability, and applies the rotation. |

Related behavior in the same file:

- `generate.py:199-211` defines `_fast_stable_pose_allowed`, currently limited
  to shell/mollusk factories.
- `generate.py:386-389` and `generate.py:457-469` skip
  `compute_stable_poses` when
  `INFINIGEN_FAST_NATURE_TRINKET_STABLE_POSE` is enabled and the base factory
  is eligible.
- `generate.py:227-256` records mesh complexity and
  `stable_pose_cache_candidate_key` in the profiled path.

Conclusion:

- The direct production calls are concentrated in `NatureShelfTrinketsFactory`.
- The best migration point is a global wrapper called from both lines 393 and
  486. This keeps behavior identical while allowing backend selection,
  profiling, validation, and fallback in one place.
- The profiled path at line 486 needs extra care because it already populates
  benchmark CSV fields such as `stable_pose_duration`,
  `stable_pose_count`, and `stable_pose_best_prob`.
- The existing fast path controlled by
  `INFINIGEN_FAST_NATURE_TRINKET_STABLE_POSE` must remain upstream of any new
  wrapper. If that path skips stable pose computation, the wrapper should not
  be called.

## 4. Current Trimesh compute_stable_poses Implementation

Audited installed source:

- `/home/ubuntu22/miniconda3/envs/infinigen/lib/python3.11/site-packages/trimesh/poses.py`
- Source saved to `audit_logs/05_trimesh_poses_source_head.log`

Relevant functions:

| Function | Lines | Role |
|---|---:|---|
| `compute_stable_poses` | 20-162 | Public API. Creates convex hull, samples COM, builds toppling graph per sample, aggregates probabilities by rounded face normal, builds transforms, sorts results. |
| `_orient3dfast` | 165-194 | Scalar 3D orientation determinant used when choosing topple successor. |
| `_compute_static_prob` | 197-227 | Computes the spherical-area probability for one hull triangle and COM. |
| `_create_topple_graph` | 230-303 | Builds `networkx` adjacency/topple graphs, computes per-face static probability, identifies unstable faces, and assigns each unstable face one successor. |

Inputs to `compute_stable_poses`:

- `mesh`: a `trimesh.Trimesh`.
- `center_mass`: optional `(3,)` float. If `None`, `mesh.center_mass` is used.
- `sigma`: covariance scalar for COM sampling.
- `n_samples`: number of accepted COM samples.
- `threshold`: filters output poses by probability.

Returns:

- `transforms`: `(n, 4, 4)` float homogeneous transforms, sorted by decreasing
  probability.
- `probs`: `(n,)` float probabilities sorted to match `transforms`.

Internal flow:

1. `poses.py:71-72`: gets `cvh = mesh.convex_hull`.
2. `poses.py:74-75`: gets `mesh.center_mass` if no `center_mass` was passed.
3. `poses.py:77-89`: samples COM candidates with
   `np.random.multivariate_normal` and rejects candidates outside the convex
   hull using face normals.
4. `poses.py:93-98`: for each accepted COM sample, calls
   `_create_topple_graph(cvh, sample_com)`.
5. `poses.py:99-112`: propagates probability through a `networkx.DiGraph` from
   no-incoming-edge nodes to sink nodes.
6. `poses.py:114-126`: aggregates nonzero sink probabilities by face normal
   rounded to 3 decimals.
7. `poses.py:131-155`: builds one transform per surviving normal and computes
   z translation by copying the convex hull and applying the transform.
8. `poses.py:157-162`: sorts by descending probability.

Important dependency and cache details:

- Convex hull: yes. `mesh.convex_hull` is used at `poses.py:72`. The property
  delegates to `trimesh.convex.convex_hull`.
- NetworkX: yes. `networkx` is imported at `poses.py:11-17`; `_create_topple_graph`
  creates `nx.Graph()` and `nx.DiGraph()` at `poses.py:257-258`.
- NumPy random: yes. `np.random.multivariate_normal` is called at
  `poses.py:81-83`. This consumes global NumPy RNG state, even for the common
  default call shape.
- Trimesh cached properties: yes. `mesh.convex_hull`, `mesh.center_mass`,
  convex hull `triangles`, `triangles_center`, `face_normals`,
  `face_adjacency`, `face_adjacency_edges`, `vertices`, and `bounds` all pass
  through trimesh property/cache machinery.
- Convex hull implementation: `trimesh/convex.py:20-24` imports
  `scipy.spatial.ConvexHull`; `convex.py:63-70` calls Qhull and retries with
  `QJ`; `convex.py:89-147` repairs winding/normals, seeds cache entries, and
  retries without `QbB` if needed.

Likely slow pieces:

- Convex hull construction for high-complexity meshes. This is already backed
  by SciPy/Qhull but can still dominate for very large meshes.
- `_compute_static_prob` loop over every convex hull face
  (`poses.py:271-274`), with per-face Python calls and trigonometry.
- `networkx` graph construction and traversal (`poses.py:257-269`,
  `poses.py:99-112`).
- Per-unstable-face Python loops and scalar orientation tests
  (`poses.py:283-301`).
- Transform z translation by copying and transforming the convex hull once per
  pose (`poses.py:149-151`).

Not suitable for first C++ pass:

- Full convex hull implementation, because trimesh already combines Qhull,
  degenerate-case retry, winding repair, normal repair, and cache seeding.
- Mesh mass properties / `center_mass`, unless a caller explicitly supplies
  `center_mass`.
- High-level Blender object conversion or `obj.obj2trimesh`.

## 5. Algorithm Step-by-Step Breakdown

| Phase | Current implementation location | Input | Output | Hotspot | C++ rewrite? | Difficulty | Equivalence risk | Priority | Notes |
|---|---|---|---|---|---|---|---|---|---|
| A. Get convex hull | `poses.py:71-72`; `trimesh/convex.py:32-149` | `mesh` | `cvh` mesh | Sometimes | Not v1 | High | High | Low for v1 | Uses SciPy/Qhull, repair, cache, face winding. |
| B. Get center_mass | `poses.py:74-75`; `trimesh/base.py:579` | `mesh` | `(3,)` COM | Usually no | Not v1 | Medium | Medium | Low | Depends on trimesh mass properties and watertight assumptions. |
| C. Sample center of mass | `poses.py:77-89` | `center_mass`, `sigma`, `n_samples`, `cvh` | accepted COM samples | Low for current `n_samples=1` | Maybe later | Low | High for RNG state | Low | Keep Python RNG in v1. |
| D. Check COM inside hull | `poses.py:84-89` | COM candidates, `cvh.triangles_center`, `cvh.face_normals` | accepted/rejected COMs | Low to medium | Yes, if samples passed in | Low | Medium | Medium | Simple dot/all test; RNG semantics are the risk. |
| E. Create toppling graph | `_create_topple_graph`, `poses.py:257-269` | face adjacency and shared edge arrays | adjacency/topple graph | Yes | Yes | Medium | Medium | High | `networkx` can be replaced by arrays. |
| F. Static probability per face | `_compute_static_prob`, `poses.py:197-227`, called at `271-274` | triangle, COM | probability per face | Yes | Yes | Medium | Medium | High | Numeric equivalence around degenerate spherical triangles matters. |
| G. COM projection to face plane | `poses.py:276-279` | COM, triangles, normals | projected COM per face | Medium | Yes | Low | Low | High | Already vectorized NumPy; cheap but useful inside core. |
| H. Barycentric in triangle | `points_to_barycentric`, called at `poses.py:280-281` | triangles, projected COMs | unstable face mask | Medium | Yes | Low | High | High | Must match strict `barys < 0` boundary policy. |
| I. Find topple successor | `poses.py:283-301`, `_orient3dfast` | unstable faces, adjacency, shared edge verts, normals | one successor per unstable face | Yes | Yes | Medium | High | High | Tie/order sensitivity affects final top-1. |
| J. Propagate graph probabilities | `poses.py:99-112` | successor graph, static probs | sink probabilities | Yes | Yes | Medium | Medium | High | Replace `networkx` with arrays and bounded walks. |
| K. Aggregate by face normal | `poses.py:114-126` | sink probs, face normals | normal/prob map | Medium | Yes | Medium | High | High | Must match rounding to 3 decimals and insertion/order behavior. |
| L. Generate 4x4 transform | `poses.py:131-147` | stable normal | rotation transform | Low | Yes | Low | Medium | Medium | Deterministic math; watch degenerate horizontal axis. |
| M. Z translation to ground | `poses.py:148-152` | transform, hull bounds | z offset | Medium | Yes | Low | Medium | Medium | Can compute transformed vertex min z without copying mesh. |
| N. Sort output | `poses.py:157-162` | transforms, probs | sorted arrays | Low | Yes | Low | Medium | Medium | Match `np.argsort(-probs)` tie behavior if possible. |

## 6. Hotspot and C++ Rewrite Candidate Analysis

The strongest C++ candidates are the Python loops and object-heavy graph work:

- `_compute_static_prob` per face.
- `networkx` graph construction and propagation.
- Per-unstable-face adjacency scan and `_orient3dfast`.
- Normal aggregation after propagation.
- Transform generation and z translation without `cvh.copy()`.

`networkx` can be replaced by arrays. In this algorithm, an unstable face gets
at most one outgoing successor edge (`poses.py:301`). A compact backend can use:

- `face_adjacency` as `[E, 2]` integer pairs.
- `face_adjacency_edges` as `[E, 2]` vertex index pairs.
- A face-to-adjacency index structure or CSR-like offsets.
- `successor[F]`, initialized to `-1`.
- `prob[F]`, initialized from static probabilities.
- A bounded propagation loop equivalent to the current `n_iters <= len(mesh.faces)`.

Convex hull should not be rewritten in the first version. Even without hull
rewrite, a C++ core is still worth doing because the current code pays Python
and `networkx` overhead on every hull face and every unstable face. Existing
profiles in repo docs already identify `stable_pose_duration` as a significant
cost for NatureShelfTrinkets shell meshes, and the runtime calls are narrow
enough to validate safely.

Areas most likely to change the top-1 pose:

- Convex hull face ordering, winding, and normals.
- Exact barycentric boundary policy: current implementation marks unstable
  faces with `np.any(barys < 0, axis=1)`.
- `_orient3dfast` comparison uses `>= 0` for both edge planes.
- Normal aggregation rounds normals to 3 decimals before accumulating
  probabilities.
- Probability sort ties use `np.argsort(-probs)`.
- Random COM sampling and rejection order.

## 7. Full Rewrite Feasibility

| Route | Scope | Development difficulty | Speed gain | Equivalence risk | Test cost | Recommended now |
|---|---|---|---|---|---|---|
| A. Conservative | Add global wrapper only; default remains trimesh | Low | Low | Low | Low | Useful first step, but not enough for the performance goal |
| B. Recommended | Python/trimesh prepares convex hull and arrays; Cython/C++ rewrites stable pose core | Medium | Medium to high | Medium | Medium | Yes |
| C. Aggressive | C++ rewrites convex hull, adjacency, stable pose core, transforms, sorting | Very high | Potentially high | Very high | Very high | No |

Specific answers:

- First version should not rewrite convex hull.
- First version should not introduce Qhull, CGAL, Eigen, or pybind11 as new
  project dependencies.
- A full convex hull rewrite without a third-party computational geometry
  library is not realistic for this phase. Matching Qhull behavior, degenerate
  retries, winding repair, and trimesh cache semantics is high-risk work.
- Moving only `networkx` and Python loops to Cython/C++ is worth doing if the
  wrapper preserves fallback and canary validation. It attacks the current
  object-heavy part while keeping the hardest geometry primitive unchanged.
- Final recommendation: route B. It gives meaningful acceleration potential
  with bounded behavior risk and a feasible test surface.

## 8. Recommended Architecture: Global Wrapper + Opt-in C++ Backend

Future wrapper file:

```text
infinigen/core/util/stable_pose.py
```

Proposed API:

```python
def compute_stable_poses(
    mesh,
    center_mass=None,
    sigma=0.0,
    n_samples=1,
    threshold=0.0,
    *,
    context=None,
):
    ...
```

Environment variables:

```bash
INFINIGEN_STABLE_POSE_BACKEND=trimesh|cpp|auto
INFINIGEN_VALIDATE_CPP_STABLE_POSE=1
INFINIGEN_PROFILE_STABLE_POSE=1
INFINIGEN_DISABLE_CPP_STABLE_POSE=1
```

Default behavior:

- Default backend should be `trimesh`.
- `cpp` should be opt-in through `INFINIGEN_STABLE_POSE_BACKEND=cpp`.
- `auto` can use C++ when the extension imports and inputs are supported, but
  should still fallback automatically.
- `INFINIGEN_DISABLE_CPP_STABLE_POSE=1` should force the original trimesh path.

Fallback rules:

- Extension import failure: fallback to trimesh and record
  `fallback_reason="extension_import_failed"`.
- Unsupported parameters or mesh shape: fallback with
  `fallback_reason="unsupported_input"`.
- C++ output contains NaN/inf, invalid transform shape, invalid probability
  shape, bad determinant, negative probabilities, or probability sum out of
  tolerance: fallback with `fallback_reason="invalid_cpp_output"`.
- Canary validation failure: fallback with
  `fallback_reason="canary_mismatch"`.

Logging and benchmark integration:

- Store fallback diagnostics in an optional `context` dict instead of printing
  per asset by default.
- Rate-limit warning logs by reason, for example once per process per reason.
- When the caller is the profiled NatureShelfTrinkets path, extend CSV fields
  later with backend and fallback diagnostics, for example
  `stable_pose_backend`, `stable_pose_fallback_reason`,
  `stable_pose_canary_pass`, and `stable_pose_cpp_duration`.
- Do not break `INFINIGEN_FAST_NATURE_TRINKET_STABLE_POSE`. That env var is an
  upstream skip mode in `generate.py:386-389` and `generate.py:457-469`; if it
  is active, stable pose computation is intentionally bypassed.

Guardrail:

- Add a lightweight test or lint check that fails on new direct production
  calls to `trimesh.poses.compute_stable_poses` outside the wrapper and
  explicit test fixtures.

## 9. C++ / Cython Backend Design

Recommended future files:

```text
infinigen/core/constraints/cpp/stable_pose_kernels.py
infinigen/core/constraints/cpp/stable_pose_kernels.pyx
tests/test_stable_pose_kernels.py
```

Existing pattern to reuse:

- `setup.py:63-71` registers
  `infinigen.core.constraints.cpp.geometry_kernels_cpp` from
  `infinigen/core/constraints/cpp/geometry_kernels.pyx`.
- `geometry_kernels.py:21-29` imports the compiled extension with broad
  fallback and exposes `C_EXTENSION_AVAILABLE`.
- `geometry_kernels.py:69-81` centralizes C++ call/fallback and explicit
  require behavior.
- `geometry_kernels.pyx:1` disables Cython bounds/wraparound checks and uses
  `language_level=3`.
- `geometry_kernels.pyx:47+` uses typed memoryviews and contiguous NumPy arrays.

Future `setup.py` change:

```python
cython_extensions.append(
    Extension(
        name="infinigen.core.constraints.cpp.stable_pose_kernels_cpp",
        sources=["infinigen/core/constraints/cpp/stable_pose_kernels.pyx"],
        include_dirs=[numpy.get_include()],
        language="c++",
    )
)
```

Suggested Python wrapper responsibilities:

- Build `cvh = mesh.convex_hull` in Python.
- Resolve `center_mass`.
- Generate accepted COM samples in Python.
- Extract contiguous arrays from `cvh`.
- Call the Cython extension.
- Validate output and fallback to trimesh on any exception.

Suggested Cython callable:

```python
def compute_stable_poses_core(
    triangles,
    face_normals,
    triangles_center,
    vertices,
    face_adjacency,
    face_adjacency_edges,
    sample_coms,
    threshold,
):
    ...
```

Inputs:

- `triangles`: `float64[:, :, :]`, shape `[F, 3, 3]`.
- `face_normals`: `float64[:, :]`, shape `[F, 3]`.
- `triangles_center`: `float64[:, :]`, shape `[F, 3]`.
- `vertices`: `float64[:, :]`, shape `[V, 3]`.
- `face_adjacency`: `int64[:, :]`, shape `[E, 2]`.
- `face_adjacency_edges`: `int64[:, :]`, shape `[E, 2]`.
- `sample_coms`: `float64[:, :]`, shape `[S, 3]`.
- `threshold`: `double`.

Outputs:

- `transforms`: `float64` array, shape `[P, 4, 4]`.
- `probs`: `float64` array, shape `[P]`.
- Optional diagnostics for validation/debug builds:
  `successor`, `stable_face_mask`, `normal_keys`, and an integer status code.

Implementation guidance:

- Use `float64` first. Trimesh casts many geometry paths to float64, and the
  stable pose code currently uses NumPy default float behavior.
- Use typed memoryviews and `np.ascontiguousarray` in the Python wrapper.
- Release the GIL for pure numeric loops after all Python/NumPy allocations are
  done. The first version can keep allocation and dictionary-like aggregation
  in Python if needed, then move it once equivalence is proven.
- Do not use OpenMP in v1. Deterministic ordering and reproducibility are more
  important than parallel speedup initially.
- Do not add new dependencies in v1.
- Handle exceptional meshes by returning a clear status or raising a Python
  exception that the wrapper converts into fallback.

## 10. Fallback Strategy

Fallback must be conservative and broad. The wrapper should return the original
trimesh result whenever the optimized path is unavailable or suspicious.

Recommended fallback checks:

- Extension import failed.
- Backend disabled by env var.
- Unsupported dtype, shape, empty arrays, no faces, no vertices, or mismatched
  adjacency arrays.
- COM sampling fails to produce accepted samples within a bounded retry budget.
- C++ raises any exception.
- Output transform/probability shapes are invalid.
- Any output contains NaN or inf.
- Any rotation determinant is far from 1.
- Probability array is empty when trimesh would return non-empty.
- Canary validation metrics exceed tolerance.

Fallback reason should be captured as structured data:

```python
context["stable_pose_backend"] = "trimesh"
context["stable_pose_requested_backend"] = requested_backend
context["stable_pose_fallback_reason"] = reason
```

Avoid log spam:

- Do not print per asset by default.
- Emit at most one warning per reason per process.
- In profiling mode, write per-row structured fields rather than free text.

## 11. Canary Validation Strategy

Goal: run the C++ backend and the original trimesh backend on the same mesh.
If they diverge too far, return the trimesh result and record diagnostics.

Recommended metrics:

| Metric | Purpose |
|---|---|
| `pose_count` | Compare number of returned transforms. |
| `prob_count` | Compare number of probabilities. |
| `prob_sum` | Detect probability mass loss/gain. |
| `top1_prob_diff` | Compare most likely pose probability. |
| `top1_rotation_diff` | Compare top-1 rotation matrix. |
| `top1_translation_diff` | Compare top-1 z placement. |
| `top1_normal_cosine` | Compare top-1 stable face normal direction. |
| `topk_normal_match` | Check whether top-k rounded normals match independent of order. |
| `has_nan` | Reject invalid numeric output. |
| `has_inf` | Reject invalid numeric output. |
| `rotation_det` | Check rotation matrices are proper. |
| `fallback_reason` | Record why the wrapper returned trimesh. |

Initial tolerance policy:

- Reject any NaN or inf.
- Reject rotation determinant outside a tight tolerance around 1.
- Require top-1 normal cosine near 1 for simple meshes.
- For complex shell meshes, compare top-k rounded normals and top-1 transform
  within a practical tolerance before enabling C++ by default.

## 12. Randomness and Equivalence Risks

Current randomness:

- `trimesh.poses.compute_stable_poses` consumes global NumPy RNG via
  `np.random.multivariate_normal` at `poses.py:81-83`.
- COM candidates are accepted only when all convex-hull face-normal dot
  products are negative (`poses.py:84-89`).

Canary double-run problem:

- Running C++ and then original trimesh naively can consume RNG twice and
  change subsequent procedural generation state.
- This matters even if stable pose output looks similar, because Infinigen
  generation depends heavily on seeded NumPy randomness.

Recommended v1 rule:

- C++ backend should not generate random numbers.
- Python wrapper should generate accepted `sample_coms` once and pass them to
  C++.
- For canary mode that calls original trimesh, snapshot and restore NumPy RNG
  state around the reference call so user-visible RNG state is consumed only
  once.
- Longer term, expose a reference path that accepts precomputed `sample_coms`,
  allowing exact C++ vs Python-core comparison without calling the public
  trimesh function twice.

Other equivalence risks:

- Trimesh convex hull face order and winding.
- `points_to_barycentric` numerical behavior and strict `< 0` unstable test.
- `_orient3dfast` scalar determinant and `>= 0` comparisons.
- Normal rounding to 3 decimals before aggregation.
- Dictionary insertion order for equal probabilities.
- `np.argsort(-probs)` tie behavior.
- Transform basis construction when `x` would be zero.
- Z translation based on transformed convex hull bounds.

## 13. Benchmark Plan

Do not run full scene for initial validation. Start with the existing
NatureShelfTrinkets benchmark.

Baseline:

```bash
INFINIGEN_PROFILE_NATURE_SHELF_TRINKETS=1 \
python scripts/bench_nature_shelf_trinkets_factory.py \
  --samples 100 \
  --seed 0 \
  --output_folder outputs/bench_cpp_stable_pose_ab/baseline
```

Candidate C++ backend:

```bash
INFINIGEN_PROFILE_NATURE_SHELF_TRINKETS=1 \
INFINIGEN_STABLE_POSE_BACKEND=cpp \
INFINIGEN_VALIDATE_CPP_STABLE_POSE=1 \
python scripts/bench_nature_shelf_trinkets_factory.py \
  --samples 100 \
  --seed 0 \
  --output_folder outputs/bench_cpp_stable_pose_ab/candidate_cpp
```

Broader test plan:

- Synthetic mesh unit tests: box, tetrahedron, flat shell, sphere-like mesh.
- NatureShelfTrinkets all factories.
- Other future stable pose call sites, if any are added.
- 1-room smoke after wrapper and fallback prove stable.
- 10-room Isaac visual test only after unit, canary, and small benchmarks pass.

Suggested acceptance criteria:

- Default mode result is unchanged.
- C++ backend compiles successfully.
- Fallback works on import failure, invalid output, and canary mismatch.
- Canary pass rate is high on synthetic and NatureShelfTrinkets meshes.
- Failure count is 0 in benchmark runs.
- No NaN or inf.
- Top-1 pose is basically consistent with trimesh.
- `stable_pose_duration` drops materially in profiled rows.
- Visual results do not float, invert, or obviously intersect surfaces.

## 14. Implementation Plan by Commits

No commits were made in this audit. A future implementation should be split into
small reviewable commits:

1. Add `infinigen/core/util/stable_pose.py` wrapper, defaulting to trimesh, with
   env parsing and structured context diagnostics.
2. Migrate the two NatureShelfTrinkets call sites to the wrapper with no
   behavior change.
3. Add tests or lint guard preventing new direct production calls to
   `trimesh.poses.compute_stable_poses`.
4. Add `stable_pose_kernels.py` and `.pyx` skeleton, extension registration in
   `setup.py`, and import fallback matching `geometry_kernels`.
5. Implement static probability, projection, barycentric unstable test, topple
   successor search, and probability propagation in Cython/C++.
6. Add normal aggregation, transform generation, z translation, sorting, and
   diagnostics.
7. Add canary validation and fallback metrics.
8. Run synthetic tests, NatureShelfTrinkets benchmark, then broader smoke tests.

## 15. Open Questions / Risks

- How much of current wall time is convex hull vs `networkx`/Python loops on
  the largest shell meshes? If convex hull dominates, route B still helps but
  may not be sufficient alone.
- How strict should canary tolerances be for complex shell assets with many
  near-equivalent poses?
- Should normal aggregation remain exactly rounded-to-3-decimals, or should
  the wrapper eventually expose a more robust matching strategy? For v1, keep
  the existing behavior.
- How should benchmark CSV schema evolve without breaking existing analysis
  scripts?
- Should C++ expose detailed per-face diagnostics, or only final transforms and
  probabilities? Diagnostics are useful early but should stay optional.
- The current source directory is not a Git repo, so commit hash and branch
  cannot be recorded for this audit.

## 16. Final Recommendation

Proceed with route B:

- Add a global wrapper first.
- Keep default behavior on the original trimesh backend.
- Keep convex hull and mesh preparation in Python/trimesh for v1.
- Move the stable pose core, `networkx` replacement, per-face probability,
  unstable-face successor search, probability propagation, normal aggregation,
  transform generation, z translation, and sorting into Cython/C++.
- Do not introduce new C++ dependencies in the first version.
- Protect the rollout with opt-in env vars, canary validation, structured
  fallback reasons, and a lint/test guard against future direct trimesh calls.

This route gives the best balance of speed potential, implementation effort,
and equivalence safety for the current codebase.
