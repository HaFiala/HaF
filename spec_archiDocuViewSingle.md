# Specification: archiDocuViewSingle.py

## Purpose

Generates a single combined HTML file documenting every element found in a named ArchiMate view. Each element's spec is produced using helpers from `archimate_spec_v3.py` (imported as a module at runtime).

```
python3 archiDocuViewSingle.py <model.xml> "<view name>"
```

Output: `{sanitised_view_name}.html`

---

## Dependency on archimate_spec_v3.py

At startup, the script locates `archimate_spec_v3.py` using:

```python
_SPEC_SCRIPT = pathlib.Path(__file__).parent / "archimate_spec_v3.py"
```

It loads it as a module via `importlib.util`. This means both files must always reside in the **same directory**. All spec logic lives in `archimate_spec_v3.py`; this script only handles view traversal, page assembly, and output.

Functions used from the imported module (`v3`):

| Call | Purpose |
|---|---|
| `v3.parse_model(xml_path)` | Parse XML |
| `v3.collect_elements(root)` | Build element dict |
| `v3.collect_relations(root)` | Collect all relations |
| `v3.collect_profiles(root)` | Collect profiles |
| `v3.get_type(el)` | Get element type |
| `v3.get_name(el)` | Get element name |
| `v3.get_doc(el)` | Get element documentation |
| `v3.resolve_abbreviations(doc, el_id, relations, elements, profiles)` | Resolve `˝˝X˝˝` tokens |
| `v3.render_description_conf(processed)` | Render description to HTML |
| `v3.expand_compositions(body_html, el_id, el_type, elements, relations, profiles, depth, visited)` | Expand inline child specs |
| `v3.collect_relation_rows(el_id, el_type, relations, elements, profiles, used_ids)` | Collect all relation rows |
| `v3._relations_html(rows, used_ids, empty_msg, incoming)` | Render relation rows to HTML |
| `v3.CSS` | Shared CSS string |

---

## View Traversal

### `find_view(root, view_name)`

Iterate all elements. Match elements whose `xsi:type` is one of:
- `archimate:ArchimateDiagramModel`
- `archimate:SketchModel`
- `archimate:CanvasModel`

Return the first whose `name` attribute (stripped) matches `view_name` (stripped). Return `None` if not found.

### Skip types

The following element types are ignored during view traversal (diagram decorators, not model elements):

```
DiagramObject, DiagramModelNote, DiagramModelGroup,
DiagramModelConnection, DiagramModelReference,
SketchModelSticky, SketchModelActor, Connection
```

Any element whose type contains `"Relationship"` is also skipped.

### `_resolve_archimate_element(node, elements)`

Given a diagram node, find its corresponding model element:
1. Check `archimateElement` attribute — if present, look up in elements dict
2. Check `model` attribute — if present, look up in elements dict
3. Otherwise check `xsi:type` (stripped of `archimate:` prefix): if not in skip types and not a Relationship, look up node's own `id` in elements dict
4. Return `None` if nothing found

### `collect_view_elements(view_node, elements)`

Recursively walk all children of the view node. For each node:
- Resolve to a model element via `_resolve_archimate_element`
- Skip if element is `None`, has no `id`, has empty `name`, is in skip types, or has already been seen (dedup by element id)
- Append to result list in document order

Returns ordered list of unique model elements referenced in the view.

---

## Per-Element Spec Rendering (`render_element_body`)

For each element in the view, produce `(el_name, el_type, body_html, out_html, inc_html)`:

1. Get `el_id`, `el_type`, `el_name`, `doc` from element
2. `processed, used_ids = v3.resolve_abbreviations(doc, el_id, relations, elements, profiles)`
3. `body_html = v3.render_description_conf(processed)`
4. `body_html = v3.expand_compositions(body_html, el_id, el_type, elements, relations, profiles, depth=0, visited={el_id})`
5. `outgoing_rows, incoming_rows = v3.collect_relation_rows(el_id, el_type, relations, elements, profiles, used_ids)`
6. `out_html = v3._relations_html(outgoing_rows, used_ids, "No outgoing relations.")`
7. `inc_html = v3._relations_html(incoming_rows, set(), "No incoming relations.", incoming=True)`

---

## Slug Generation

For sidebar anchors and element `id` attributes:

```
slugify(name):
  strip characters not in [\w\s-]
  strip whitespace
  replace whitespace runs with "-"
  lowercase
  truncate to 60 characters
```

Slugs are deduplicated within a run: if a slug already exists, append `-1`, `-2`, etc.

---

## Output HTML Structure

### CSS

Base CSS is `v3.CSS` plus additional single-file layout rules:

- `body`: `max-width: 960px`, `padding: 2rem`
- `#page-header`: bottom border, contains view title and element count
- `.el-card`: `margin-bottom: 3rem`, separated by bottom border (last card has none)
- `.el-card h2`: `font-size: 19px`, type in a `<span>` with gray small font

### Page layout

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>{view_name} — Documentation</title>
  <style>{CSS}</style>
</head>
<body>

<header id="page-header">
  <h1>{view_name}</h1>
  <p class="count">{N} element(s)</p>
</header>

{el-card for each element}

</body>
</html>
```

### Element card

```html
<div class="el-card" id="{slug}">
  <h2>
    <span>«{el_type}»</span>{el_name}
  </h2>

  <section>
    {body_html}
  </section>

  <section>
    <p><strong>Related context</strong></p>
    {out_html}
    {inc_html}
  </section>
</div>
```

Note: `«Type»` in `<h2>` is in a separate `<span>` — visual spacing via CSS only, no literal space in text.

---

## Output File

Output directory: `c:\temp` (created automatically if missing).

Filename sanitisation:
```
strip characters not in [\w\s-]
strip whitespace
replace whitespace runs with "_"
truncate to 80 characters
append ".html"
```

Full path: `c:\temp\{sanitised_view_name}.html`

File is written UTF-8. If the view contains no documentable elements, the script exits with a message and no file is written.

---

## Design Constraints

- **Single source of truth**: all spec logic (abbreviation resolution, relation collection, HTML rendering) lives exclusively in `archimate_spec_v3.py`. `archiDocuViewSingle.py` must never duplicate or reimplement any of that logic.
- **Shared `collect_relation_rows`**: the relations section for each element card uses `v3.collect_relation_rows()` — the same function used by `archimate_spec_v3.py`'s `main()`. This guarantees identical output between single-element and full-view generation.
- **No standalone execution of spec logic**: `archiDocuViewSingle.py` does not call `v3.main()` or produce individual files. It only calls the module-level helper functions.
