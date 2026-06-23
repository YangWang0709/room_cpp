# C++ Callsite Survey

## Scope

This survey is based on `rg` searches for:

```text
".min(axis=0)", ".max(axis=0)", "np.minimum", "np.maximum", "overlap",
"collision", "bounds", "contain", "AABB", "bbox"
```

The goal is to find call sites where a C++ kernel could help without touching
Blender `bpy`, random number generation, solver control flow, proposal order, or
accept/reject logic. A syntactic `min(axis=0)` match is not enough: the expected
array size and surrounding side effects matter.

## Candidates

### 1. `infinigen/assets/utils/bbox_from_mesh.py::union_all_bbox`

- Current logic: walks a Blender object tree, transforms each mesh child's 8
  `bound_box` corners with `matrix_world`, then reduces min/max and accumulates
  a union.
- Input data scale estimate: 8 points per mesh child; many repeated calls in
  heavy failed additions, but each numeric reduction is tiny.
- Touches `bpy`: yes in the wrapper, through object tree traversal and
  `bound_box`.
- Touches random numbers: no.
- Pure array computation: only the inner transformed-corner min/max is pure.
- Could change generation effect: yes if the existing suspicious max update is
  fixed or if dtype/order changes. The suspected `union_all_bbox` bug remains
  intentionally unfixed.
- Suitable for C++: only as an exact-behavior opt-in inner numeric helper after
  bbox timing shows `union_all_bbox_duration` is meaningful.
- Priority: P1 until timing proves it is a large share; not P0 by syntax alone.

### 2. `infinigen/assets/utils/bbox_from_mesh.py::bbox_mesh_from_hipoly`

- Current logic: spawns placeholder, optionally spawns the full asset, computes
  a bbox mesh from corners, collects temporary objects, and deletes them.
- Input data scale estimate: expensive by call count and asset weight, but most
  work is Blender/factory object lifecycle rather than large arrays.
- Touches `bpy`: yes, heavily.
- Touches random numbers: indirectly through factory spawn methods seeded before
  the call path.
- Pure array computation: no; it orchestrates object creation/deletion.
- Could change generation effect: very high if rewritten or reordered.
- Suitable for C++: no for the function itself.
- Priority: not recommended for C++; instrument and optimize behavior-preserving
  Python/Blender work instead.

### 3. `infinigen/core/constraints/evaluator/node_impl/trimesh_geometry.py::any_touching`

- Current logic: builds or reuses `CollisionManager` objects and asks FCL for
  internal, single, or pairwise collision results.
- Input data scale estimate: one candidate object against many scene objects in
  post-move validity; can become many boxes/pairs after bounds are materialized.
- Touches `bpy`: not in the core collision call, but tag-filtered subsets can
  fetch Blender objects through `col_from_subset`.
- Touches random numbers: no.
- Pure array computation: not currently; a broad-phase AABB prefilter could be.
- Could change generation effect: no only if used as a conservative prefilter
  that skips FCL solely for provably non-overlapping AABBs and preserves all
  possible overlaps.
- Suitable for C++: yes for an opt-in broad-phase over numeric bbox arrays; no
  for replacing FCL exact collision.
- Priority: P0 as a broad-phase experiment after array extraction is measured.

### 4. `infinigen/core/constraints/constraint_language/util.py::col_from_subset`

- Current logic: constructs a `trimesh.collision.CollisionManager`, optionally
  extracts tagged submeshes, caches managers, and registers FCL objects.
- Input data scale estimate: number of candidate scene objects per validity or
  distance query; can be substantial, but setup is object/FCL-heavy.
- Touches `bpy`: yes when tags are used.
- Touches random numbers: no.
- Pure array computation: no.
- Could change generation effect: high if C++ changes collision object
  membership, tag filtering, or cache keys.
- Suitable for C++: not as a rewrite target; it may feed a separate numeric
  broad-phase.
- Priority: P2 for direct rewrite, P0/P1 only as a data source for broad-phase
  bounds.

### 5. `infinigen/core/constraints/evaluator/node_impl/trimesh_geometry.py::accessibility_cost_cuboid_penetration`

- Current logic: creates extruded freespace boxes from object bbox/dimensions,
  builds a collision manager, and measures penetration contacts.
- Input data scale estimate: one or more source objects against candidate
  blockers; more useful as a prefilter than as exact replacement.
- Touches `bpy`: yes for `bpy.data.objects`, dimensions, bound boxes, and
  transforms.
- Touches random numbers: no.
- Pure array computation: the axis-aligned direction, bbox offset, and overlap
  broad-phase are pure once arrays are extracted.
- Could change generation effect: no if it only skips impossible collisions;
  yes if it replaces penetration depth.
- Suitable for C++: P1 for an opt-in broad-phase prefilter; not suitable for
  replacing the collision query.
- Priority: P1.

### 6. `infinigen/core/constraints/example_solver/geometry/planes.py::compute_all_planes_fast`

- Current logic: reads Blender vertices and polygon normals, hashes approximate
  planes, and returns one representative polygon per unique plane.
- Input data scale estimate: number of polygons on a tagged mesh; can be larger
  than 8-point bboxes for detailed assets.
- Touches `bpy`: yes for mesh vertices and polygons.
- Touches random numbers: no.
- Pure array computation: the normal normalization, plane hashing, and mask
  comparisons are pure after extraction.
- Could change generation effect: yes if rounding, hash tolerance, normal
  direction, or representative polygon choice changes.
- Suitable for C++: possible extracted numeric kernel, but extraction and exact
  tolerance matching are delicate.
- Priority: P1.

### 7. `infinigen/core/constraints/example_solver/geometry/stability.py::stable_against` and `coplanar`

- Current logic: checks tagged plane alignment, projects meshes with trimesh and
  Shapely, and loops over polygon vertices to compare plane distances.
- Input data scale estimate: small per relation, repeated many times across
  proposal validity checks.
- Touches `bpy`: yes for objects, polygons, normals, and vertex coordinates.
- Touches random numbers: no.
- Pure array computation: only the batched point-to-plane distance and dot
  checks are pure.
- Could change generation effect: possible if tolerances or boundary rules
  differ.
- Suitable for C++: possible for extracted point/plane distance arrays after
  timing shows relation checks matter.
- Priority: P1.

### 8. `infinigen/core/constraints/evaluator/node_impl/trimesh_geometry.py::angle_alignment_cost_base`

- Current logic: projects meshes to Shapely polygons, builds edge LineStrings,
  finds closest edge to object centroids, and computes axis/normal dot costs.
- Input data scale estimate: number of projected polygon edges per queried
  object set; can be larger than bbox reductions.
- Touches `bpy`: yes for object axes and Blender object lookup.
- Touches random numbers: no.
- Pure array computation: closest-edge distance and dot-cost loops can be pure
  after edge arrays and query points are extracted.
- Could change generation effect: yes if closest-edge ties or Shapely distance
  semantics differ.
- Suitable for C++: possible but should preserve tie-breaking exactly.
- Priority: P1.

### 9. `infinigen_examples/generate_indoors.py::compose_indoors` bbox reductions

- Current logic: concatenates room object `butil.bounds` results and computes
  solved/house bboxes with NumPy min/max.
- Input data scale estimate: room count and scene object count, usually small
  compared with proposal attempts and asset spawning.
- Touches `bpy`: yes through `butil.bounds`.
- Touches random numbers: no.
- Pure array computation: final min/max over concatenated 8-corner boxes is
  pure but small.
- Could change generation effect: low, but downstream camera/export setup uses
  the result.
- Suitable for C++: technically possible, low ROI.
- Priority: P2.

### 10. `infinigen/core/util/exporting.py::calc_instance_bbox`

- Current logic: computes a single mesh bbox, transforms bbox corners for many
  instance matrices with `einsum`, and reduces the combined bbox.
- Input data scale estimate: potentially many instances per exported mesh.
- Touches `bpy`: no inside `calc_instance_bbox`; callers gather object data.
- Touches random numbers: no.
- Pure array computation: yes.
- Could change generation effect: only export metadata/visibility bounds, not
  indoor solver decisions.
- Suitable for C++: yes if export bbox timing becomes hot, but it is outside the
  current indoor coarse bottleneck.
- Priority: P1 for export, P2 for indoor coarse speedup.

### 11. `infinigen/core/util/blender.py::bounds`

- Current logic: converts one object's 8 local `bound_box` corners to a NumPy
  array and reduces min/max.
- Input data scale estimate: exactly 8 points per call.
- Touches `bpy`: yes through object `bound_box`.
- Touches random numbers: no.
- Pure array computation: only the final tiny reduction.
- Could change generation effect: low if exact, but not worth kernel overhead.
- Suitable for C++: no for normal use.
- Priority: not recommended.

### 12. `infinigen/core/util/math.py::BBox`

- Current logic: small vector min/max, containment, union, intersection, and
  random uniform sampling.
- Input data scale estimate: low-dimensional boxes, usually one at a time.
- Touches `bpy`: no.
- Touches random numbers: `BBox.uniform` does.
- Pure array computation: union/intersection/contains are pure; uniform is not.
- Could change generation effect: yes if `uniform` or containment semantics
  change.
- Suitable for C++: no expected benefit at current scale.
- Priority: not recommended.

## Summary

The best C++ candidates are not the Blender wrappers themselves. They are
extracted numeric kernels used after data is already available as arrays:

1. AABB broad-phase prefilters before exact FCL collision calls.
2. Plane hashing or tagged-plane mask numeric cores, if timing shows they are
   hot.
3. Point-to-plane and edge-distance batches, if relation/evaluator timing grows.
4. Export-time batch bbox computation, if export profiling calls for it.

`bbox_from_mesh.py` remains a measured candidate, but each child bbox reduction
uses only 8 points. Do not connect `bbox_min_max` to that path by default unless
`infinigen_bbox_timing.csv` shows `union_all_bbox_duration` is a meaningful
share of total `bbox_mesh_from_hipoly` time. Any integration must be opt-in and
must pass same seed/gin/task A/B output comparison.

The current bbox timing sample measured `union_all_bbox` at 0.075s out of
334.068s, or 0.023%, so it is not a current C++ priority. The follow-up asset
factory timing sample moved the first bottleneck to `AssetFactory.spawn_asset`
and factory lifecycle, especially `GarbageCollect` context work. The GC target
sample then localized that cost to `exit_cleanup` removal from
`bpy.data.node_groups`: target `exit_cleanup` was 183.972s, `remove_duration`
was 183.378s, `node_groups` alone was 181.131s, `enter_snapshot` was 0.422s,
and broad scan time excluding remove was about 0.594s.

Those paths touch `bpy`, object creation/deletion, material/node data,
parent/transform state, `bpy.data` lifecycle, and seeded factory behavior, so
they are not C++ call-site candidates. Any future GC scope adjustment, deferred
cleanup, less frequent cleanup, batch cleanup, delete batching, or factory
bbox/cache experiment must be opt-in, behavior-preserving, and validated with
same seed/gin/task A/B output comparison.
