#!/usr/bin/env python3
"""
archiDocuViewSingle.py

Generates a single HTML file documenting every element found in a named
ArchiMate view.  Each element's spec is produced by archimate_spec_v3.py
(imported as a module) and combined into one page with a sticky sidebar TOC.

Usage:
    python3 archiDocuViewSingle.py <model.xml> "<view name>"

Example:
    python3 archiDocuViewSingle.py "orchestration (2).archimate.xml" "[AppProcess]Processing triggering candidates queue"

Output:
    <sanitised_view_name>.html
"""

import sys
import os
import re
import importlib.util
import pathlib
from html import escape

# ---------------------------------------------------------------------------
# Import spec helpers from archimate_spec_v3.py (must be in same directory)
# ---------------------------------------------------------------------------

_SPEC_SCRIPT = pathlib.Path(__file__).parent / "archimate_spec_v3.py"
if not _SPEC_SCRIPT.exists():
    sys.exit(f"ERROR: archimate_spec_v3.py not found next to this script ({_SPEC_SCRIPT})")

_spec = importlib.util.spec_from_file_location("archimate_spec_v3", _SPEC_SCRIPT)
v3    = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(v3)

# ---------------------------------------------------------------------------
# Constants (reuse skip list from archiDocuView)
# ---------------------------------------------------------------------------

XSI = "http://www.w3.org/2001/XMLSchema-instance"

SKIP_TYPES = {
    "DiagramObject", "DiagramModelNote", "DiagramModelGroup",
    "DiagramModelConnection", "DiagramModelReference",
    "SketchModelSticky", "SketchModelActor",
    "Connection",
}

# ---------------------------------------------------------------------------
# View & element collection  (identical logic to archiDocuView.py)
# ---------------------------------------------------------------------------

def find_view(root, view_name):
    for el in root.iter():
        xtype = el.get(f"{{{XSI}}}type", "")
        if xtype in (
            "archimate:ArchimateDiagramModel",
            "archimate:SketchModel",
            "archimate:CanvasModel",
        ):
            if el.get("name", "").strip() == view_name.strip():
                return el
    return None


def _resolve_archimate_element(node, elements):
    ref = node.get("archimateElement") or node.get("model")
    if ref:
        return elements.get(ref)
    xtype = node.get(f"{{{XSI}}}type", "").replace("archimate:", "")
    if xtype and xtype not in SKIP_TYPES and "Relationship" not in xtype:
        nid = node.get("id")
        if nid and nid in elements:
            return elements[nid]
    return None


def collect_view_elements(view_node, elements):
    seen   = set()
    result = []

    def walk(node):
        el = _resolve_archimate_element(node, elements)
        if el is not None:
            eid   = el.get("id")
            etype = el.get(f"{{{XSI}}}type", "").replace("archimate:", "")
            if eid and eid not in seen and etype not in SKIP_TYPES and "Relationship" not in etype:
                name = el.get("name", "").strip()
                seen.add(eid)
                if not name:
                    return
                result.append(el)
        for child in node:
            walk(child)

    for child in view_node:
        walk(child)

    return result

# ---------------------------------------------------------------------------
# Per-element spec body renderer  (reuses v3 helpers, returns inner HTML only)
# ---------------------------------------------------------------------------

def render_element_body(el, elements, relations, profiles):
    """
    Returns (el_name, el_type, body_html) where body_html is the spec content
    without the outer <html>/<head>/<body> wrapper — ready to embed in a page.
    """
    el_id   = el.get("id")
    el_type = v3.get_type(el)
    el_name = v3.get_name(el)
    doc     = v3.get_doc(el)

    processed, used_ids = v3.resolve_abbreviations(
        doc, el_id, relations, elements, profiles
    )

    body_html = v3.render_description_conf(processed)
    body_html = v3.expand_compositions(
        body_html, el_id, el_type, elements, relations, profiles,
        depth=0, visited={el_id}
    )

    outgoing_rows, incoming_rows = v3.collect_relation_rows(
        el_id, el_type, relations, elements, profiles, used_ids
    )

    out_html = v3._relations_html(outgoing_rows, used_ids, "No outgoing relations.")
    inc_html = v3._relations_html(incoming_rows, set(), "No incoming relations.", incoming=True)

    return el_name, el_type, body_html, out_html, inc_html

# ---------------------------------------------------------------------------
# Slug helper
# ---------------------------------------------------------------------------

def slugify(name):
    s = re.sub(r"[^\w\s\-]", "", name).strip()
    s = re.sub(r"\s+", "-", s)
    return s[:60].lower()

# ---------------------------------------------------------------------------
# Combined single-file HTML builder
# ---------------------------------------------------------------------------

PAGE_CSS = v3.CSS + """
    /* ---- single-file layout ---- */
    body {
      max-width: 960px;
      padding: 2rem;
    }
    #page-header {
      margin-bottom: 2rem;
      padding-bottom: 1rem;
      border-bottom: 2px solid #e8e8e4;
    }
    #page-header h1 {
      font-size: 20px;
      margin: 0 0 0.25rem;
    }
    #page-header .count {
      font-size: 13px;
      color: #888;
    }
    .el-card {
      margin-bottom: 3rem;
      padding-bottom: 2rem;
      border-bottom: 1px solid #e8e8e4;
    }
    .el-card:last-child { border-bottom: none; }

    .toc-list { margin: 0.5rem 0 0 1.5rem; }
    .toc-list li { margin-bottom: 0.2rem; }
    .toc-list a { color: #0055cc; text-decoration: none; }
    .toc-list a:hover { text-decoration: underline; }
    .toc-type { font-size: 12px; font-weight: 400; color: #888; margin-right: 5px; }
    .el-card h2 {
      font-size: 19px;
      font-weight: 500;
      margin-bottom: 0.15rem;
    }
    .el-card h2 span {
      font-size: 13px;
      font-weight: 400;
      color: #888;
      margin-right: 6px;
    }
    .el-card section { margin-bottom: 1.25rem; }
"""

def build_single_html(view_name, entries):
    """
    entries: list of (el_name, el_type, slug, body_html, out_html, inc_html)
    """

    # --- table of contents ---
    toc_items = []
    for el_name, el_type, slug, *_ in entries:
        toc_items.append(
            f'<li><a href="#{slug}">'
            f'<span class="toc-type">«{escape(v3.display_type(el_type))}»</span>'
            f'{escape(el_name)}</a></li>'
        )
    toc_html = "\n".join(toc_items)

    # --- element cards ---
    cards = []
    for el_name, el_type, slug, body_html, out_html, inc_html in entries:
        cards.append(f"""
<div class="el-card" id="{slug}">
  <h2><span>«{escape(v3.display_type(el_type))}»</span>{escape(el_name)}</h2>

  <section>
{body_html}
  </section>

  <section>
    <p style="margin-top:1rem;"><strong>Related context</strong></p>
    {out_html}
    {inc_html}
  </section>
</div>""")

    cards_html = "\n".join(cards)
    count      = len(entries)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{escape(view_name)} \u2014 Documentation</title>
  <style>{PAGE_CSS}</style>
</head>
<body>

<header id="page-header">
  <h1>{escape(view_name)}</h1>
  <p class="count">{count} element{"s" if count != 1 else ""}</p>
</header>

<div class="el-card" id="toc">
  <h2>Contents</h2>
  <ol class="toc-list">
{toc_html}
  </ol>
</div>

{cards_html}

</body>
</html>"""

# ---------------------------------------------------------------------------
# Filename sanitiser
# ---------------------------------------------------------------------------

def safe_filename(name, ext=".html"):
    s = re.sub(r"[^\w\s\-]", "", name).strip()
    s = re.sub(r"\s+", "_", s)
    return s[:80] + ext

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 3:
        print('Usage: python3 archiDocuViewSingle.py <model.xml> "<view name>"')
        sys.exit(1)

    xml_path  = sys.argv[1]
    view_name = sys.argv[2]

    print(f"Parsing {xml_path} ...")
    root      = v3.parse_model(xml_path)
    elements  = v3.collect_elements(root)
    relations = v3.collect_relations(root)
    profiles  = v3.collect_profiles(root)

    view_node = find_view(root, view_name)
    if view_node is None:
        print(f"ERROR: view '{view_name}' not found in model.")
        sys.exit(1)

    view_elements = collect_view_elements(view_node, elements)
    if not view_elements:
        print(f"View '{view_name}' contains no documentable elements.")
        sys.exit(0)

    print(f"View '{view_name}': {len(view_elements)} elements found.")

    # track used slugs to deduplicate
    used_slugs = {}
    entries    = []

    for el in view_elements:
        el_name, el_type, body_html, out_html, inc_html = render_element_body(
            el, elements, relations, profiles
        )

        base_slug = slugify(el_name)
        slug      = base_slug
        counter   = 1
        while slug in used_slugs:
            slug = f"{base_slug}-{counter}"
            counter += 1
        used_slugs[slug] = True

        entries.append((el_name, el_type, slug, body_html, out_html, inc_html))
        print(f"  [{el_type}] {el_name}")

    html    = build_single_html(view_name, entries)
    out_dir = r"c:\temp"
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, safe_filename(view_name))

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\nDone.  Output: {out_path}")


if __name__ == "__main__":
    main()
