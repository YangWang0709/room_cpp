# MaskTag Investigation

## Scope

This note investigates the completed full 10-room A/B for the opt-in
`INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1` candidate. It does not introduce a
new optimization, does not change `batch_remove`, and does not change
`scripts/compare_indoor_outputs.py`.

Compared folders:

```text
outputs/gc_batch_remove_equiv/baseline/coarse
outputs/gc_batch_remove_equiv/candidate_batch/coarse
```

## Full Baseline A/A Follow-Up

A later full 10-room baseline repeat compared the existing baseline A against a
new baseline B without enabling batch remove:

```text
baseline A: outputs/gc_batch_remove_equiv/baseline/coarse
baseline B: outputs/determinism_full_baseline_b/coarse
```

Baseline B used the same seed, task, gin, and overrides as the original full
target:

```text
seed 0
task coarse
fast_solve.gin
compose_indoors.terrain_enabled=False
home_room_constraints.has_fewer_rooms=False
restrict_solving.solve_max_rooms=10
INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS unset
```

The full baseline B run completed with `MAIN TOTAL` `4:25:03.044391`. No
timeout, traceback, OOM, killed, or segfault marker was found.

`scripts/compare_indoor_outputs.py` reported:

```text
matched_json_file_count: 2
DIFFERENT MaskTag.json numeric_max_abs_diff=1
  $.back.bottom: left 22, right 21
  $.front.top: left 21, right 22
SAME solve_state.json numeric_max_abs_diff=0
numeric_max_abs_diff: 1
FINAL: FAIL
```

This is the same `back.bottom` / `front.top` label-ID swap observed in the
full baseline-vs-batch A/B. Therefore this `MaskTag.json` difference is not
currently attributable to `INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1`.

The read-only static blend diagnostic also failed for full
baseline-vs-baseline:

```text
STATIC_SCENE_FAIL
USD_RELEVANT_DIFF: yes
UNUSED_DATABLOCK_DIFF: no
UNUSED_DATABLOCK_DIFF_ONLY: no
static_scene_diff_count: 60
unused_datablock_diff_count: 0
```

The diagnostic found matching object counts and linked datablock counts but
linked scene differences, including `NatureShelfTrinketsFactory` mesh
vertex/edge/polygon counts and small pillow/towel transform differences. Since
both single-room and full baseline A/A can fail the static blend diagnostic,
saved `.blend` static-scene differences are not a batch-remove-specific
rejection signal by themselves.

The important stable evidence remains `solve_state.json SAME`. The current
strict JSON gate is not baseline-deterministic because `MaskTag.json` label ID
insertion order can vary even under baseline behavior.

## Generation Path

For the indoor coarse task, `MaskTag.json` is written from the global tag
system in `infinigen/core/execute_tasks.py` after the coarse `scene.blend` is
saved:

```text
infinigen_examples/generate_indoors.py
  -> infinigen/core/execute_tasks.py::execute_tasks
  -> infinigen/core/tagging.py::AutoTag.save_tag
```

The relevant implementation pieces are:

- `infinigen/core/tagging.py`: defines `COMBINED_ATTR_NAME = "MaskTag"`,
  stores per-face integer `MaskTag` attributes, and serializes
  `tag_system.tag_dict`.
- `infinigen/core/tagging.py::tag_canonical_surfaces`: creates canonical
  `back`, `front`, `top`, and `bottom` tags.
- `infinigen/core/constraints/example_solver/moves/addition.py`: tags
  placeholders created during `Addition.apply`.
- `infinigen/core/constraints/example_solver/populate.py`: retags populated
  objects when synchronizing modified objects back into the solver state.
- `infinigen/core/constraints/example_solver/room/solidifier.py`: creates
  room surface tags such as `support`, `wall`, `ceiling`, `visible`, and
  `interior`.
- `infinigen/core/execute_tasks.py`: loads `MaskTag.json` for downstream
  non-coarse tasks and saves it for coarse/populate/fine terrain outputs.

`MaskTag.json` is the serialized mapping from semantic tag names to integer
label IDs. The integer ID is also used in the Blender mesh face attribute named
`MaskTag`.

## Field Meaning

`back.bottom` and `front.top` are combined tag names. The tag system combines
overlapping tag masks by dot-joining the sorted tag parts.

The canonical surface meanings in `tag_canonical_surfaces` are:

- `back`: local object x minimum.
- `front`: local object x maximum.
- `bottom`: local object z minimum.
- `top`: local object z maximum.

Therefore:

- `back.bottom` means a face tagged with both `back` and `bottom`.
- `front.top` means a face tagged with both `front` and `top`.

The values `21` and `22` are tag label IDs in `tag_system.tag_dict`. They are
not object IDs, mesh IDs, material IDs, proposal IDs, or Blender collection
IDs. They are assigned by insertion order with `len(tag_dict) + 1` when a new
tag name is first seen.

In this A/B:

| tag ID | baseline | candidate_batch |
| ---: | --- | --- |
| 21 | `front.top` | `back.bottom` |
| 22 | `back.bottom` | `front.top` |

All other `MaskTag.json` keys and values matched.

## Use Sites

`MaskTag` and `MaskTag.json` are used for semantic tag lookup and tag-based
selection, especially for mask or annotation workflows:

- `infinigen/core/tagging.py` reads and writes `MaskTag` face attributes.
- `infinigen/core/placement/density.py` can create geometry-node masks by
  comparing the `MaskTag` attribute to IDs from the tag dictionary.
- `infinigen/core/placement/camera.py` can select faces by matching
  `mesh.face_attributes["MaskTag"]` to IDs from `tag_system.tag_dict`.
- `docs/GroundTruthAnnotations.md` documents Tag Segmentation as a mask whose
  integer values are associated with labels through `MaskTag.json`.
- `infinigen/datagen/customgt/src/buffer_arrays.cpp` reads saved
  `*_masktag` arrays and `infinigen/datagen/customgt/main.cpp` writes
  `TagSegmentation_*.npy`.

For static USD export and Isaac Sim import:

- `infinigen/tools/export.py` exports USD through Blender's
  `bpy.ops.wm.usd_export`; it does not read `MaskTag.json`.
- `infinigen/tools/isaac_sim.py` loads a USD scene and optionally reads
  relation data from `solve_state.json`; it does not read `MaskTag.json`.
- `infinigen/core/util/exporting.py` has a `masktag` field for mesh-save NPZs,
  but the current code path initializes it to zeros because the attribute read
  is behind `if False and "MaskTag" in obj.data.attributes`.

The JSON mapping itself is therefore not an input to Blender geometry creation,
material creation, USD export, or Isaac's static collider setup in the inspected
paths. It is an annotation/tag lookup artifact. However, the Blender face
attribute and tag dictionary can be used by generation-time tag selection code
before the file is saved.

## A/B Output Summary

`scripts/compare_indoor_outputs.py` reported:

```text
matched_json_file_count: 2
DIFFERENT MaskTag.json numeric_max_abs_diff=1
  $.back.bottom: left 22, right 21
  $.front.top: left 21, right 22
SAME solve_state.json numeric_max_abs_diff=0
FINAL: FAIL
```

Additional checks:

- `solve_state.json` is not byte-identical. The SHA256 hashes differ.
- After applying the compare script's canonicalization, `solve_state.json` is
  equal. The observed byte difference is unordered tag-list ordering, for
  example `-Subpart(front)` and `-Subpart(back)` appearing in the opposite
  order.
- `MaskTag.json` has the same 119 keys on both sides. The only value
  differences are the two-ID swap above.
- `assets/info.pickle`, `optim_records.png`, and `version.txt` are
  byte-identical.
- `pipeline_coarse.csv` differs in memory columns, but object counts per stage
  match.
- `optim_records.csv` has the same 5830 rows. Ignoring timing columns, the
  sampled differences are only 23 floating point text differences with maximum
  absolute difference `1.4210854715202004e-14`; no accept/reject or move
  sequence difference was found by this check.
- `polycounts.txt` differs: candidate has more vertices/faces/tris, especially
  under `unique_assets`.
- `scene.blend` is not byte-identical and has different file sizes.

Blender background summary for `scene.blend`:

| metric | baseline | candidate_batch |
| --- | ---: | ---: |
| objects | 809 | 809 |
| mesh objects | 744 | 744 |
| mesh datablocks | 744 | 744 |
| total mesh vertices | 32,305,150 | 32,879,496 |
| total mesh polygons | 49,675,254 | 50,829,448 |
| materials | 1,165 | 1,165 |
| node groups | 2,139 | 2,164 |
| mesh datablocks with `MaskTag` | 491 | 491 |

The object name set and mesh datablock name set matched. There were still
non-JSON scene differences:

- 3 common objects had transform differences above `1e-9`, with maximum
  absolute transform difference `0.0033512119999999923`.
- 31 common mesh datablocks had different mesh info.
- Material name sets differed by 12 names on each side.
- Candidate had 25 extra node group names.

This means the current A/B cannot be treated as Isaac static scene equivalent
from the blend evidence, even though the strict JSON compare only reports
`MaskTag.json` as different.

## Interpretation

The `MaskTag.json` difference alone does not prove a furniture layout change.
The strongest layout evidence is the canonicalized `solve_state.json` result,
which is `SAME`, and the matching `pipeline_coarse.csv` object counts.

The `MaskTag.json` difference alone does not prove a geometry change. It is a
label-ID mapping swap between two semantic tag names. In this run, however,
`polycounts.txt` and the Blender summary show actual `.blend` geometry
differences, so the full A/B output is not static-scene equivalent.

The `MaskTag.json` difference alone does not prove a material change. It is not
used as a material input in the inspected export/material paths. In this run,
the Blender summary did find material name differences, so material equivalence
is also not established.

For Isaac Sim static USD import, the inspected code does not read
`MaskTag.json`. A pure ID swap in this JSON mapping should not affect static
USD import, static colliders, or object transforms by itself. This specific
A/B still cannot be accepted for Isaac static equivalence because the saved
blend contains geometry, material, transform, and node group differences.

For training annotations, `MaskTag.json` is directly relevant to tag
segmentation label lookup. A raw numeric ID swap can affect consumers that
treat IDs as globally stable. A semantic consumer that always reads the
per-scene `MaskTag.json` may still recover the same tag names, but that must be
validated against generated TagSegmentation outputs rather than assumed from
the JSON mapping alone.

## Suggested Validation Gates

Do not relax `scripts/compare_indoor_outputs.py` in this investigation. A
future validation design could split the current single gate into separate
purposes:

1. Strict equivalence: require current JSON compare PASS and, if needed, add
   byte or structural checks for blend-derived summaries.
2. Isaac static scene equivalence: compare the exported USD-relevant scene
   surface, including object names, transforms, mesh counts or mesh hashes,
   material assignments, visibility, and collider-relevant relation data.
   `MaskTag.json` could be reported but should not be the only blocker for this
   mode if the exported static scene is proven equivalent.
3. GT annotation equivalence: compare `MaskTag.json`, `TagSegmentation`,
   object/instance segmentation, and any per-pixel or per-face annotation data
   using both raw IDs and semantic label interpretation.

Any adjustment to `compare_indoor_outputs.py` should be proposed and reviewed
separately. It should not be made as part of this batch-remove investigation.

## Determinism Follow-Up

The next diagnostic round added a read-only static blend comparator and an A/A
ablation script:

```bash
python scripts/compare_blend_static_scene.py LEFT.blend RIGHT.blend
python scripts/compare_blend_static_scene.py outputs/a/coarse outputs/b/coarse

EXPERIMENT_SMOKE_SINGLE_ROOM=1 \
EXPERIMENT_TIMEOUT_SECONDS=3600 \
PYTHON_BIN=/home/ubuntu22/miniconda3/envs/infinigen/bin/python \
bash scripts/run_determinism_ablation.sh
```

`scripts/compare_blend_static_scene.py` opens `scene.blend` in Blender
background mode, does not save, and compares a USD/Isaac-relevant static scene
summary: object names/counts/types, transforms, per-object mesh vertex/edge/
polygon counts, material slots, linked material names, and linked node group
names. It separately reports unused mesh/material/node group datablocks and
prints either `STATIC_SCENE_PASS` or `STATIC_SCENE_FAIL`, plus
`USD_RELEVANT_DIFF`, `UNUSED_DATABLOCK_DIFF_ONLY`, or `NO_DIFF`.

The 2026-06-20 smoke A/A result was:

| pair | JSON compare | static blend compare | notes |
| --- | --- | --- | --- |
| baseline_a vs baseline_b | `FINAL: PASS` | `STATIC_SCENE_FAIL` / `USD_RELEVANT_DIFF: yes` | 23 linked static-scene diffs, no unused-only diffs |
| candidate_a vs candidate_b | `FINAL: PASS` | `STATIC_SCENE_FAIL` / `USD_RELEVANT_DIFF: yes` | 26 linked static-scene diffs, no unused-only diffs |

Both baseline smoke runs completed, and both candidate smoke runs completed.
No timeout, traceback, OOM, killed, or segfault marker was found. The JSON
compare saw `MaskTag.json` and `solve_state.json` as exactly same in both
pairs. The static blend comparator still found linked scene differences,
mainly wall/floor/ceiling material slot differences and some wall mesh
vertex/edge/polygon count differences. Object counts and object type counts
matched in both pairs.

This means the saved `.blend` static-scene differences are not proven to be
introduced by `INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1`. At least in the smoke
configuration, baseline same-seed A/A is JSON-deterministic but not saved-blend
static-scene deterministic under the new comparator.

A later full 10-room baseline A/A is recorded above. It showed the same
`MaskTag.json` `back.bottom` / `front.top` label-ID swap and also failed the
static blend diagnostic. That full result supersedes the earlier "full A/A
still required" note: baseline variability is now confirmed on the normal
10-room target for both the current strict JSON gate and the saved-blend static
diagnostic.
