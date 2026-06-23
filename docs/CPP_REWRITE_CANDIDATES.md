# C++ Rewrite Candidates

## Scope

This plan is based on the current indoor coarse timing sample and code reading.
The latest timing run was a 1800s timeout sample with 3061 proposal-attempt
rows, not a complete profile. It showed:

- `apply_duration`: about 1160.159s.
- `evaluate_duration`: about 172.236s.
- `revert_duration`: about 187.095s.
- Row-level `garbage_collect_duration`: about 287.308s, with step-level
  duplication caveat.
- The largest bottleneck is failed or unaccepted `Addition.apply`, especially
  heavy factories.

C++ should only be used for pure computation kernels. It must not change the
solver control flow, proposal order, random number call order, accept/reject
logic, or Blender `bpy` side effects.

Later fine-grained samples sharpened this guidance:

- `union_all_bbox_duration` was 0.075s of 334.068s of
  `bbox_mesh_from_hipoly` time, or 0.023%; do not prioritize default C++
  bbox integration from current evidence.
- `AssetFactory.spawn_asset` timing showed 278.502s total in the latest short
  sample, with `garbage_collect_context_duration` at 177.848s, or 63.859%,
  `create_asset_duration` at 99.383s, or 35.685%, and
  `delete_placeholder_duration` at 0.228s, or 0.082%.
- `GarbageCollect` target timing showed the GC cost is concentrated in
  `exit_cleanup` removal from `bpy.data.node_groups`: target `exit_cleanup`
  was 183.972s, `remove_duration` was 183.378s, and `node_groups` alone was
  181.131s. `enter_snapshot` was only 0.422s, and broad scan time excluding
  remove was about 0.594s.

`spawn_asset`, `create_asset`, `GarbageCollect`, Blender object
creation/deletion, material/node generation, parent/transform operations, and
`bpy` data-block lifecycle are not C++ rewrite targets. They need
behavior-preserving Python/Blender experiments and same seed/gin/task A/B
validation.

## Current Prototype Status

The first standalone Cython/C++ geometry kernel prototype now lives under:

```text
infinigen/core/constraints/cpp/
```

Implemented helpers:

1. `bbox_min_max(points)`
2. `bbox_union(mins, maxs)`
3. `aabb_overlap_matrix(mins_a, maxs_a, mins_b, maxs_b)`
4. `aabb_contains(outer_min, outer_max, inner_min, inner_max)`

The Python wrapper provides NumPy fallback when the compiled extension is not
available. The extension module is:

```text
infinigen.core.constraints.cpp.geometry_kernels_cpp
```

The extension build is optional. By default `python -m pip install -e .`
attempts to build it. To force the fallback-only path:

```bash
INFINIGEN_DISABLE_GEOMETRY_CPP=True python -m pip install -e .
```

These kernels are not connected to the indoor solver, evaluator,
`union_all_bbox`, annealing, or `Addition.apply` by default. Therefore this
prototype should not change generated scenes, random number consumption,
proposal order, or accept/reject decisions.

Boundary contact is currently treated as inclusive overlap/containment in the
AABB prototype. That choice is documented in tests and keeps future broad-phase
use conservative: a pair that touches at the boundary must not be filtered out
before existing exact contact checks run.

Before any solver-facing integration, rerun unit tests, microbenchmarks, and a
same seed/gin/task A/B equivalence comparison. The next possible experiment is
an opt-in `bbox_from_mesh.py` path for `bbox_min_max` / `bbox_union`, not a
solver-control-flow rewrite, and only if bbox timing shows that
`union_all_bbox` is a meaningful share of `bbox_mesh_from_hipoly`.
Current bbox timing does not show that, so the next practical optimization
target is factory lifecycle and `GarbageCollect` behavior, especially
`bpy.data.node_groups` cleanup, not C++ bbox.

See also:

```text
docs/CPP_CALLSITE_SURVEY.md
```

## Priority Rules

P0 candidates are pure computation, do not touch `bpy`, do not touch random
number generation, can accept primitive or NumPy-array inputs, can return
primitive or NumPy-array outputs, and are easy to unit-test and A/B validate.

P1 candidates are mostly pure computation but need Python extraction/wrapping or
careful integration to avoid changing behavior.

P2 candidates may be possible but need larger refactoring or have uncertain
benefit.

Not recommended means the code directly operates on Blender objects, creates or
deletes objects, runs factory orchestration, cleans up `bpy.data` lifecycle,
builds materials/nodes, controls solver order, or consumes random numbers.

## P0 Candidates

### 1. Batch BBox Min/Max Reduction

- File path: `infinigen/assets/utils/bbox_from_mesh.py`
- Function or module: extracted numeric kernel from the inner reduction in
  `union_all_bbox`; do not rewrite the whole function as C++.
- Current logic: `union_all_bbox` walks a Blender object tree, reads each mesh
  child's `bound_box`, applies `matrix_world`, and reduces transformed points
  with NumPy `min` and `max`.
- Why it may be slow: `bbox_mesh_from_hipoly` was a major cProfile hotspot, and
  heavy factories repeatedly compute placeholder/high-poly bounds during failed
  additions. Each mesh child contributes only 8 transformed bbox corners, so the
  numeric reduction is not automatically high ROI. Use
  `infinigen_bbox_timing.csv` to confirm whether `union_all_bbox_duration` is
  meaningful before connecting C++.
- Touches `bpy`: current wrapper yes; proposed C++ kernel no.
- Touches random numbers: no.
- Inputs as primitive/NumPy array: yes, transformed points as `float64[N, 3]` or
  `float64[B, N, 3]`.
- Outputs as primitive/NumPy array: yes, `mins[3]` and `maxs[3]`.
- Could change generation effect: only if floating-point order or dtype changes
  enough to affect downstream constraints. Keep dtype and tolerance explicit.
- A/B equivalence method: unit-test against NumPy on saved arrays, then run same
  seed/gin/task A/B and compare `solve_state.json` plus other JSON with
  `scripts/compare_indoor_outputs.py`.
- Priority: P0 only if bbox timing shows a large `union_all_bbox` share;
  otherwise P1/P2 behind spawn/delete/factory lifecycle work.

### 2. Batch BBox Union

- File path: `infinigen/assets/utils/bbox_from_mesh.py`
- Function or module: extracted numeric union helper for per-child bbox
  `mins/maxs`; related to `union_all_bbox`.
- Current logic: `union_all_bbox` accumulates per-mesh min and max corners while
  iterating Blender mesh children.
- Why it may be slow: repeated bbox aggregation is on the high-poly placeholder
  path seen in the baseline profile. Timing now distinguishes spawn placeholder,
  spawn asset, `union_all_bbox`, bbox mesh creation, cleanup collection, and
  delete work.
- Touches `bpy`: current wrapper yes; proposed C++ kernel no.
- Touches random numbers: no.
- Inputs as primitive/NumPy array: yes, `mins[B, 3]` and `maxs[B, 3]`.
- Outputs as primitive/NumPy array: yes, one `min[3]` and one `max[3]`.
- Could change generation effect: yes if it fixes or changes existing behavior.
  Risk note: `union_all_bbox` currently contains suspicious logic:
  `maxs = pmaxs if maxs is None else np.maximum(pmins, mins)`. This looks like
  a possible bug, but it must not be fixed in this planning round. Any fix could
  change scene geometry and needs a separate sanity test and A/B.
- A/B equivalence method: first compare against current behavior exactly,
  including the suspected behavior. Test any bug fix separately. Then run
  same seed/gin/task A/B with JSON comparison.
- Priority: P0 for exact-behavior union kernel only if new bbox timing shows it
  is a large share; bug fix is separate work.

### 3. AABB Pair Overlap Matrix

- File path:
  `infinigen/core/constraints/evaluator/node_impl/trimesh_geometry.py`
- Function or module: numeric prefilter kernel used before `any_touching` or
  post-move collision checks.
- Current logic: `validity.check_post_move_validity` calls `any_touching`, which
  builds or reuses `trimesh.collision.CollisionManager` objects and asks FCL for
  contact.
- Why it may be slow: collision and validity evaluation are secondary but
  measurable. AABB broad-phase can cheaply eliminate impossible FCL checks
  without changing exact collision results.
- Touches `bpy`: proposed kernel no; surrounding data extraction may.
- Touches random numbers: no.
- Inputs as primitive/NumPy array: yes, candidate mins/maxs and scene
  mins/maxs as arrays.
- Outputs as primitive/NumPy array: yes, bool overlap matrix or candidate index
  pairs.
- Could change generation effect: no if it only skips FCL for pairs whose AABBs
  provably do not overlap and still sends all possible overlaps to the existing
  exact path. Yes if it replaces exact collision.
- A/B equivalence method: unit-test overlap truth tables, assert skipped pairs
  match current no-contact results, then same seed/gin/task JSON A/B.
- Priority: P0 as broad-phase only.

### 4. Axis-Aligned Bounds and Containment Checks

- File path:
  `infinigen/core/constraints/example_solver/geometry/validity.py` and
  `infinigen/core/constraints/evaluator/node_impl/trimesh_geometry.py`
- Function or module: extracted numeric kernel for axis-aligned box containment
  or interval bounds checks.
- Current logic: containment and validity checks are mixed with Shapely,
  trimesh, FCL, and Blender-object access. Some cheap interval checks can be
  represented as numeric array comparisons.
- Why it may be slow: repeated validity checks follow proposal application; a
  batch interval kernel can reduce Python-loop overhead when the relevant
  bounds are already materialized.
- Touches `bpy`: proposed kernel no.
- Touches random numbers: no.
- Inputs as primitive/NumPy array: yes, box mins/maxs and parent bounds.
- Outputs as primitive/NumPy array: yes, bool pass/fail masks.
- Could change generation effect: no only when used as an exact necessary
  condition and not as a replacement for polygon/FCL checks. Risk increases if
  it rejects proposals earlier.
- A/B equivalence method: unit-test against Python interval logic, log skipped
  candidates during a dry run, and require same seed/gin/task JSON A/B.
- Priority: P0 when used after the original random/proposal path is preserved.

### 5. Batch Plane Distance and Support Margin Kernel

- File path:
  `infinigen/core/constraints/example_solver/geometry/stability.py` and
  `infinigen/core/constraints/constraint_language/util.py`
- Function or module: extracted numeric kernel for `distance_to_plane`-style
  point/plane distances and margin checks used by `stable_against` and
  `coplanar`.
- Current logic: relation validity computes polygon normals, plane origins, and
  per-vertex distances through Python loops and Blender utility calls.
- Why it may be slow: relation checks are repeated for many proposals, and the
  numeric part can be batched once vertices/normals are arrays.
- Touches `bpy`: current callers yes; proposed kernel no.
- Touches random numbers: no.
- Inputs as primitive/NumPy array: yes, points `N x 3`, plane origins, normals,
  and margins.
- Outputs as primitive/NumPy array: yes, distances or bool masks.
- Could change generation effect: possible if tolerance handling differs.
  Preserve existing `np.isclose` tolerances exactly.
- A/B equivalence method: unit-test against the current Python/NumPy result for
  captured point/plane arrays, then same seed/gin/task JSON A/B.
- Priority: P0.

### 6. Numeric Loss/Violation Aggregation

- File path: `infinigen/core/constraints/evaluator/evaluate.py`
- Function or module: extracted aggregation over already-computed numeric score
  and violation arrays.
- Current logic: `evaluate_problem`, `EvalResult.loss`, and
  `EvalResult.viol_count` aggregate Python dict values.
- Why it may be slow: `evaluate_duration` is measurable, although not the main
  bottleneck. This kernel is easy to make exact but likely low ROI unless
  evaluation is first restructured to produce arrays.
- Touches `bpy`: no for the aggregation itself.
- Touches random numbers: no.
- Inputs as primitive/NumPy array: yes, arrays of float losses and violation
  counts.
- Outputs as primitive/NumPy array: yes, scalar sums.
- Could change generation effect: possible if summation order changes. Preserve
  Python order if exact reproducibility is required.
- A/B equivalence method: unit-test aggregation order and values, then same
  seed/gin/task JSON A/B.
- Priority: P0 technically, but low expected impact.

## P1 Candidates

### 7. Plane Hashing and Tagged Plane Masks

- File path: `infinigen/core/constraints/example_solver/geometry/planes.py`
- Function or module: `Planes.compute_all_planes_fast`,
  `Planes._compute_tagged_plane_mask`, and `Planes.hash_plane`.
- Current logic: reads Blender vertices/polygons, computes global coordinates
  and normals, hashes approximate planes, and builds boolean face masks.
- Why it may be slow: repeated relation checks use tagged planes and masks.
- Touches `bpy`: current functions yes; extracted numeric core no.
- Touches random numbers: no.
- Inputs as primitive/NumPy array: yes after Python extracts vertices, normals,
  polygon indices, and face masks.
- Outputs as primitive/NumPy array: yes, plane IDs and boolean masks.
- Could change generation effect: yes if hashing, rounding, or tolerance differs.
- A/B equivalence method: compare plane lists and masks on captured objects,
  then run same seed/gin/task JSON A/B.
- Priority: P1 because extraction from Blender mesh data is still required.

### 8. Accessibility Cuboid Penetration Broad-Phase

- File path:
  `infinigen/core/constraints/evaluator/node_impl/trimesh_geometry.py`
- Function or module: `accessibility_cost_cuboid_penetration`.
- Current logic: creates an extruded free-space box from Blender bounds and
  matrix transforms, then uses `CollisionManager` for overlap depth.
- Why it may be slow: it combines Python object access, trimesh object creation,
  and FCL collision checks.
- Touches `bpy`: current function yes; possible broad-phase kernel no.
- Touches random numbers: no.
- Inputs as primitive/NumPy array: yes for bounds, transforms, normal axis, and
  distances.
- Outputs as primitive/NumPy array: yes for broad-phase hit masks; exact depth
  should still come from the existing collision path unless separately proven.
- Could change generation effect: no if used only as a no-overlap prefilter; yes
  if replacing FCL penetration depth.
- A/B equivalence method: unit-test prefilter against current collision calls,
  then same seed/gin/task JSON A/B.
- Priority: P1.

### 9. Closest Edge and 2D Distance Kernels

- File path: `infinigen/core/constraints/constraint_language/util.py` and
  `infinigen/core/constraints/evaluator/node_impl/trimesh_geometry.py`
- Function or module: `closest_edge_to_point_edge_list`,
  `angle_alignment_cost_base`, and related 2D edge distance loops.
- Current logic: builds Shapely `LineString` objects and loops in Python to find
  closest edges for alignment and focus-like scores.
- Why it may be slow: repeated Python/Shapely calls can be expensive if these
  scores become hot.
- Touches `bpy`: current callers sometimes do; extracted edge-distance kernel no.
- Touches random numbers: no.
- Inputs as primitive/NumPy array: yes, edge endpoints and query points.
- Outputs as primitive/NumPy array: yes, closest edge indices and distances.
- Could change generation effect: possible if tie-breaking or distance
  tolerance changes.
- A/B equivalence method: unit-test tie cases and random captured edge sets,
  then same seed/gin/task JSON A/B.
- Priority: P1.

### 10. Room Numeric Metrics

- File path: `infinigen/core/constraints/evaluator/node_impl/rooms.py`
- Function or module: `access_angle_impl`, `aspect_ratio_impl`,
  `grid_line_count_impl`, and simple numeric reductions.
- Current logic: computes room graph and polygon metrics using Python loops,
  NumPy, and Shapely polygons.
- Why it may be slow: room solving is not the current top bottleneck, but some
  metrics are pure numeric after polygon data has been extracted.
- Touches `bpy`: no.
- Touches random numbers: `rand_impl` represents random constraint likelihoods
  and should not be rewritten as part of this candidate.
- Inputs as primitive/NumPy array: partly, after polygon/graph extraction.
- Outputs as primitive/NumPy array: yes for metric values.
- Could change generation effect: yes if polygon or graph semantics differ.
- A/B equivalence method: unit-test each metric against Python on fixed floor
  plans, then same seed/gin/task JSON A/B.
- Priority: P1/P2 depending on measured room-solver timing.

## P2 Candidates

### 11. Shapely Polygon Operations

- File path: `infinigen/core/constraints/example_solver/geometry/stability.py`,
  `infinigen/core/constraints/example_solver/geometry/validity.py`, and
  `infinigen/core/constraints/evaluator/node_impl/rooms.py`
- Function or module: polygon containment, projection, buffering,
  intersection, and narrowness checks.
- Current logic: uses Shapely/trimesh polygon operations.
- Why it may be slow: geometry libraries can be expensive, but they already
  call compiled code internally.
- Touches `bpy`: surrounding callers may.
- Touches random numbers: no.
- Inputs as primitive/NumPy array: not without substantial conversion.
- Outputs as primitive/NumPy array: mostly scalar booleans/floats.
- Could change generation effect: high risk because geometric robustness and
  boundary rules are hard to match exactly.
- A/B equivalence method: extensive geometry unit tests plus same seed/gin/task
  JSON A/B.
- Priority: P2.

### 12. FCL/Trimesh Collision Replacement

- File path:
  `infinigen/core/constraints/evaluator/node_impl/trimesh_geometry.py` and
  `infinigen/core/constraints/constraint_language/util.py`
- Function or module: `any_touching`, `min_dist`, and `col_from_subset`.
- Current logic: builds/reuses `trimesh.collision.CollisionManager` and FCL
  collision objects.
- Why it may be slow: collision setup and exact collision queries are measurable.
- Touches `bpy`: `col_from_subset` can touch Blender when filtering tagged
  faces.
- Touches random numbers: no.
- Inputs as primitive/NumPy array: only after substantial mesh extraction.
- Outputs as primitive/NumPy array: contact booleans, distances, contacts.
- Could change generation effect: high risk if exact contact/depth semantics
  differ.
- A/B equivalence method: only after a large exactness test suite and same
  seed/gin/task JSON A/B.
- Priority: P2 for replacement; P0/P1 only for broad-phase prefilters.

## Not Recommended For C++

### Factory and Blender Object Lifecycle

- File path: `infinigen/core/constraints/example_solver/moves/addition.py`
- Function or module: `sample_rand_placeholder`, `Addition.apply`,
  `Addition.revert`, `Resample.apply`, and `Resample.revert`.
- Current logic: samples seeds, constructs factories, spawns placeholders or
  assets, finalizes Blender mesh objects, updates trimesh scene state, applies
  relation constraints, deletes rejected objects, and runs Blender data-block
  cleanup through `GarbageCollect`.
- Why it may be slow: this is the main hotspot, especially failed heavy
  additions. The current GC sample points specifically to `bpy.data.node_groups`
  removal during cleanup.
- Touches `bpy`: yes.
- Touches random numbers: yes for factory and instance seeds.
- Inputs as primitive/NumPy array: no.
- Outputs as primitive/NumPy array: no.
- Could change generation effect: very high risk.
- A/B equivalence method: required for any Python-level restructuring, but this
  should not be a direct C++ rewrite target.
- Priority: not recommended.

### Asset Creation and Materials

- File path: asset factory modules under `infinigen/assets/`
- Function or module: `spawn_asset`, `spawn_placeholder`, `create_asset`,
  material/node generation.
- Current logic: creates Blender object hierarchies, geometry nodes, materials,
  and tags.
- Why it may be slow: heavy factories such as `KitchenIslandFactory`,
  `LargeShelfFactory`, `TableDiningFactory`, `BeverageFridgeFactory`,
  `LargePlantContainerFactory`, `SimpleBookcaseFactory`, `SimpleDeskFactory`,
  `BathtubFactory`, and `OvenFactory` dominate failed addition apply time.
- Touches `bpy`: yes.
- Touches random numbers: often yes.
- Inputs as primitive/NumPy array: no.
- Outputs as primitive/NumPy array: no.
- Could change generation effect: very high risk.
- A/B equivalence method: same seed/gin/task JSON A/B plus visual sanity checks
  for any behavior-preserving Python refactor.
- Priority: not recommended for C++.

### Solver Control Flow

- File path:
  `infinigen/core/constraints/example_solver/solve.py` and
  `infinigen/core/constraints/example_solver/annealing.py`
- Function or module: move selection, retry loop, simulated annealing step,
  Metropolis-Hastings accept/reject logic.
- Current logic: controls proposal order, retry behavior, evaluation,
  acceptance, rejection, and garbage collection.
- Why it may be slow: every proposal passes through this code, but the flow
  defines behavior.
- Touches `bpy`: indirectly through moves and garbage collection.
- Touches random numbers: yes, move choice and acceptance can consume random
  numbers.
- Inputs as primitive/NumPy array: no.
- Outputs as primitive/NumPy array: no.
- Could change generation effect: extremely high risk.
- A/B equivalence method: required for instrumentation only; do not rewrite in
  C++.
- Priority: not recommended.

### Cheap Preflight Rejection As A C++ Shortcut

- File path: would likely affect `addition.py`, `validity.py`, and evaluator
  modules.
- Function or module: any early rejection inserted before the original proposal
  path.
- Current logic: proposals are applied, evaluated, accepted, or reverted in a
  specific order.
- Why it may be slow: failed heavy additions waste most apply time.
- Touches `bpy`: depends on implementation.
- Touches random numbers: risk is high even if the preflight itself does not.
- Inputs as primitive/NumPy array: maybe.
- Outputs as primitive/NumPy array: maybe.
- Could change generation effect: high risk because earlier rejection can alter
  retry count, random consumption, object side effects, and final scene.
- A/B equivalence method: must prove same random number sequence, proposal
  order, accept/reject decisions, and final JSON output before entering the main
  path.
- Priority: not recommended as a C++ shortcut. Consider only as a separately
  proven behavior-preserving Python design.
