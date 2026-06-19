# Specification: archimate_spec_v3.py

## Purpose

Generates a standalone Confluence-styled HTML specification document for a single named element from an ArchiMate XML model file.

```
python3 archimate_spec_v3.py <model.xml> "<element name>"
```

Output: `<sanitised_element_name>_spec_v3.html`

---

## Public API (importable by archiDocuViewSingle.py)

The following functions and constants are imported and used externally:

| Symbol | Kind | Purpose |
|---|---|---|
| `parse_model(xml_path)` | fn | Parse XML, return root element |
| `collect_elements(root)` | fn | Return `{id: element}` dict for all elements |
| `collect_relations(root)` | fn | Return list of all relationship elements |
| `collect_profiles(root)` | fn | Return `{id: name}` dict of top-level `<profile>` elements |
| `get_name(el)` | fn | Return element `name` attribute |
| `get_type(el)` | fn | Return element type without `archimate:` prefix |
| `display_type(t)` | fn | Strip `Application`/`Business`/`Technology` prefix from a type string for display |
| `get_doc(el)` | fn | Return element documentation text |
| `get_profile_name(rel, profiles)` | fn | Return profile name for a relation, or None |
| `access_type_label(rel, profile_name)` | fn | Return access label string |
| `resolve_abbreviations(doc, el_id, relations, elements, profiles)` | fn | Replace `˝˝X˝˝` tokens; return `(processed_text, used_ids)` |
| `render_description_conf(processed_text, indent_base)` | fn | Convert processed text to HTML paragraphs |
| `expand_compositions(body_html, parent_id, parent_type, elements, relations, profiles, depth, visited)` | fn | Replace `__COMPOSE__` placeholders with inline child specs |
| `collect_relation_rows(el_id, el_type, relations, elements, profiles, used_ids)` | fn | Return `(outgoing_rows, incoming_rows)` for Relations section |
| `_relations_html(rows, used_ids, empty_msg, incoming)` | fn | Render relation rows as HTML |
| `CSS` | str | Shared CSS string for embedding in HTML pages |

---

## Model Parsing

### XML namespaces

- ArchiMate namespace: `http://www.archimatetool.com/archimate` (prefix `NS`)
- XSI namespace: `http://www.w3.org/2001/XMLSchema-instance` (prefix `XSI`)
- Abbreviation delimiter: `˝` (U+02DD double acute accent), constant `DELIM`

### `collect_elements(root)`

Iterate all elements in the tree. For every element with an `id` attribute, store `{id: element}`. This includes both model elements and relations.

### `collect_relations(root)`

Return all elements whose `xsi:type` contains the string `"Relationship"`.

### `collect_profiles(root)`

Iterate **direct children** of root only (not full tree). Match tags `profile` or `{NS}profile`. Build `{id: name}` dict.

### `find_element_by_name(root, name)`

Search all elements for `name` attribute match (stripped). If multiple matches:
1. Prefer type `ApplicationFunction`
2. Otherwise take first match

### `get_doc(el)`

Try tag `{NS}documentation` first, then plain `documentation`. Return `.text.strip()` or empty string.

### `get_type(el)`

Return `xsi:type` attribute value with `archimate:` prefix stripped.

### `display_type(t)`

Strip `Application`, `Business`, or `Technology` prefix from a type string before displaying it in HTML. Applied at every render site (`«Type»` badges in `<h1>`, `<h2>`, inline child spec headers, and `«Type»Name` strings in Related context rows). `get_type()` is unchanged — only the display layer is affected.

`_TYPE_PREFIX_RE = re.compile(r'^(Application|Business|Technology)')`

---

## Abbreviation Resolution

### Token format

Description text may contain tokens of the form `˝˝X˝˝` (double-delimited) or `˝X˝` (single-delimited). Always try double form first.

### Scope

Abbreviation resolution applies **only to the description section**. `resolve_abbreviations` is called on the element's own `doc` text. `collect_relation_rows` and `_relations_html` (Related context) do **not** call `resolve_abbreviations` — relation rows use element names and relation docs directly, without token substitution.

### Lookup

Build a dict `{relation_name: relation}` for all relations where **`source == current_element_id` OR `target == current_element_id`** and the relation has a non-empty `name` attribute. Both directions are included because an abbreviation token in the description may reference a relation where the current element is on either side.

Relation `name` attributes in the model include the delimiters (e.g. `name="˝˝0035˝˝"`). For each token match, extract the inner string and look up:
1. `name_to_rel.get(f"˝˝{inner}˝˝")` — double-delimited form
2. `name_to_rel.get(f"˝{inner}˝")` — single-delimited form

If no relation found, return the original token HTML-escaped.

### Rendering by relation type

#### `CompositionRelationship`

- Mark relation as used
- Emit placeholder `__COMPOSE__{target_id}__`
- Applies regardless of target type

#### `AccessRelationship`

Do **not** prefix with `«TargetType»`. Render inline without type annotation.

Determine label via `access_type_label()`:
- If relation has `profiles` attribute → look up profile id → use profile `name`
- Otherwise map `accessType`: absent/`2` = `write`, `1` = `read`, `3` = `read/write`

Determine direction word: `read` or `select` → `from`; all others → `into`

**If label = `select`:**
- Extract `<sellist>...</sellist>` from relation doc; remaining text is the WHERE clause
- Render multi-line block (each line prefixed with `__BLOCK__`):
  ```
  __BLOCK__<p>select</p>
  __BLOCK__<p style="margin-left:40px;">{sellist line}</p>  [one per line]
  __BLOCK__<p>from {object_name}</p>
  __BLOCK__<p style="margin-left:40px;"><gray>where clause</gray></p>
  ```
- Never render "select into" — always `select` then `from` on separate lines

**All other access labels:**
- Render: `{label} {dir_word} {object_name} [gray doc]`
- Embedded newlines in doc → normalize to `<br>` inside gray span

#### All other relation types (TriggeringRelationship, ServingRelationship, etc.)

- Prefix with the relation's keyword, then `«TargetType»TargetName`
- No space between `«TargetType»` and name
- Keyword map:
  - `TriggeringRelationship` → `triggers`
  - `ServingRelationship` → `is used by`
  - `AssociationRelationship` → `associated with`
  - `RealizationRelationship` → `realizes`
  - `InfluenceRelationship` → `influences`
  - `FlowRelationship` → `flows to`
  - Any other → strip `Relationship` suffix, lowercase
- Gray doc appended if present
- For `TriggeringRelationship` and `ServingRelationship`: if the other element (target for outgoing, source for incoming) has a business description, it is appended as `<em><span style="color:...gray...">(biz_desc)</span></em>` — italic and gray
- Mark relation as used

### `used_ids`

Every relation rendered via abbreviation (all types) is added to `used_ids`. These are excluded from the Relations section.

---

## Description Rendering (`render_description_conf`)

Processes text after abbreviation resolution. Input may contain:
- Plain text lines
- Pre-rendered HTML blocks prefixed with `__BLOCK__`
- `__COMPOSE__{id}__` placeholders (passed through unchanged for later expansion)
- `<sql>...</sql>` blocks (pre-processed into bordered monospace blocks before line splitting)

### `<sql>` block pre-processing

Before line splitting, all `<sql>...</sql>` occurrences are replaced with a `__BLOCK__<pre>` element:

- Content is HTML-escaped line by line; empty lines are filtered
- Lines joined with `<br>` (no literal newlines — prevents `_split_blocks` from splitting the block)
- Style: `font-family:monospace; font-size:13px; background:#f8f8f0; padding:8px; border:1px solid #dde0d8; border-radius:4px`
- Regex: `_SQL_RE = re.compile(r'<sql>(.*?)</sql>', re.DOTALL)`

### `__BLOCK__` splitting

A single input line may mix plain text and `__BLOCK__` segments. Split on `__BLOCK__` prefix. Plain part before first `__BLOCK__` is a text segment; remaining parts are block segments.

### Loop/nesting depth

Maintain a `depth` counter (starts at 0). Each line is classified:

| Line pattern | Action |
|---|---|
| Matches open-tag pattern (see below) | Emit `<p class="loop-label">&lt;tag content&gt;</p>`, then `depth += 1` |
| Matches close-tag pattern (see below) | Emit `<p class="loop-end-label">&lt;/tag content&gt;</p>`, then `depth -= 1` |
| Starts with `Description:` (case-insensitive) | Emit `<p><strong>Description: </strong>{rest}</p>` |
| Matches `^technically\s*:?\s*$` (case-insensitive) | Emit `<p class="technically-label"><strong>Technically</strong>:</p>` |
| `__COMPOSE__...` placeholder | Pass through unchanged |
| Pre-rendered block (`kind == 'block'`) | Inject loop indent style if `depth > 0`, then emit as-is |
| Line contains `<span`/`<code`/`<em` | Apply `_VAR_RE` and `_CONST_RE` substitutions to plain-text segments between HTML tags only (avoids double-escaping), then emit as `<p>` |
| Plain text | Emit `<p style="margin-left:{indent}px;">{colorize_text(line)}</p>` |

Indentation per depth level: `indent_base + depth × 40` px. Default `indent_base = 0`.

**Open/close tag detection regexes:**

```python
OPEN_TAG_RE  = re.compile(r'^<(?!/)(?!.*</)(.+)>$')
CLOSE_TAG_RE = re.compile(r'^</(.+)>$')
```

- `OPEN_TAG_RE`: line must start with `<` (not `</`), must **not** contain `</` anywhere (negative lookahead `(?!.*</)` — prevents HTML span lines like `<span ...>text</span>` from matching), and must end with `>`. The greedy `.+` matches to the **last** `>`, so tag content may contain `<>` (not-equal operator) or other `<` characters.
- `CLOSE_TAG_RE`: line must start with `</`, greedy `.+` matches to the last `>`.

---

## Inline Token Colorization (`colorize_text`)

Applied to all plain text in descriptions and relation doc strings. Uses a single combined regex pass (left to right, no double-processing):

| Pattern | Rendering |
|---|---|
| `[register name]`, `[table ...]`, `[view ...]`, `[file ...]`, `[select ...]`, `[definition ...]`, `[folder ...]` | Blue `<code>` via `conf_obj()` |
| `'UPPERCASE_CONSTANT'` (single-quoted, starts uppercase, `[A-Z0-9_():]`) | Magenta via `conf_const()`, kept in single quotes |
| `{variableName}` | Green `<code>` `<em>` wrapped in `{}` via `conf_var()` |
| Other text | `escape()` only |

---

## Composition Expansion (`expand_compositions`)

After `render_description_conf`, replace `__COMPOSE__{id}__` placeholders.

For each placeholder:
- Look up `target_id` in elements dict
- If not found → emit gray placeholder note
- If `target_type != parent_type` → render as plain blue object reference (`conf_obj`)
- If `target_type == parent_type` → render full inline child spec via `render_child_spec()`

### `render_child_spec()`

Recursive. Tracks `visited` set to prevent infinite loops.

For the child element:
1. Resolve abbreviations (same rules as parent)
2. `render_description_conf`
3. `expand_compositions` at `depth + 1`
4. Collect child's Relations section using **only** `AccessRelationship` (not the full `collect_relation_rows` — child inline specs show Access relations only)
5. Wrap in a styled `<div>` with depth-dependent border and background

**Depth colors:**

| Depth | Border | Background |
|---|---|---|
| 0 | `#0055cc` | `#f7f8ff` |
| 1 | `#0077aa` | `#f5fffd` |
| 2 | `#009988` | `#f5fff8` |
| 3+ | `#007744` | `#f8fff5` |

Child spec block structure:
```html
<div style="border-left:3px solid {color}; margin:10px 0; padding:10px 0 10px 16px; background:{bg};">
  <h2>
    <span style="font-size:13px; font-weight:400; color:#888; margin-right:6px;">«{ChildType}»</span>
    {ChildName}
  </h2>
  {body_html}
  <p><strong>Related context</strong></p>
  {out_html}
  {inc_html}
</div>
```

Note: `«Type»` in the `<h2>` is in a separate `<span>` — visual spacing is CSS only, no literal space in the text.

---

## Relations Section (`collect_relation_rows`)

Returns `(outgoing_rows, incoming_rows)`. Each row is `(label, obj_str, doc)` or `(label, obj_str, doc, biz_desc)` when a business description is available. The 4th element is present for:
- `TriggeringRelationship` and `ServingRelationship` (both outgoing and incoming) — `biz_desc` from `extract_business_description(get_doc(other_el))`, where `other_el` is the other side of the relation (target for outgoing, source for incoming)
- `AccessRelationship` with label `select` and target name starting with `[select]` — `biz_desc` is `get_doc(target_el)` (full doc of the target element)

`used_ids` (relations already rendered in description) are excluded from outgoing. Incoming relations are never filtered by `used_ids`.

### `obj_str` format

All relation rows use `«TargetType»TargetName` — **no space** between `»` and the name. `TargetType` is passed through `display_type()` (strips `Application`/`Business`/`Technology` prefix).

**Exception: `AccessRelationship`** — `obj_str` is just the plain name, no type prefix.

### Outgoing row labels by relation type

| Relation type | Label | Condition |
|---|---|---|
| `AccessRelationship` | from `access_type_label()` | always |
| `CompositionRelationship` | `composed of` | always |
| `TriggeringRelationship` | `triggers` | always |
| `ServingRelationship` | `is used by` | always |
| `AssignmentRelationship` | see `_ASSIGNMENT_OUT` table below | keyed by `(source_type, target_type)` |
| `AssignmentRelationship` | raw relation type string | no match in `_ASSIGNMENT_OUT` |
| any other type | raw relation type string | always |

**`_ASSIGNMENT_OUT` — outgoing label by `(source_type, target_type)`:**

| Source type | Target type | Label |
|---|---|---|
| `ApplicationComponent` | `ApplicationService` | `provides` |
| `ApplicationComponent` | `ApplicationInterface` | `publishes` |
| `ApplicationComponent` | `ApplicationEvent` | `generates` |
| `ApplicationComponent` | `ApplicationProcess` | `implements` |
| `ApplicationComponent` | `ApplicationFunction` | `implements` |
| `ApplicationInterface` | `ApplicationService` | `publishes` |

### Incoming row labels by relation type

| Relation type | Label | Condition |
|---|---|---|
| `AccessRelationship` | from `access_type_label()` | always |
| `CompositionRelationship` | `is a part of` | always |
| `TriggeringRelationship` | `is triggered by` | always |
| `ServingRelationship` | `use` | always |
| `AssignmentRelationship` | see `_ASSIGNMENT_IN` table below | keyed by `(source_type, current_el_type)` |
| `AssignmentRelationship` | raw relation type string | no match in `_ASSIGNMENT_IN` |
| any other type | raw relation type string | always |

**`_ASSIGNMENT_IN` — incoming label by `(source_type, target_type)`:**

| Source type | Target type | Label |
|---|---|---|
| `ApplicationComponent` | `ApplicationService` | `is provided by` |
| `ApplicationComponent` | `ApplicationInterface` | `is published on` |
| `ApplicationComponent` | `ApplicationEvent` | `is generated` |
| `ApplicationComponent` | `ApplicationProcess` | `is implemented by` |
| `ApplicationComponent` | `ApplicationFunction` | `is implemented by` |
| `ApplicationInterface` | `ApplicationService` | `is published on` |

---

## Relations HTML Rendering (`_relations_html`)

### Empty state

- Outgoing, no rows, `used_ids` non-empty → `"All relations already described above."`
- Outgoing, no rows, `used_ids` empty → `"No outgoing relations."`
- Incoming, no rows → `"No incoming relations."`

### Grouped labels (bullet list for all)

All relation rows render as a group header + bullet list regardless of label. Relations with the same label are collected under one header (first-occurrence order preserved).

```html
<p>{display label}:</p>
<p style="margin-left:20px;">- {conf_obj(name)}</p>
<p style="margin-left:20px;">- {conf_obj(name)} <em><span style="color:...gray...">(biz_desc)</span></em></p>
```

Business description (`biz_desc`) is appended only when present (non-empty), rendered italic and gray: `<em><span style="{C_GRAY}">(text)</span></em>`.

**Direction word rules for access labels** (`_ACCESS_DIR_LABELS = {"read", "write", "select", "read/write", "update"}`):

| Label | Display |
|---|---|
| `read` | `read from` |
| `select` | `select from` |
| `write` | `write into` |
| `update` | `update into` |
| `read/write` | `read/write into` |

Non-access labels (e.g. `composed of`, `triggers`, `is triggered by`, `use`) display as-is, no direction word appended.

Note: `select` and `update` SQL block formatting (bordered boxes, sellist/updList expansion) applies **only in the description section** (via `resolve_abbreviations`). In Related context they render as plain grouped bullets.

---

## HTML Primitives & Color Constants

| Constant | CSS variable | Fallback | Use |
|---|---|---|---|
| `C_TEXT` | `--ds-text` | `#172b4d` | Relation keywords |
| `C_BLUE` | `--ds-text-accent-blue` | `#0055cc` | Object/element names |
| `C_GREEN` | `--ds-text-accent-green` | `#216e4e` | Variable names `{x}` |
| `C_GRAY` | `--ds-text-accent-gray` | `#44546f` | Descriptions/comments |
| `C_MAGENTA` | `--ds-background-accent-magenta-bolder` | `#ae4787` | Constants `'VALUE'` |

| Function | Output |
|---|---|
| `conf_var(name)` | `{` + green `<em><code>name</code></em>` + `}` |
| `conf_obj(name)` | blue `<code>name</code>` |
| `conf_const(value)` | magenta `<span>value</span>` |
| `conf_keyword(word)` | dark `<span>word</span>` |
| `conf_desc(text)` | gray `<span>text</span>` |

---

## Page Structure (single element)

```html
<h1>
  <span>«{ElementType}»</span>{ElementName}
</h1>

<section>
  {description body}
</section>

<section>
  <p><strong>Related context</strong></p>
  {outgoing html}
  {incoming html}
</section>
```

Note: `«Type»` in `<h1>` is inside a `<span>` — spacing is CSS `margin-right: 8px`. No literal space between `»` and element name in the text node.

---

## Output File

Output directory: `c:\temp` (created automatically if missing).

Filename: `c:\temp\{sanitised_element_name}_spec_v3.html`

Sanitisation: strip characters not in `[\w\s-]`, strip whitespace, replace spaces with `_`, lowercase.
