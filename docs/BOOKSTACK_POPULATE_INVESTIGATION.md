# BookStack Populate Investigation

## Scope

This is a P1 populate-clutter investigation line. It adds optional timing and
a targeted microbenchmark only. It does not optimize BookStack generation,
does not reduce book count, does not change solver behavior, does not change
random flow, and does not add concurrency.

## Source Path

`BookStackFactory`, `BookColumnFactory`, and `BookFactory` are defined in:

```text
infinigen/assets/objects/table_decorations/book.py
```

They are exported through:

```text
infinigen/assets/objects/table_decorations/__init__.py
```

Indoor semantics reference them in:

```text
infinigen_examples/constraints/semantics.py
```

## Call Chain

Final populate path:

```text
populate_state_placeholders(final=True)
  os.generator.spawn_asset(i=inst_seed, loc=placeholder.location, rot=...)
    AssetFactory.spawn_asset()
      BookStackFactory.create_placeholder()
      BookStackFactory.create_asset()
        choose one of self.base_factories
        BookFactory.create_asset()
          self.surface_material_gen()
          make_paperback() or make_hardcover()
          make_cover()
            wrap_front_back_side(obj, self.cover_surface, ...)
        position and rotate each book
        join_objects(books)
```

`BookColumnFactory` has the same inner `BookFactory.create_asset()` pattern but
lays books side by side and uses `longest_ray()` to resolve adjacent offsets.

## Likely Slow Points

- Per-book geometry creation: each stack contains about 5-15 books in the
  source logic.
- Per-book paper material generation in `BookFactory.create_asset()`.
- Cover material generation in `BookFactory.__init__()`: this calls
  `infinigen.assets.materials.text.Text`, which uses matplotlib, font
  selection, text drawing, barcode / patch drawing, a packed Blender image, and
  shader node material creation. This happens when the nested `BookFactory`
  instances are constructed, not inside the final stack `create_asset()` call.
- `wrap_front_back_side()` assigns cover UVs/materials and can create material
  slots / node groups.
- `join_objects(books)` and repeated transforms add smaller geometry costs.

## Timing

Optional timing is enabled with:

```bash
INFINIGEN_PROFILE_BOOKSTACK=1
```

CSV path:

```text
<output_folder>/infinigen_bookstack_timing.csv
```

Fallback path:

```text
/tmp/infinigen_bookstack_timing.csv
```

Targeted runs can override the path with:

```bash
INFINIGEN_BOOKSTACK_TIMING_CSV=/path/to/infinigen_bookstack_timing.csv
```

The timing records `BookStackFactory`, `BookColumnFactory`, and nested
`BookFactory` rows. Nested rows mean created datablock totals can double-count
when summing all rows; use the factory breakdown to distinguish stack-level
inclusive counts from per-book rows.

Fields include total duration, geometry duration, material duration,
font/text duration if safely measurable, per-book create duration, placement
duration, join duration, before/after counts for materials, textures, node
groups, meshes, objects, and images, created counts, success, and error type.

Analyze with:

```bash
python scripts/analyze_bookstack_timing.py \
  outputs/bench_bookstack/infinigen_bookstack_timing.csv
```

## Targeted Microbenchmark

Added:

```text
scripts/bench_bookstack_factory.py
```

Default:

```bash
python scripts/bench_bookstack_factory.py \
  --samples 30 \
  --seed 0 \
  --output_folder outputs/bench_bookstack
```

The benchmark instantiates `BookStackFactory(factory_seed)`, creates a
placeholder, calls `spawn_asset(inst_seed, placeholder=placeholder)`, records
timing, and deletes generated objects. It is not a complete-scene walltime
result.

Result from the first 30-sample run:

| metric | value |
| --- | ---: |
| benchmark samples | 30 |
| benchmark failures | 0 |
| CSV rows | 307 |
| CSV failures | 0 |
| measured CSV total | `4.827s` |
| stack rows total | `2.490s` |
| nested `BookFactory` rows total | `2.337s` |
| stack max row | `0.149s` |

Stack rows created `277` materials, `277` node groups, `554` meshes, and
`30` objects. Nested `BookFactory` rows created the same material / node group
families, so all-row totals double-count inclusively.

The benchmark stdout showed repeated `findfont` warnings. The CSV did not show
create-asset-time image creation or `font_text_duration`, which matches the
source: cover `Text` material and image construction happen during
`BookFactory.__init__()` when base factories are built, not in
`BookStackFactory.create_asset()`.

## Reuse Suitability

Potential later opt-in candidates:

- Paper / plaster material template reuse, if per-book variation can be kept
  without changing random flow.
- Cover shader node template reuse, if generated image and material parameters
  remain unique per book.
- Font lookup / matplotlib setup cache, if it can be proven not to change cover
  text, font choice, image content, or random consumption.

Not suitable for broad reuse:

- Full book meshes or full stacks, because that would reduce visible clutter
  variation.
- Generated cover images or text layouts across books, because they encode
  random text, font, colors, barcode layout, patches, and wear variation.
- Any reuse that skips `BookFactory.__init__()` random sampling.

## Risk

Book covers are visually salient shelf clutter. Reusing too much can flatten
book variety, reduce random cover diversity, or change font/text appearance.
Any future reuse must remain opt-in and should pass a Blender/Isaac visual
check before a full 10-room quality validation.
