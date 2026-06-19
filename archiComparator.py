#!/usr/bin/env python3
"""
archiComparator.py
------------------
Compare two ArchiMate files (.archimate or .archimate.xml) and generate
an HTML guide describing what to add, remove, and change in the OLD file
to make it match the NEW file.

Usage:
    python archiComparator.py <old_file> <new_file> [output.html]

No third-party dependencies required — uses the Python standard library only.
lxml is used automatically if installed (handles more malformed files).
"""

import re
import sys
import html
import argparse
import xml.etree.ElementTree as ET
from pathlib import Path

# Use lxml when available: it tolerates malformed XML better (recover=True).
# Fall back to stdlib ET with a pre-cleaning step otherwise.
try:
    from lxml import etree as _lxml
    _HAVE_LXML = True
except ImportError:
    _HAVE_LXML = False


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

XSI_TYPE = "{http://www.w3.org/2001/XMLSchema-instance}type"
SKIP_TYPES = {"ArchimateDiagramModel", "SketchModel", "CanvasModel"}

# XML 1.0 legal character ranges — anything outside is stripped before
# stdlib ET sees the file (stray control chars are the usual parse failure).
_INVALID_XML_CHARS = re.compile(
    r"[^\x09\x0A\x0D\x20-퟿-�\U00010000-\U0010FFFF]"
)


def _clean_xml_bytes(raw: bytes) -> bytes:
    """Strip characters illegal in XML 1.0 so stdlib ET can parse."""
    try:
        text = raw.decode("utf-8", errors="replace")
    except Exception:
        text = raw.decode("latin-1", errors="replace")
    return _INVALID_XML_CHARS.sub("", text).encode("utf-8")


def _parse_tree(filepath: str):
    """Return an element tree root using lxml (preferred) or stdlib ET."""
    with open(filepath, "rb") as f:
        raw = f.read()

    if _HAVE_LXML:
        parser = _lxml.XMLParser(recover=True, encoding="utf-8")
        return _lxml.fromstring(raw, parser)

    # stdlib path — try direct parse first, then with cleaning
    try:
        return ET.fromstring(raw)
    except ET.ParseError:
        pass
    try:
        return ET.fromstring(_clean_xml_bytes(raw))
    except ET.ParseError as exc:
        sys.exit(
            f"ERROR: Cannot parse {filepath}.\n"
            f"  Reason: {exc}\n"
            f"  Tip: install lxml for better recovery:  pip install lxml"
        )


def parse_file(filepath: str):
    """Return (elements, relationships) dicts keyed by element id."""
    root = _parse_tree(filepath)

    elements = {}       # id -> {name, type, doc}
    relationships = {}  # id -> {name, type, source, target, doc}

    for el in root.iter():
        xsi_type = el.get(XSI_TYPE, "")
        if not xsi_type.startswith("archimate:"):
            continue

        el_id = el.get("id", "")
        if not el_id:
            continue

        short_type = xsi_type.replace("archimate:", "")
        name = el.get("name", "")
        doc_el = el.find("documentation")
        doc = doc_el.text if doc_el is not None else None

        if "Relationship" in short_type:
            relationships[el_id] = {
                "name": name,
                "type": short_type,
                "source": el.get("source", ""),
                "target": el.get("target", ""),
                "doc": doc,
            }
        elif short_type not in SKIP_TYPES:
            elements[el_id] = {
                "name": name,
                "type": short_type,
                "doc": doc,
            }

    return elements, relationships


def resolve_name(el_id: str, elements: dict) -> str:
    if el_id in elements:
        return elements[el_id]["name"] or f"[unnamed:{el_id}]"
    return f"[?{el_id}]"


# ---------------------------------------------------------------------------
# Diffing
# ---------------------------------------------------------------------------

def diff_elements(old_els: dict, new_els: dict):
    """Return (only_old, only_new, changed) grouped by element name."""
    old_by_name = {}
    for eid, data in old_els.items():
        old_by_name.setdefault(data["name"], []).append((eid, data))

    new_by_name = {}
    for eid, data in new_els.items():
        new_by_name.setdefault(data["name"], []).append((eid, data))

    only_old = {n: old_by_name[n] for n in old_by_name if n not in new_by_name}
    only_new = {n: new_by_name[n] for n in new_by_name if n not in old_by_name}

    changed = []
    for name in sorted(old_by_name.keys() & new_by_name.keys()):
        o_id, o = old_by_name[name][0]
        n_id, n = new_by_name[name][0]
        type_change = o["type"] != n["type"]
        doc_change  = o["doc"]  != n["doc"]
        if type_change or doc_change:
            changed.append({
                "name":         name,
                "old_type":     o["type"],
                "new_type":     n["type"],
                "old_doc":      o["doc"],
                "new_doc":      n["doc"],
                "type_changed": type_change,
                "doc_changed":  doc_change,
            })

    return only_old, only_new, changed


def build_rel_sig_map(rels: dict, elements: dict):
    """Map (type, src_name, tgt_name) -> list of {name, doc, id}."""
    sig_map = {}
    for rid, r in rels.items():
        src = resolve_name(r["source"], elements)
        tgt = resolve_name(r["target"], elements)
        sig = (r["type"], src, tgt)
        sig_map.setdefault(sig, []).append(
            {"name": r["name"], "doc": r["doc"], "id": rid}
        )
    return sig_map


def diff_relationships(old_rels, new_rels, old_els, new_els):
    """Return (only_old, only_new, changed) keyed/listed by signature."""
    old_sig = build_rel_sig_map(old_rels, old_els)
    new_sig = build_rel_sig_map(new_rels, new_els)

    only_old = {s: old_sig[s] for s in set(old_sig) - set(new_sig)}
    only_new = {s: new_sig[s] for s in set(new_sig) - set(old_sig)}

    changed = []
    for sig in sorted(set(old_sig) & set(new_sig)):
        for oe in old_sig[sig]:
            for ne in new_sig[sig]:
                if oe["name"] != ne["name"] or oe["doc"] != ne["doc"]:
                    changed.append({
                        "sig":      sig,
                        "old_name": oe["name"],
                        "new_name": ne["name"],
                        "old_doc":  oe["doc"],
                        "new_doc":  ne["doc"],
                    })

    return only_old, only_new, changed


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------

CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:Segoe UI,Arial,sans-serif;font-size:13px;line-height:1.5;
     color:#222;background:#f4f4f4;padding:16px}
h1{font-size:18px;margin-bottom:4px;color:#111}
.subtitle{color:#666;font-size:12px;margin-bottom:18px}
.section{margin-bottom:24px;border-radius:6px;overflow:hidden;
         box-shadow:0 1px 4px rgba(0,0,0,.15)}
.section-header{padding:10px 14px;font-weight:bold;font-size:13px;
                cursor:pointer;user-select:none;display:flex;
                justify-content:space-between;align-items:center}
.section-header:hover{filter:brightness(.96)}
.section-body{background:#fff;padding:14px}
.A .section-header{background:#fde8e8;color:#7b1111}
.B .section-header{background:#e8f4e8;color:#145214}
.C .section-header{background:#e8eef8;color:#0c2d70}
.D .section-header{background:#fdf4e8;color:#6b4100}
.subsection{margin-bottom:14px;border:1px solid #e0e0e0;border-radius:4px;overflow:hidden}
.subsection-header{background:#f7f7f7;padding:7px 11px;font-weight:600;
                   font-size:12px;color:#444;cursor:pointer;display:flex;
                   justify-content:space-between}
.subsection-header:hover{background:#eee}
.subsection-body{padding:10px 12px}
.badge{display:inline-block;padding:1px 7px;border-radius:10px;font-size:10px;
       font-weight:bold;margin-left:4px;vertical-align:middle}
.badge-AccessRelationship{background:#d4edff;color:#00457a}
.badge-AssignmentRelationship{background:#ffe0b2;color:#7a3800}
.badge-TriggeringRelationship{background:#f3e5ff;color:#4a007a}
.badge-ServingRelationship{background:#e0ffe0;color:#145214}
.badge-CompositionRelationship{background:#fffde0;color:#6b5800}
.badge-FlowRelationship{background:#f0f0f0;color:#333}
.badge-AssociationRelationship{background:#fce4ec;color:#880e4f}
.badge-RealizationRelationship{background:#e8f4e8;color:#2e7d32}
.badge-InfluenceRelationship{background:#e3f2fd;color:#0d47a1}
.badge-AggregationRelationship{background:#f3e5ff;color:#6a1b9a}
.badge-SpecializationRelationship{background:#fff8e1;color:#f57f17}
.badge-el{background:#e8eaf6;color:#283593}
.row{margin:3px 0;padding:5px 8px;background:#fafafa;border-left:3px solid #ccc;
     border-radius:2px;font-size:12px}
code{font-family:Consolas,monospace;font-size:11px;background:#f0f0f0;
     padding:0 3px;border-radius:2px}
.arrow{color:#888;margin:0 5px}
.diff-table{width:100%;border-collapse:collapse;font-size:12px;margin-top:6px}
.diff-table th{background:#f0f0f0;padding:5px 8px;text-align:left;
               font-weight:600;border:1px solid #ddd}
.diff-table td{padding:5px 8px;vertical-align:top;border:1px solid #ddd}
.old-cell{background:#fff5f5}
.new-cell{background:#f5fff5}
.doc-panels{display:flex;gap:10px;margin-top:6px}
.doc-panel{flex:1;border-radius:4px;overflow:hidden;min-width:0}
.doc-panel-header{padding:4px 8px;font-size:11px;font-weight:bold}
.doc-panel-body{padding:8px;font-family:Consolas,monospace;font-size:11px;
                white-space:pre-wrap;word-break:break-word;
                min-height:30px;max-height:400px;overflow:auto}
.old-panel .doc-panel-header{background:#ffd5d5;color:#7b1111}
.old-panel .doc-panel-body{background:#fff5f5}
.new-panel .doc-panel-header{background:#c3f0c3;color:#145214}
.new-panel .doc-panel-body{background:#f5fff5}
.cnt{font-size:11px;font-weight:normal;opacity:.7;margin-left:6px}
.tog{font-size:11px;opacity:.6;margin-left:8px}
.empty{color:#aaa;font-style:italic;font-size:12px}
"""

JS = "function tog(id){var el=document.getElementById(id);if(el)el.style.display=(el.style.display==='none'?'':'none');}"


def e(s):
    return html.escape(str(s)) if s is not None else ""


def _doc_panels(old_doc, new_doc):
    def panel(label, cls, text):
        body = html.escape(text) if text else "(none)"
        return (
            f'<div class="doc-panel {cls}">'
            f'<div class="doc-panel-header">{label}</div>'
            f'<div class="doc-panel-body">{body}</div>'
            f'</div>'
        )
    return (
        '<div class="doc-panels">'
        + panel("OLD", "old-panel", old_doc)
        + panel("NEW", "new-panel", new_doc)
        + "</div>"
    )


def _badge(rel_type):
    return f'<span class="badge badge-{e(rel_type)}">{e(rel_type)}</span>'


def _el_badge(el_type):
    return f'<span class="badge badge-el">{e(el_type)}</span>'


def _rel_row(sig, name=""):
    rtype, src, tgt = sig
    name_part = f' <code>"{e(name)}"</code>' if name else ""
    return (
        f'<div class="row">{_badge(rtype)}{name_part} '
        f'<strong>{e(src)}</strong>'
        f'<span class="arrow">&#8594;</span>'
        f'<strong>{e(tgt)}</strong></div>\n'
    )


def _subsection(title, count, body_id, body_html, collapsed=False):
    display = "display:none" if collapsed else ""
    cnt = f' <span class="cnt">({count})</span>' if count != "" else ""
    return (
        f'<div class="subsection">'
        f'<div class="subsection-header" onclick="tog(\'{e(body_id)}\')">'
        f'{e(title)}{cnt}<span class="tog">&#9660;</span></div>'
        f'<div id="{e(body_id)}" class="subsection-body" style="{display}">'
        f'{body_html}</div></div>\n'
    )


def _section(letter, subtitle, body_id, body_html):
    labels = {
        "A": "A. REMOVE from OLD",
        "B": "B. ADD to OLD",
        "C": "C. CHANGE in OLD",
        "D": "D. UPDATE documentation",
    }
    header = labels.get(letter, letter)
    return (
        f'<div class="section {e(letter)}">'
        f'<div class="section-header" onclick="tog(\'{e(body_id)}\')">'
        f'{e(header)} <span class="cnt">{e(subtitle)}</span>'
        f'<span class="tog">&#9660;</span></div>'
        f'<div class="section-body" id="{e(body_id)}">'
        f'{body_html}</div></div>\n'
    )


# ---------------------------------------------------------------------------
# Build each section
# ---------------------------------------------------------------------------

def _build_a(only_old_els, only_old_rels):
    # Elements
    el_rows = "".join(
        f'<div class="row">{_el_badge(data["type"])} <strong>{e(name)}</strong></div>\n'
        for name in sorted(only_old_els)
        for _, data in only_old_els[name]
    ) or '<div class="empty">No elements to remove.</div>'

    # Relationships
    rel_rows = "".join(
        _rel_row(sig, entry["name"])
        for sig in sorted(only_old_rels)
        for entry in only_old_rels[sig]
    ) or '<div class="empty">No relationships to remove.</div>'

    return (
        _subsection("Elements to Delete", len(only_old_els), "a_el", el_rows)
        + _subsection("Relationships to Delete", len(only_old_rels), "a_rel", rel_rows, collapsed=True)
    )


def _build_b(only_new_els, only_new_rels):
    el_rows = "".join(
        f'<div class="row">{_el_badge(data["type"])} <strong>{e(name)}</strong></div>\n'
        for name in sorted(only_new_els)
        for _, data in only_new_els[name]
    ) or '<div class="empty">No elements to add.</div>'

    rel_rows = "".join(
        _rel_row(sig, entry["name"])
        for sig in sorted(only_new_rels)
        for entry in only_new_rels[sig]
    ) or '<div class="empty">No relationships to add.</div>'

    return (
        _subsection("Elements to Add", len(only_new_els), "b_el", el_rows)
        + _subsection("Relationships to Add", len(only_new_rels), "b_rel", rel_rows, collapsed=True)
    )


def _build_c(changed_els, changed_rels):
    parts = []

    # Element type changes
    type_rows = "".join(
        f'<tr><td><strong>{e(ch["name"])}</strong></td>'
        f'<td class="old-cell">{_el_badge(ch["old_type"])}</td>'
        f'<td class="new-cell">{_el_badge(ch["new_type"])}</td></tr>\n'
        for ch in changed_els if ch["type_changed"]
    )
    if type_rows:
        table = (
            '<table class="diff-table"><thead>'
            '<tr><th>Element</th><th>OLD type</th><th>NEW type</th></tr>'
            f'</thead><tbody>{type_rows}</tbody></table>'
        )
        count = sum(1 for ch in changed_els if ch["type_changed"])
        parts.append(_subsection("Element Type Changes", count, "c_types", table))

    # Relationship changes
    rel_body = ""
    for ch in changed_rels:
        rtype, src, tgt = ch["sig"]
        old_n = ch["old_name"] or "(empty)"
        new_n = ch["new_name"] or "(empty)"
        name_changed = ch["old_name"] != ch["new_name"]
        doc_changed  = ch["old_doc"]  != ch["new_doc"]

        rel_body += (
            f'<div class="row" style="margin-bottom:8px">'
            f'{_badge(rtype)} <strong>{e(src)}</strong>'
            f'<span class="arrow">&#8594;</span>'
            f'<strong>{e(tgt)}</strong>'
        )
        if name_changed:
            rel_body += (
                f'<br><span style="font-size:11px;color:#666;margin-left:4px">'
                f'Name: <code class="old-cell">{e(old_n)}</code>'
                f' &rarr; <code class="new-cell">{e(new_n)}</code></span>'
            )
        if doc_changed:
            rel_body += _doc_panels(ch["old_doc"], ch["new_doc"])
        rel_body += '</div>\n'

    if not rel_body:
        rel_body = '<div class="empty">No relationship changes.</div>'
    parts.append(_subsection("Relationship Changes", len(changed_rels), "c_rels", rel_body, collapsed=True))

    return "".join(parts) if parts else '<div class="empty">No changes.</div>'


def _build_d(changed_els):
    doc_changes = [ch for ch in changed_els if ch["doc_changed"]]
    if not doc_changes:
        return '<div class="empty">No element documentation changes.</div>'

    parts = []
    for i, ch in enumerate(doc_changes):
        old_has = bool(ch["old_doc"])
        new_has = bool(ch["new_doc"])
        op = "CHANGE" if (old_has and new_has) else ("ADD" if new_has else "REMOVE")
        title = f'{op}: {ch["name"]}  [{ch["new_type"]}]'
        parts.append(_subsection(title, "", f"d_{i}", _doc_panels(ch["old_doc"], ch["new_doc"]), collapsed=True))

    return "".join(parts)


# ---------------------------------------------------------------------------
# Assemble HTML
# ---------------------------------------------------------------------------

def generate_html(old_path, new_path, old_els, new_els, old_rels, new_rels):
    only_old_els, only_new_els, changed_els = diff_elements(old_els, new_els)
    only_old_rels, only_new_rels, changed_rels = diff_relationships(
        old_rels, new_rels, old_els, new_els
    )

    type_changed = [ch for ch in changed_els if ch["type_changed"]]
    doc_changed  = [ch for ch in changed_els if ch["doc_changed"]]

    old_name = Path(old_path).name
    new_name = Path(new_path).name

    parser_note = "lxml" if _HAVE_LXML else "stdlib xml.etree.ElementTree (install lxml for better malformed-file handling)"

    sec_a = _build_a(only_old_els, only_old_rels)
    sec_b = _build_b(only_new_els, only_new_rels)
    sec_c = _build_c(changed_els, changed_rels)
    sec_d = _build_d(doc_changed)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>ArchiMate Comparison: {e(old_name)} vs {e(new_name)}</title>
<style>{CSS}</style>
<script>{JS}</script>
</head>
<body>
<h1>ArchiMate Comparison Guide</h1>
<div class="subtitle">
  <strong>OLD:</strong> {e(old_path)}<br>
  <strong>NEW:</strong> {e(new_path)}<br>
  Apply the changes below to the OLD file so it matches the NEW file.<br>
  <span style="margin-top:4px;display:inline-block">
    OLD: {len(old_els)} elements, {len(old_rels)} relationships &nbsp;|&nbsp;
    NEW: {len(new_els)} elements, {len(new_rels)} relationships &nbsp;|&nbsp;
    Parser: {e(parser_note)}
  </span>
</div>
{_section("A", f"remove {len(only_old_els)} elements, {len(only_old_rels)} relationships", "secA", sec_a)}
{_section("B", f"add {len(only_new_els)} elements, {len(only_new_rels)} relationships", "secB", sec_b)}
{_section("C", f"{len(type_changed)} type changes, {len(changed_rels)} relationship changes", "secC", sec_c)}
{_section("D", f"{len(doc_changed)} element documentation changes", "secD", sec_d)}
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Compare two ArchiMate files and generate an HTML diff guide."
    )
    parser.add_argument("old", help="Path to the OLD ArchiMate file")
    parser.add_argument("new", help="Path to the NEW ArchiMate file")
    parser.add_argument(
        "output", nargs="?", default=None,
        help="Output HTML path (default: archi_comparison.html next to the old file)"
    )
    args = parser.parse_args()

    if not Path(args.old).exists():
        sys.exit(f"ERROR: OLD file not found: {args.old}")
    if not Path(args.new).exists():
        sys.exit(f"ERROR: NEW file not found: {args.new}")

    output_path = args.output or str(Path(args.old).parent / "archi_comparison.html")

    print(f"Parser: {'lxml' if _HAVE_LXML else 'stdlib ET (lxml not installed)'}")

    print(f"Parsing OLD: {args.old}")
    old_els, old_rels = parse_file(args.old)
    print(f"  -> {len(old_els)} elements, {len(old_rels)} relationships")

    print(f"Parsing NEW: {args.new}")
    new_els, new_rels = parse_file(args.new)
    print(f"  -> {len(new_els)} elements, {len(new_rels)} relationships")

    print("Generating HTML...")
    html_content = generate_html(args.old, args.new, old_els, new_els, old_rels, new_rels)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"Done -> {output_path}")


if __name__ == "__main__":
    main()
