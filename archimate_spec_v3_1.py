#!/usr/bin/env python3
"""
archimate_spec_v3.py

Generates a spec v3 HTML document in Confluence output format for an
ApplicationFunction element from an ArchiMate XML model file.

Spec v3 rules:
  - Replace ˝X˝ abbreviations in description with formatted relation lines
  - Track relations rendered in description; omit them from Relations section
  - If all relations rendered in description, show "All relations already described above"
  - CompositionRelationship to same-type element -> embed child spec inline (recursive)

Usage:
    python3 archimate_spec_v3.py <model.xml> "<element name>"

Example:
    python3 archimate_spec_v3.py "orchestration (2).archimate.xml" "Generate trigger request"
"""

import sys
import os
import re
import xml.etree.ElementTree as ET
from html import escape

NS    = "http://www.archimatetool.com/archimate"
XSI   = "http://www.w3.org/2001/XMLSchema-instance"
DELIM = "\u02DD"   # ˝  double acute accent — abbreviation delimiter in ArchiMate


# ---------------------------------------------------------------------------
# Confluence DS color constants
# ---------------------------------------------------------------------------
C_TEXT        = "color:var(--ds-text,#172b4d)"
C_BLUE        = "color:var(--ds-text-accent-blue,#0055cc)"
C_GREEN       = "color:var(--ds-text-accent-green,#216e4e)"
C_GRAY        = "color:var(--ds-text-accent-gray,#44546f)"
C_MAGENTA     = "color:var(--ds-background-accent-magenta-bolder,#ae4787)"
C_SQL_KW      = "color:#003d99;font-size:11px;font-weight:bold;"

# SQL keywords recognised at the start of a line (longest match first)
_SQL_KW_SET = {
    "select distinct", "select", "from", "where",
    "inner join", "left join", "right join", "full outer join", "full join", "cross join", "join",
    "group by", "order by", "having",
    "insert into", "insert", "update", "set", "delete from", "delete",
    "with", "union all", "union",
    "case", "when", "then", "else", "end",
    "on", "into", "values",
}
_SQL_KW_RE = re.compile(
    r'^(' + '|'.join(re.escape(k) for k in sorted(_SQL_KW_SET, key=len, reverse=True)) + r')(\s|$)',
    re.IGNORECASE
)


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def parse_model(xml_path):
    return ET.parse(xml_path).getroot()


def collect_elements(root):
    elements = {}
    for el in root.iter():
        eid = el.get("id")
        if eid:
            elements[eid] = el
    return elements


def get_name(el):
    return el.get("name", "") if el is not None else ""


def get_type(el):
    return el.get(f"{{{XSI}}}type", "").replace("archimate:", "")


_TYPE_PREFIX_RE = re.compile(r'^(Application|Business|Technology)')

def display_type(t):
    """Strip Application/Business/Technology prefix from ArchiMate type names for display."""
    return _TYPE_PREFIX_RE.sub('', t)


def get_doc(el):
    for tag in (f"{{{NS}}}documentation", "documentation"):
        doc = el.find(tag)
        if doc is not None and doc.text:
            return doc.text.strip()
    return ""


def collect_relations(root):
    return [el for el in root.iter() if "Relationship" in el.get(f"{{{XSI}}}type", "")]


def collect_profiles(root):
    profiles = {}
    for el in root:
        if el.tag in ("profile", f"{{{NS}}}profile"):
            pid = el.get("id")
            if pid:
                profiles[pid] = el.get("name", "")
    return profiles


def get_profile_name(rel, profiles):
    for pid in (rel.get("profiles") or "").strip().split():
        if pid in profiles:
            return profiles[pid]
    return None


def find_element_by_name(root, name):
    candidates = [el for el in root.iter() if el.get("name", "").strip() == name.strip()]
    for el in candidates:
        if get_type(el) == "ApplicationFunction":
            return el
    return candidates[0] if candidates else None


# ---------------------------------------------------------------------------
# Relation labelling
# ---------------------------------------------------------------------------

def access_type_label(rel, profile_name):
    """
    profile present   -> profile name
    accessType absent -> write
    accessType 1      -> read
    accessType 2      -> write
    accessType 3      -> read/write
    """
    if profile_name:
        return profile_name
    return {None: "write", "1": "read", "2": "write", "3": "read/write"}.get(
        rel.get("accessType"), "write"
    )


def direction_word(label, direction="out"):
    """'from' for reads, selects, and incoming; 'into' for writes outgoing."""
    if label.lower() in ("read", "select") or direction == "in":
        return "from"
    return "into"


# ---------------------------------------------------------------------------
# sellist extraction
# ---------------------------------------------------------------------------

_SELLIST_RE = re.compile(r'<sellist>(.*?)</sellist>', re.DOTALL)


def extract_sellist(doc_text):
    """
    Extract content from <sellist>...</sellist> tags in relation documentation.
    Returns (sellist_content_or_None, doc_without_sellist_tags).
    """
    m = _SELLIST_RE.search(doc_text)
    if not m:
        return None, doc_text
    sellist = m.group(1).strip()
    # Remove the sellist block from doc, leave the rest (the WHERE clause etc.)
    rest = _SELLIST_RE.sub('', doc_text).strip()
    return sellist, rest


_UPDLIST_RE = re.compile(r'<updList>(.*?)</updList>', re.DOTALL)

_SQL_RE = re.compile(r'<sql>(.*?)</sql>', re.DOTALL)


def extract_updlist(doc_text):
    """
    Extract content from <updList>...</updList> tags in relation documentation.
    Returns (updlist_content_or_None, doc_without_updlist_tags).
    """
    m = _UPDLIST_RE.search(doc_text)
    if not m:
        return None, doc_text
    updlist = m.group(1).strip()
    rest = _UPDLIST_RE.sub('', doc_text).strip()
    return updlist, rest


# ---------------------------------------------------------------------------
# Confluence HTML primitives
# ---------------------------------------------------------------------------

def conf_var(name):
    """Render a {variableName} with green+italic+code styling."""
    inner = f'<span style="{C_GREEN};font-style: italic;"><code>{escape(name)}</code></span>'
    return '{' + inner + '}'


def conf_obj(name):
    """Render a linked object name with blue+code styling."""
    return f'<span style="{C_BLUE}"><code>{escape(name)}</code></span>'


def conf_const(value):
    """Render a constant/status value with magenta styling."""
    return f'<span style="{C_MAGENTA}">{escape(value)}</span>'


def conf_keyword(word):
    """Render a relation direction keyword (read from / write into etc.) in dark text."""
    return f'<span style="{C_TEXT}">{escape(word)}</span>'


def conf_desc(text):
    """Render description/comment text in gray."""
    return f'<span style="{C_GRAY}">{escape(text)}</span>'


def sql_kw(word):
    """Render an explicit SQL keyword in dark-blue bold 11px."""
    return f'<span style="{C_SQL_KW}">{escape(word)}</span>'


def colorize_sql_line(text):
    """
    Colorize a single SQL line: if it starts with a recognised SQL keyword,
    render the keyword in dark-blue bold, then apply colorize_text() to the rest.
    Otherwise apply colorize_text() to the whole line.
    Called at render time so colorize_text is defined below — forward ref resolved
    because this is only invoked after module load.
    """
    text = text.strip()
    m = _SQL_KW_RE.match(text)
    if m:
        kw   = m.group(1)
        rest = text[len(kw):]
        return f'{sql_kw(kw)}{colorize_text(rest)}'
    return colorize_text(text)


def _sql_div(inner_html):
    """Wrap SQL <p> lines in the shared monospace bordered div."""
    return (
        f'<div style="border:1px solid #dde0d8;border-radius:4px;'
        f'background:#f8f8f0;padding:8px;margin:4px 0;'
        f'font-family:SFMono-Regular,Consolas,&quot;Liberation Mono&quot;,Menlo,monospace;'
        f'font-size:12px;{C_GRAY}">{inner_html}</div>'
    )


# ---------------------------------------------------------------------------
# Smart text renderer
# Converts plain description text into Confluence-styled HTML,
# applying color rules to variables {x}, constants 'X', object refs [x],
# and relation keywords.
# ---------------------------------------------------------------------------

# Patterns for inline token colorization inside description text
_VAR_RE    = re.compile(r'\{([^}]+)\}')
_CONST_RE  = re.compile(r"'([A-Z][A-Z0-9_()]*)'")
_OBJ_RE    = re.compile(r'(\[(?:register|table|view|file|select|definition|folder)[^\]]*\](?:\s+\S+)*)')


def colorize_text(text):
    """
    Apply Confluence color styling to inline tokens in a plain text string.
    Order matters: process objects first, then constants, then variables.
    Returns an HTML string.
    """
    # We'll build up the result token by token using split positions
    # to avoid double-escaping. We process left to right finding matches.

    result = []
    pos = 0

    # Merge all patterns with their handler
    all_patterns = [
        (_OBJ_RE,   lambda m: conf_obj(m.group(1))),
        (_CONST_RE, lambda m: f"'{conf_const(m.group(1))}'"),
        (_VAR_RE,   lambda m: '{' + f'<em><span style="{C_GREEN}"><code>{escape(m.group(1))}</code></span></em>' + '}'),
    ]

    # Build combined pattern with named groups
    combined = re.compile(
        r'(\[(?:register|table|view|file|select|definition|folder)[^\]]*\](?:\s+\S+)*)'
        r"|'([A-Z][A-Z0-9_():]*)'"
        r'|\{([^}]+)\}'
    )

    for m in combined.finditer(text):
        # append plain text before this match
        result.append(escape(text[pos:m.start()]))
        pos = m.end()

        obj_match   = m.group(1)
        const_match = m.group(2)
        var_match   = m.group(3)

        if obj_match:
            result.append(conf_obj(obj_match))
        elif const_match:
            result.append(f"'{conf_const(const_match)}'")
        elif var_match:
            result.append(
                '{' + f'<span style="{C_GREEN};font-style: italic;"><code>{escape(var_match)}</code></span>' + '}'
            )

    result.append(escape(text[pos:]))
    return "".join(result)


# ---------------------------------------------------------------------------
# Relation line renderer (Confluence format)
# ---------------------------------------------------------------------------

def render_relation_line_conf(label, obj_name, doc, indent=0):
    """Render a single relation line in Confluence format."""
    dir_word  = direction_word(label)
    margin    = f' style="margin-left:{indent}px;"' if indent else ""
    label_out = conf_keyword(f"{label} {dir_word}")
    obj_out   = conf_obj(obj_name)
    desc_out  = f' <span style="{C_GRAY}">{colorize_text(doc)}</span>' if doc else ""
    return f'<p{margin}>{label_out} {obj_out}{desc_out}</p>'


# ---------------------------------------------------------------------------
# Business description extractor
# ---------------------------------------------------------------------------

_BIZ_DESC_RE = re.compile(
    r'^\s*description\s*:\s*(.+?)(?=technically\s*:?)',
    re.IGNORECASE | re.DOTALL
)

def extract_business_description(doc):
    """
    Return text between 'Description:' and 'Technically:' in an element's doc.
    Returns empty string if the pattern is not found.
    """
    if not doc:
        return ""
    m = _BIZ_DESC_RE.match(doc)
    return m.group(1).strip() if m else ""


# ---------------------------------------------------------------------------
# Description abbreviation resolution
# Returns (processed_text, dict abbrev_inner -> rel)
# ---------------------------------------------------------------------------

def resolve_abbreviations(description, source_id, relations, elements, profiles):
    """
    Replace ˝X˝ tokens with formatted Confluence relation lines.
    Returns (new_html_string, set_of_used_relation_ids).
    """
    used_ids = set()
    d = re.escape(DELIM)
    # match double ˝˝X˝˝ OR single ˝X˝ — double must come first
    pattern = re.compile(f'{d}{d}([^{d}]+){d}{d}|{d}([^{d}]+){d}')

    # build lookup: exact relation name -> rel
    # include both outgoing (source==id) and incoming (target==id) relations
    name_to_rel = {}
    for rel in relations:
        if rel.get("source") != source_id and rel.get("target") != source_id:
            continue
        name = (rel.get("name") or "").strip()
        if name:
            name_to_rel[name] = rel

    def replace(match):
        inner = (match.group(1) if match.group(1) is not None else
                 match.group(2) if match.group(2) is not None else "").strip()
        # relation names in the model include the delimiters (e.g. name="˝˝0035˝˝")
        rel = name_to_rel.get(f"{DELIM}{DELIM}{inner}{DELIM}{DELIM}")
        if rel is None:
            rel = name_to_rel.get(f"{DELIM}{inner}{DELIM}")
        if rel is None:
            return escape(match.group(0))

        rel_type = get_type(rel)

        # CompositionRelationship to same-type element -> placeholder for child expansion
        # (handled separately in render_element_spec)
        if rel_type == "CompositionRelationship":
            target_el = elements.get(rel.get("target"))
            if target_el is not None:
                used_ids.add(rel.get("id"))
                return f"__COMPOSE__{rel.get('target')}__"
            return escape(match.group(0))

        # AccessRelationship -> render inline
        if rel_type == "AccessRelationship":
            used_ids.add(rel.get("id"))
            target_el   = elements.get(rel.get("target"))
            target_name = get_name(target_el)
            target_type = get_type(target_el) if target_el is not None else ""
            raw_doc     = get_doc(rel)
            label       = access_type_label(rel, get_profile_name(rel, profiles))
            dir_word    = direction_word(label)

            if label.lower() == "select":
                if target_name.lower().startswith("[select]"):
                    target_doc = get_doc(target_el) if target_el is not None else ""
                    lines = []
                    if target_doc:
                        sql_html = "<br>".join(
                            escape(l) for l in target_doc.splitlines() if l.strip()
                        )
                        lines.append(
                            f'__BLOCK__<pre style="font-family:monospace;font-size:13px;'
                            f'margin:4px 0;background:#f8f8f0;padding:8px;'
                            f'border:1px solid #dde0d8;border-radius:4px;">'
                            f'{sql_html}</pre>'
                        )
                    if raw_doc:
                        for rd in raw_doc.splitlines():
                            rd = rd.strip()
                            if rd:
                                lines.append(f'__BLOCK__<p>{colorize_text(rd)}</p>')
                    return "\n".join(lines)
                sellist, rest_doc = extract_sellist(raw_doc)
                obj_out = conf_obj(target_name)
                lines = []
                inner = f'<p>{sql_kw("select")}</p>'
                if sellist:
                    for sl in sellist.splitlines():
                        sl = sl.strip()
                        if sl:
                            inner += f'<p>{colorize_sql_line(sl)}</p>'
                inner += f'<p>{sql_kw("from")} {obj_out}</p>'
                if rest_doc:
                    for rd in rest_doc.splitlines():
                        rd = rd.strip()
                        if rd:
                            inner += f'<p>{colorize_sql_line(rd)}</p>'
                lines.append(f'__BLOCK__{_sql_div(inner)}')
                return "\n".join(lines)
            elif label.lower() == "update":
                updlist, rest_doc = extract_updlist(raw_doc)
                obj_out   = conf_obj(target_name)
                lines = []
                inner  = f'<p>{sql_kw("update")} {obj_out}</p>'
                if updlist:
                    for ul in updlist.splitlines():
                        ul = ul.strip()
                        if ul:
                            inner += f'<p>{colorize_sql_line(ul)}</p>'
                if rest_doc:
                    for rd in rest_doc.splitlines():
                        rd = rd.strip()
                        if rd:
                            inner += f'<p>{colorize_sql_line(rd)}</p>'
                lines.append(f'__BLOCK__{_sql_div(inner)}')
                return "\n".join(lines)
            else:
                label_out = conf_keyword(f"{label} {dir_word}")
                obj_out   = conf_obj(target_name)
                if raw_doc:
                    doc_lines = [l.strip() for l in re.split(r'\r?\n', raw_doc) if l.strip()]
                    doc_html  = "<br>".join(colorize_text(l) for l in doc_lines)
                    desc_out  = f' <span style="{C_GRAY}">{doc_html}</span>'
                else:
                    desc_out = ""
                return f'{label_out} {obj_out}{desc_out}'

        # Other relation types (TriggeringRelationship, ServingRelationship etc.)
        # -> render as: <rel_keyword> «OtherType» OtherName <gray doc>
        used_ids.add(rel.get("id"))
        incoming = rel.get("target") == source_id
        other_el   = elements.get(rel.get("source") if incoming else rel.get("target"))
        other_name = get_name(other_el)
        other_type = get_type(other_el) if other_el is not None else ""
        _OUT = {
            "TriggeringRelationship":  "triggers",
            "ServingRelationship":     "is used by",
            "AssociationRelationship": "associated with",
            "RealizationRelationship": "realizes",
            "InfluenceRelationship":   "influences",
            "FlowRelationship":        "flows to",
        }
        _IN = {
            "TriggeringRelationship":  "is triggered by",
            "ServingRelationship":     "use",
            "AssociationRelationship": "associated with",
            "RealizationRelationship": "is realized by",
            "InfluenceRelationship":   "is influenced by",
            "FlowRelationship":        "flows from",
        }
        kw_map   = _IN if incoming else _OUT
        rel_keyword = kw_map.get(rel_type, rel_type.replace("Relationship", "").lower())
        doc      = get_doc(rel)
        obj_out  = conf_obj(f"«{display_type(other_type)}»{other_name}")
        desc_out = f' <span style="{C_GRAY}">{colorize_text(doc)}</span>' if doc else ""
        biz_out  = ""
        if rel_type in ("TriggeringRelationship", "ServingRelationship") and other_el is not None:
            biz_desc = extract_business_description(get_doc(other_el))
            if biz_desc:
                biz_out = f' <span style="{C_GRAY};font-style: italic;">({colorize_text(biz_desc)})</span>'
        return f'{conf_keyword(rel_keyword)} {obj_out}{desc_out}{biz_out}'

    new_text = pattern.sub(replace, description)
    return new_text, used_ids


# ---------------------------------------------------------------------------
# Description block renderer (Confluence format)
# ---------------------------------------------------------------------------

def _inject_style(m, extra_style):
    """Inject extra_style into a <p> or <div> tag matched by regex."""
    tag = m.group(1)
    existing = (m.group(2) or "").strip()
    if 'style=' in existing:
        # append to existing style="..."
        new_attr = re.sub(r'style="([^"]*)"', lambda s: f'style="{s.group(1)};{extra_style}"', existing)
        return f'<{tag} {new_attr}>'
    elif existing:
        return f'<{tag} {existing} style="{extra_style}">'
    else:
        return f'<{tag} style="{extra_style}">'


OPEN_TAG_RE  = re.compile(r'^<(?!/)(?!.*</)(.+)>$')
CLOSE_TAG_RE = re.compile(r'^</(.+)>$')

# Sentinel prefix for pre-rendered HTML paragraphs produced by select renderer
_BLOCK_PREFIX = "__BLOCK__"


def _split_blocks(text):
    """
    Split text into a list of segments.  Each segment is either:
      ('text',  str)   — plain text to be processed normally
      ('block', str)   — pre-rendered HTML paragraph (stripped of __BLOCK__ prefix)
    A single input line may contain both — e.g.
        "{foo} := __BLOCK__<p>select</p>"
    splits into ('text', '{foo} :=') and ('block', '<p>select</p>').
    """
    segments = []
    for raw_line in re.split(r'\r?\n', text):
        if _BLOCK_PREFIX in raw_line:
            parts_of_line = raw_line.split(_BLOCK_PREFIX)
            first = parts_of_line[0].strip()
            if first:
                segments.append(('text', first))
            for block_part in parts_of_line[1:]:
                # block_part is already a complete <p>...</p>
                segments.append(('block', block_part))
        else:
            stripped = raw_line.strip()
            if stripped:
                segments.append(('text', stripped))
    return segments


def render_description_conf(processed_text, indent_base=0):
    """
    Convert processed description text (after abbreviation resolution) to
    Confluence-styled HTML paragraphs and loop blocks.
    indent_base: base left-margin in px for loop body indentation.
    """
    # pre-process <sql>...</sql> blocks into bordered monospace __BLOCK__ elements
    def _sql_to_block(m):
        lines_html = "".join(
            f'<p>{colorize_sql_line(l)}</p>'
            for l in m.group(1).strip().splitlines() if l.strip()
        )
        return f'__BLOCK__{_sql_div(lines_html)}'
    processed_text = _SQL_RE.sub(_sql_to_block, processed_text)

    parts = []
    depth = 0   # current loop nesting depth

    for kind, line in _split_blocks(processed_text):

        if kind == 'block':
            # pre-rendered HTML block — inject loop indent if needed
            if depth > 0:
                indent_style = f'margin-left:{indent_base + depth * 20}px;'
                line = re.sub(
                    r'<(p|div)(\s[^>]*)?>',
                    lambda m: _inject_style(m, indent_style),
                    line, count=1
                )
            parts.append(line)
            continue

        # --- plain text segment ---
        if not line:
            continue

        # skip "Description:" prefix line
        if line.lower().startswith("description:"):
            text = line[len("description:"):].strip()
            if text:
                parts.append(f'<p><strong>Description: </strong>{colorize_text(text)}</p>')
            else:
                parts.append(f'<p><strong>Description: </strong></p>')
            continue

        # skip "technically:" label line
        if re.match(r'^technically\s*:?\s*$', line, re.IGNORECASE):
            parts.append(f'<p><strong>Technically</strong>:</p>')
            continue

        m_open  = OPEN_TAG_RE.match(line)
        m_close = CLOSE_TAG_RE.match(line)

        if m_open:
            depth += 1
            tag_content = m_open.group(1)
            colored = colorize_text(tag_content)
            parts.append(f'<p><span style="font-size: 14px; font-style: italic; color: #999; margin-top: 4px;">&lt;{colored}&gt;</span></p>')

        elif m_close:
            tag_content = m_close.group(1)
            colored = colorize_text(tag_content)
            parts.append(f'<p><span style="font-size: 14px; font-style: italic; color: #999; margin-top: 4px;">&lt;/{colored}&gt;</span></p>')
            depth -= 1

        elif line.startswith("__COMPOSE__") and line.endswith("__"):
            # placeholder — will be replaced by caller with child spec HTML
            parts.append(line)

        else:
            margin = indent_base + depth * 20
            margin_style = f' style="margin-left:{margin}px;"' if margin else ""
            # if line already contains HTML tags (from resolved abbreviations), don't re-colorize
            # the whole line (would double-escape existing HTML). Instead apply variable {x}
            # and constant 'X' colorization only to plain-text segments between HTML tags.
            if '<span' in line or '<code' in line:
                chunks = []
                pos = 0
                for tm in re.finditer(r'<[^>]+>', line):
                    plain = line[pos:tm.start()]
                    if plain:
                        plain = _VAR_RE.sub(lambda m: conf_var(m.group(1)), plain)
                        plain = _CONST_RE.sub(lambda m: f"'{conf_const(m.group(1))}'", plain)
                    chunks.append(plain)
                    chunks.append(tm.group(0))
                    pos = tm.end()
                plain = line[pos:]
                if plain:
                    plain = _VAR_RE.sub(lambda m: conf_var(m.group(1)), plain)
                    plain = _CONST_RE.sub(lambda m: f"'{conf_const(m.group(1))}'", plain)
                chunks.append(plain)
                parts.append(f'<p{margin_style}>{"".join(chunks)}</p>')
            else:
                parts.append(f'<p{margin_style}>{colorize_text(line)}</p>')

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Child spec renderer (inline, nested)
# ---------------------------------------------------------------------------

def render_child_spec(child_el, elements, relations, profiles, depth=0,
                      visited=None):
    """
    Render inline child spec for a composed same-type element.
    depth controls border-left color intensity / nesting level.
    visited prevents infinite recursion.
    """
    if visited is None:
        visited = set()

    child_id   = child_el.get("id")
    child_type = get_type(child_el)
    child_name = get_name(child_el)

    if child_id in visited:
        return f'<p style="color:#888;font-style:italic;">[recursive reference: {escape(child_name)}]</p>'
    visited = visited | {child_id}

    child_doc = get_doc(child_el)

    # resolve abbreviations for child
    processed, used_ids = resolve_abbreviations(
        child_doc, child_id, relations, elements, profiles
    )

    # expand __COMPOSE__ placeholders recursively
    body_html = render_description_conf(processed)
    body_html = expand_compositions(
        body_html, child_id, child_type, elements, relations, profiles,
        depth + 1, visited
    )

    # child outgoing access relations not used in description
    outgoing_rows = []
    for rel in relations:
        if get_type(rel) != "AccessRelationship": continue
        if rel.get("source") != child_id:         continue
        if rel.get("id") in used_ids:             continue
        target_el  = elements.get(rel.get("target"))
        label      = access_type_label(rel, get_profile_name(rel, profiles))
        obj_name   = get_name(target_el)
        doc        = get_doc(rel)
        if label.lower() == "select" and obj_name.lower().startswith("[select]"):
            target_doc = get_doc(target_el) if target_el is not None else ""
            outgoing_rows.append((label, obj_name, doc, target_doc))
        else:
            outgoing_rows.append((label, obj_name, doc))

    incoming_rows = []
    for rel in relations:
        if get_type(rel) != "AccessRelationship": continue
        if rel.get("target") != child_id:         continue
        source_el = elements.get(rel.get("source"))
        label     = access_type_label(rel, get_profile_name(rel, profiles))
        obj_name  = get_name(source_el)
        doc       = get_doc(rel)
        incoming_rows.append((label, obj_name, doc))

    # build relations section
    out_html = _relations_html(outgoing_rows, used_ids, "No outgoing relations.")
    inc_html = _relations_html(incoming_rows, set(), "No incoming relations.", incoming=True)

    # choose border color by depth
    border_colors = ["#0055cc", "#0077aa", "#009988", "#007744"]
    border_color  = border_colors[min(depth, len(border_colors) - 1)]
    bg_colors     = ["#f7f8ff", "#f5fffd", "#f5fff8", "#f8fff5"]
    bg_color      = bg_colors[min(depth, len(bg_colors) - 1)]

    return f"""<div style="border-left:3px solid {border_color};margin:10px 0;padding:10px 0 10px 16px;background:{bg_color};">
<h2><span style="font-size:13px;font-weight:400;color:#888;margin-right:6px;">«{escape(display_type(child_type))}»</span>{escape(child_name)}</h2>
{body_html}
<p style="margin-top:0.75rem;"><strong>Related context</strong></p>
{out_html}
{inc_html}
</div>"""


_ACCESS_DIR_LABELS = {"read", "write", "select", "read/write", "update"}


def _relations_html(rows, used_ids, empty_msg, incoming=False):
    _note_style = 'font-size: 14px; color: #888; font-style: italic;'
    if not rows and used_ids and not incoming:
        return f'<p style="{_note_style}">All relations already described above.</p>'
    if not rows:
        return f'<p style="{_note_style}">{empty_msg}</p>'

    from collections import OrderedDict
    groups = OrderedDict()
    for row in rows:
        label, obj_name = row[0], row[1]
        biz_desc = row[3] if len(row) > 3 else ""
        groups.setdefault(label, []).append((obj_name, biz_desc))

    lines = []
    for label, items in groups.items():
        if label.lower() in _ACCESS_DIR_LABELS:
            if label.lower() in ("write", "update", "read/write"):
                dw = "into"
            else:
                dw = "from"
            display = f"{label} {dw}"
        else:
            display = label
        lines.append(f'<p>{conf_keyword(display)}:</p>')
        for nm, biz in items:
            biz_part = (f' <span style="{C_GRAY};font-style: italic;">({colorize_text(biz)})</span>'
                        if biz else "")
            lines.append(f'<p style="margin-left:20px;">- {conf_obj(nm)}{biz_part}</p>')
    return "\n".join(lines)


def expand_compositions(body_html, parent_id, parent_type,
                        elements, relations, profiles, depth, visited):
    """
    Replace __COMPOSE__{id}__ placeholders in body_html with rendered child specs.
    """
    placeholder_re = re.compile(r'__COMPOSE__([^_]+)__')

    def replace_placeholder(m):
        target_id  = m.group(1)
        target_el  = elements.get(target_id)
        if target_el is None:
            return f'<p style="color:#888;">[unknown element: {target_id}]</p>'
        target_type = get_type(target_el)
        if target_type != parent_type:
            # different type — just render as object reference
            return conf_obj(get_name(target_el))
        return render_child_spec(
            target_el, elements, relations, profiles, depth, visited
        )

    return placeholder_re.sub(replace_placeholder, body_html)


# ---------------------------------------------------------------------------
# Full document renderer
# ---------------------------------------------------------------------------

CSS = ""  # v4: no embedded stylesheet — all styling is inline


def build_full_html(el_name, el_type, body_html,
                    outgoing_rows, used_ids, incoming_rows):
    out_html = _relations_html(outgoing_rows, used_ids, "No outgoing relations.")
    inc_html = _relations_html(incoming_rows, set(), "No incoming relations.", incoming=True)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{escape(el_name)} \u2014 Spec v4</title>

</head>
<body>

<h1><span style="color:var(--ds-chart-gray-bold,#8590a2);">«{escape(display_type(el_type))}»</span>{escape(el_name)}</h1>
{escape(el_name)} \u2014 Spec v4
<section>
{body_html}
</section>

<section>
  <p style="margin-top:1.5rem;"><strong>Related context</strong></p>
  {out_html}
  {inc_html}
</section>

</body>
</html>"""


# ---------------------------------------------------------------------------
# AssignmentRelationship label maps  (source must be ApplicationComponent)
# ---------------------------------------------------------------------------

# Keys: (source_type, target_type)
_ASSIGNMENT_OUT = {
    ("ApplicationComponent", "ApplicationService"):   "provides",
    ("ApplicationComponent", "ApplicationInterface"): "publishes",
    ("ApplicationComponent", "ApplicationEvent"):     "generates",
    ("ApplicationComponent", "ApplicationProcess"):   "implements",
    ("ApplicationComponent", "ApplicationFunction"):  "implements",
    ("ApplicationInterface", "ApplicationService"):   "publishes",
}

# Keys: (source_type, target_type)  — looked up as (src_type, el_type) for incoming
_ASSIGNMENT_IN = {
    ("ApplicationComponent", "ApplicationService"):   "is provided by",
    ("ApplicationComponent", "ApplicationInterface"): "is published on",
    ("ApplicationComponent", "ApplicationEvent"):     "is generated",
    ("ApplicationComponent", "ApplicationProcess"):   "is implemented by",
    ("ApplicationComponent", "ApplicationFunction"):  "is implemented by",
    ("ApplicationInterface", "ApplicationService"):   "is published on",
}

# ---------------------------------------------------------------------------
# Shared relation row collector  (used by main() and archiDocuViewSingle.py)
# ---------------------------------------------------------------------------

def collect_relation_rows(el_id, el_type, relations, elements, profiles, used_ids):
    """
    Returns (outgoing_rows, incoming_rows) — each a list of (label, obj_str, doc).
    used_ids: set of relation ids already rendered in the description (excluded here).
    """
    outgoing_rows = []
    for rel in relations:
        rel_type = get_type(rel)
        if rel.get("source") != el_id: continue
        if rel.get("id") in used_ids:  continue

        if rel_type == "AccessRelationship":
            target_el   = elements.get(rel.get("target"))
            label       = access_type_label(rel, get_profile_name(rel, profiles))
            target_name = get_name(target_el)
            rel_doc     = get_doc(rel)
            if label.lower() == "select" and target_name.lower().startswith("[select]"):
                outgoing_rows.append((label, target_name, rel_doc,
                                      get_doc(target_el) if target_el is not None else ""))
            else:
                outgoing_rows.append((label, target_name, rel_doc))

        elif rel_type == "CompositionRelationship":
            target_el = elements.get(rel.get("target"))
            tgt_type  = get_type(target_el) if target_el is not None else ""
            outgoing_rows.append(("composed of",
                                  f"«{display_type(tgt_type)}»{get_name(target_el)}", ""))

        elif rel_type == "TriggeringRelationship":
            target_el = elements.get(rel.get("target"))
            tgt_type  = get_type(target_el) if target_el is not None else ""
            biz       = extract_business_description(get_doc(target_el)) if target_el is not None else ""
            outgoing_rows.append(("triggers",
                                  f"«{display_type(tgt_type)}»{get_name(target_el)}", "", biz))

        elif rel_type == "ServingRelationship":
            target_el = elements.get(rel.get("target"))
            tgt_type  = get_type(target_el) if target_el is not None else ""
            biz       = extract_business_description(get_doc(target_el)) if target_el is not None else ""
            outgoing_rows.append(("is used by",
                                  f"«{display_type(tgt_type)}»{get_name(target_el)}", get_doc(rel), biz))

        elif rel_type == "AssignmentRelationship":
            target_el = elements.get(rel.get("target"))
            tgt_type  = get_type(target_el) if target_el is not None else ""
            label = _ASSIGNMENT_OUT.get((el_type, tgt_type))
            if label:
                outgoing_rows.append((label,
                                      f"«{display_type(tgt_type)}»{get_name(target_el)}", ""))
            else:
                outgoing_rows.append((rel_type,
                                      f"«{display_type(tgt_type)}»{get_name(target_el)}", get_doc(rel)))

        else:
            target_el = elements.get(rel.get("target"))
            tgt_type  = get_type(target_el) if target_el is not None else ""
            outgoing_rows.append((rel_type,
                                  f"«{display_type(tgt_type)}»{get_name(target_el)}", get_doc(rel)))

    incoming_rows = []
    for rel in relations:
        rel_type = get_type(rel)
        if rel.get("target") != el_id: continue

        if rel_type == "AccessRelationship":
            source_el = elements.get(rel.get("source"))
            label     = access_type_label(rel, get_profile_name(rel, profiles))
            incoming_rows.append((label, get_name(source_el), get_doc(rel)))

        elif rel_type == "CompositionRelationship":
            source_el = elements.get(rel.get("source"))
            src_type  = get_type(source_el) if source_el is not None else ""
            incoming_rows.append(("is a part of",
                                  f"«{display_type(src_type)}»{get_name(source_el)}", ""))

        elif rel_type == "TriggeringRelationship":
            source_el = elements.get(rel.get("source"))
            src_type  = get_type(source_el) if source_el is not None else ""
            biz       = extract_business_description(get_doc(source_el)) if source_el is not None else ""
            incoming_rows.append(("is triggered by",
                                  f"«{display_type(src_type)}»{get_name(source_el)}", "", biz))

        elif rel_type == "ServingRelationship":
            source_el = elements.get(rel.get("source"))
            src_type  = get_type(source_el) if source_el is not None else ""
            biz       = extract_business_description(get_doc(source_el)) if source_el is not None else ""
            incoming_rows.append(("use",
                                  f"«{display_type(src_type)}»{get_name(source_el)}", get_doc(rel), biz))

        elif rel_type == "AssignmentRelationship":
            source_el = elements.get(rel.get("source"))
            src_type  = get_type(source_el) if source_el is not None else ""
            label = _ASSIGNMENT_IN.get((src_type, el_type))
            if label:
                incoming_rows.append((label,
                                      f"«{display_type(src_type)}»{get_name(source_el)}", ""))
            else:
                incoming_rows.append((rel_type,
                                      f"«{display_type(src_type)}»{get_name(source_el)}", get_doc(rel)))

        else:
            source_el = elements.get(rel.get("source"))
            src_type  = get_type(source_el) if source_el is not None else ""
            incoming_rows.append((rel_type,
                                  f"«{display_type(src_type)}»{get_name(source_el)}", get_doc(rel)))

    return outgoing_rows, incoming_rows


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 3:
        print('Usage: python3 archimate_spec_v3.py <model.xml> "<element name>"')
        sys.exit(1)

    xml_path, element_name = sys.argv[1], sys.argv[2]

    root      = parse_model(xml_path)
    elements  = collect_elements(root)
    relations = collect_relations(root)
    profiles  = collect_profiles(root)

    el = find_element_by_name(root, element_name)
    if el is None:
        print(f"Element '{element_name}' not found in model.")
        sys.exit(1)

    el_id   = el.get("id")
    el_type = get_type(el)
    doc     = get_doc(el)

    # resolve abbreviations
    processed, used_ids = resolve_abbreviations(
        doc, el_id, relations, elements, profiles
    )

    # render description
    body_html = render_description_conf(processed)

    # expand inline child specs
    body_html = expand_compositions(
        body_html, el_id, el_type, elements, relations, profiles,
        depth=0, visited={el_id}
    )

    outgoing_rows, incoming_rows = collect_relation_rows(
        el_id, el_type, relations, elements, profiles, used_ids
    )

    html = build_full_html(
        element_name, el_type, body_html,
        outgoing_rows, used_ids, incoming_rows
    )

    safe_name = re.sub(r"[^\w\s-]", "", element_name).strip().replace(" ", "_").lower()
    out_dir   = r"c:\temp"
    os.makedirs(out_dir, exist_ok=True)
    out_path  = os.path.join(out_dir, f"{safe_name}_spec_v4.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Spec v3 written to: {out_path}")


if __name__ == "__main__":
    main()
