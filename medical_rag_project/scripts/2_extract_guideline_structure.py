"""
Step 2: Extract recommendations from guideline markdown

Input:  data/guideline.md
Output: data/rag_chunks.json

Extracts only recommendation statements (Class I/IIa/IIb/III + Level of Evidence A/B/C).
Works for any ESC/ACC/ESH-style guideline that uses the standard table format:
  | recommendation text | Class | Level |

Each output chunk has:
  id, text, metadata (type, class, evidence, disease, topic, section, source)
"""

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from pipeline_common import DATA_ROOT  # noqa: E402

DATA_DIR = Path(os.getenv("RAG_DATA_DIR", str(DATA_ROOT / "data")))
INPUT_MD = DATA_DIR / "guideline.md"
OUTPUT_JSON = DATA_DIR / "rag_chunks.json"
PROJECT_TITLE = os.getenv("RAG_PROJECT_TITLE", DATA_DIR.name)
GUIDELINE_YEAR = os.getenv("RAG_GUIDELINE_YEAR", "")

# ---------------------------------------------------------------------------
# Disease keyword detection
# Extend this dict for document-specific diseases.
# ---------------------------------------------------------------------------
DISEASE_PATTERNS: dict[str, list[str]] = {
    "HCM":  ["hypertrophic cardiomyopathy", "hcm"],
    "DCM":  ["dilated cardiomyopathy", "dcm"],
    "ARVC": ["arrhythmogenic cardiomyopathy", "arvc", "arrhythmogenic right ventricular"],
    "RCM":  ["restrictive cardiomyopathy", "rcm"],
    "CAD":  ["coronary artery disease", "chronic coronary syndrome", "ccs",
             "stable angina", "obstructive cad", "atherosclerotic"],
    "HF":   ["heart failure", "hfref", "hfpef", "hfmref",
             "left ventricular dysfunction", "reduced ejection fraction"],
    "AF":   ["atrial fibrillation", "atrial flutter"],
    "VT":   ["ventricular tachycardia", "ventricular fibrillation", "sudden cardiac death"],
    "VHD":  ["valvular heart disease", "aortic stenosis", "mitral regurgitation",
             "aortic regurgitation", "mitral stenosis"],
    "ACS":  ["acute coronary syndrome", "acs", "myocardial infarction", "nstemi", "stemi"],
}

# ---------------------------------------------------------------------------
# Topic keyword detection
# ---------------------------------------------------------------------------
TOPIC_KEYWORDS: dict[str, list[str]] = {
    "diagnosis": [
        "diagnos", "imaging", "echocardiograph", "mri", "cmr", "ct", "ccta",
        "criteria", "angiograph", "biomarker", "troponin", "bnp",
        "pre-test", "likelihood", "classification", "definition",
    ],
    "treatment": [
        "treatment", "therapy", "management", "medication", "drug", "pharmacol",
        "intervention", "icd", "ablation", "transplant", "implant", "device",
        "pci", "cabg", "revascular", "statin", "antiplatelet", "anticoagul",
        "beta-blocker", "nitrate", "diuretic", "ace inhibitor", "arb", "surgery",
    ],
    "risk_stratification": [
        "risk", "stratif", "sudden death", "scd", "prognosis", "score",
        "mace", "adverse event", "high risk", "low risk", "mortality", "predictor",
    ],
    "screening": [
        "screen", "family", "genetic", "relative", "cascade", "hereditary",
        "mutation", "genotype",
    ],
    "lifestyle": [
        "lifestyle", "exercise", "physical activity", "diet", "smoking",
        "weight", "obesity", "alcohol", "rehabilitation",
    ],
    "follow_up": [
        "follow-up", "follow up", "monitoring", "surveillance",
        "re-evaluation", "serial", "long-term",
    ],
}

# Sections to skip — they are summaries/boilerplate, not the authoritative source
SKIP_SECTION_RE = re.compile(
    r"what is new|what('s| is) changed|new recommendations|revised recommendations"
    r"|what to do|what not to do"
    r"|conflict of interest|author|copyright|acknowledgement|abbreviation"
    r"|table of contents|list of table|list of figure|preamble"
    r"|document reviewer|permission|disclaimer|references?"
    r"|funding|data availability|supplement",
    re.IGNORECASE,
)

# Trailing citation numbers: digits/commas/ranges directly after a sentence-ending period or semicolon
# e.g. "...obstructive CAD.289–293"  or  "...revascularization.49,195,331–333"  or  "...therapy;49,195"
# A table footnote marker can sit between the period and the numbers, which is
# how the PDF renders "...to reduce the risk of HFH or death.^c 43,254–257".
CITATION_SUFFIX_RE = re.compile(r"[.;][a-z]?(\d[\d,\s\u2013\-]*)$")

# Prose fallback: a paragraph is only a recommendation if it is phrased like
# one — the ESC wording that maps onto Class I/IIa/IIb/III.
RECOMMENDATION_PHRASE_RE = re.compile(
    r"\b(?:is|are)\s+(?:not\s+)?recommended\b"
    r"|\b(?:should|may)\s+(?:not\s+)?be\s+considered\b"
    r"|\bis\s+indicated\b|\bis\s+not\s+indicated\b",
    re.IGNORECASE,
)

# Bracket-style citations left by the PDF conversion, e.g. "...HFH.[302][–][304 ]"
BRACKET_CITATION_RE = re.compile(r"(?:\[\s*[\d\u2013,\-]+\s*\])+")

# Prose fallback: blocks containing "Class I/II..." + Level of Evidence
REC_CLASS_RE = re.compile(r"(Class\s+(?:I{1,3}|IIa|IIb|III|IV))\b", re.IGNORECASE)
REC_EVIDENCE_RE = re.compile(
    r"Level of [Ee]vidence[:\s]+(A|B1|B2|B|C)\b|LOE[:\s]+(A|B1|B2|B|C)\b"
    r"|Evidence[:\s]+(A|B1|B2|B|C)\b",
)


# A single table cell holding a class of recommendation, e.g. "**IIa**"
CLASS_CELL_RE = re.compile(r"^\**\s*(I{1,3}|IIa|IIb|IV)\s*\**$", re.IGNORECASE)
# A single table cell holding a level of evidence, optionally with a footnote
# letter glued on by the PDF conversion, e.g. "**A**" or "**Cd**".
# Since 2026, ESC grades therapy and prevention as A/B1/B2/C (Table 2) and
# diagnostic tests as A/B/C (Table 3), so B1 and B2 are levels in their own
# right — not a B with a footnote marker.
EV_CELL_RE = re.compile(r"^\**\s*(A|B1|B2|B|C)\s*[a-z]?\s*\**$", re.IGNORECASE)

# Markdown table separator row, e.g. "|---|---|---|"
SEPARATOR_CELL_RE = re.compile(r"^:?-{2,}:?$")

# Table captions we key recommendations to, e.g.
# "**Recommendation Table 5 — Recommendations for ...**"
TABLE_CAPTION_RE = re.compile(r"^\s*#*\s*\**\s*((?:Recommendation\s+)?Table\s+\d+\b.*)$")

# Summary tables that restate recommendations printed in full elsewhere in the
# document — extracting them yields duplicates, so they are skipped.
SKIP_TABLE_RE = re.compile(
    r"new concepts|new recommendations|revised recommendations"
    r"|classes? of recommendations?|levels? of evidence",
    re.IGNORECASE,
)

# Page furniture that interrupts a table where the PDF broke across pages,
# e.g. "**20** ESC Guidelines" or a bare "_Continued_"
PAGE_NOISE_RE = re.compile(
    r"^\**\d*\**\s*(ESC|ACC|AHA|ESH)\b.*|^\**\d+\**$|^_?Continued_?$",
    re.IGNORECASE,
)
CONTINUED_CELL_RE = re.compile(r"^_?\s*Continued\s*_?$", re.IGNORECASE)

# A cell ends a recommendation when it closes a sentence, optionally followed by
# the citation numbers that the PDF glues onto the final period.
SENTENCE_END_RE = re.compile(r"[.;](?:[a-z]?\d[\d,\s\u2013\-]*)?$")
# ...unless that period belongs to an abbreviation rather than a sentence.
ABBREV_END_RE = re.compile(r"(?:\be\.g|\bi\.e|\bvs|\bapprox|\bno|\bcf|\s[a-z])\.$", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def detect_disease(text: str) -> str:
    text_lower = text.lower()
    for code, keywords in DISEASE_PATTERNS.items():
        if any(kw in text_lower for kw in keywords):
            return code
    return "general"


def _pick_disease(table_title: str, rec_text: str, section_disease: str) -> str:
    """Prefer the disease named by the recommendation itself over the section's.

    Section bodies mention many diseases in passing, which mislabels a
    recommendation; the table caption and the recommendation text are far more
    specific. Falls back to the section-level guess.
    """
    own = detect_disease(f"{table_title} {rec_text}")
    return own if own != "general" else section_disease


def detect_topic(section_title: str, rec_text: str = "") -> str:
    for source in (section_title.lower(), rec_text.lower()):
        for topic, keywords in TOPIC_KEYWORDS.items():
            if any(kw in source for kw in keywords):
                return topic
    return "general"


def parse_reference_section(markdown: str) -> dict[int, str]:
    """Parse the References section and return {ref_number: ref_text}.

    Handles multi-line reference entries. Cleans up markdown formatting.
    """
    # Matches "## References", "## **25. References**", "## 25 References", etc.
    ref_heading = re.search(
        r"^#{1,4}\s+\**\s*(?:\d+\.?\s*)?References?\s*\**\s*$",
        markdown, re.MULTILINE | re.IGNORECASE,
    )
    if not ref_heading:
        return {}

    ref_body = markdown[ref_heading.end():]
    # Stop at the next heading (if any)
    next_heading = re.search(r"^#{1,4}\s+", ref_body, re.MULTILINE)
    if next_heading:
        ref_body = ref_body[: next_heading.start()]

    # Split on lines that start a new numbered entry ("\n" + digit + ".")
    entries = re.split(r"\n(?=\d+\.\s)", ref_body)
    refs: dict[int, str] = {}
    for entry in entries:
        m = re.match(r"^(\d+)\.\s+(.+)", entry.strip(), re.DOTALL)
        if m:
            ref_num = int(m.group(1))
            ref_text = re.sub(r"[*_`]", "", m.group(2))   # strip markdown
            ref_text = re.sub(r"\s+", " ", ref_text).strip()
            refs[ref_num] = ref_text
    return refs


def _parse_ref_ids(cit_str: str) -> list[int]:
    """Parse a citation string like '49,195,308–313' into a list of ints."""
    ids: list[int] = []
    for part in re.split(r"[,\s]+", cit_str.strip()):
        part = part.strip()
        if not part:
            continue
        range_m = re.match(r"(\d+)\s*[\u2013\-]\s*(\d+)", part)
        if range_m:
            start, end = int(range_m.group(1)), int(range_m.group(2))
            ids.extend(range(start, min(end + 1, start + 21)))  # cap at 20 per range
        elif part.isdigit():
            ids.append(int(part))
    return ids


def _ref_entries(ref_ids: list[int], ref_dict: dict[int, str]) -> list[dict]:
    """Resolve reference numbers to {"id", "text"} entries, skipping unknown ids."""
    return [{"id": i, "text": ref_dict[i]} for i in ref_ids if i in ref_dict]


SUP_RE = re.compile(r"<sup>(.*?)</sup>", re.DOTALL)
_SUPERSCRIPT_DIGITS = str.maketrans("0123456789+-", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻")


def _strip_sup_tags(text: str) -> tuple[str, list[int]]:
    """Remove <sup>...</sup> markup that pymupdf4llm leaves in for citations.

    ESC/ACC guidelines mark citations with superscript numbers, e.g.
    "...ineligible for surgery.<sup>264,265,268,269</sup>" or inline as
    "diseases,<sup>5</sup> chronic coronary syndrome,<sup>6</sup>". These
    aren't caught by CITATION_SUFFIX_RE (which only matches bare trailing
    digits) and were leaking into recommendation text verbatim.

    - A superscript that's a digit list (citation numbers) is cut out and
      its numbers are returned as extra ref ids.
    - A superscript preceded by a letter (e.g. "cm<sup>2</sup>") is a unit
      exponent — kept, rendered as a real Unicode superscript.
    - Anything else (footnote letters like <sup>d</sup>) references a table
      footnote that isn't captured elsewhere, so it's just dropped.
    """
    extra_ref_ids: list[int] = []

    def repl(m: re.Match) -> str:
        start = m.start()
        j = start - 1
        while j >= 0 and text[j] == "*":  # skip markdown bold markers
            j -= 1
        preceding = text[j] if j >= 0 else ""
        content = re.sub(r"[*\s]", "", m.group(1))

        if preceding.isalpha():
            if content and all(ch in "0123456789+-" for ch in content):
                return content.translate(_SUPERSCRIPT_DIGITS)
            return content

        if content and re.fullmatch(r"[\d,–\-]+", content):
            extra_ref_ids.extend(_parse_ref_ids(content))
            return ""

        return ""  # footnote-letter marker — not resolvable, drop it

    cleaned = SUP_RE.sub(repl, text)
    return cleaned, extra_ref_ids


def _split_cells(row: str) -> list[str]:
    """Split a markdown table row into cells, preserving column positions.

    Only the single outer pipe on each side is dropped — stripping every pipe
    would collapse the empty leading/trailing columns that these guideline
    tables use, and with them the alignment we need to locate the class column.
    """
    row = row.strip()
    if row.startswith("|"):
        row = row[1:]
    if row.endswith("|"):
        row = row[:-1]
    return row.split("|")


def _clean_cell(cell: str) -> str:
    """Normalize a table cell to plain text (drop <br> and bold markers)."""
    cell = re.sub(r"<br\s*/?>", " ", cell, flags=re.IGNORECASE)
    cell = cell.replace("**", "")
    return re.sub(r"\s+", " ", cell).strip()


def _is_separator_row(cells: list[str]) -> bool:
    filled = [c.strip() for c in cells if c.strip()]
    return bool(filled) and all(SEPARATOR_CELL_RE.match(c) for c in filled)


def _ends_recommendation(text: str) -> bool:
    text = text.strip()
    if len(text) < 25:
        return False
    return bool(SENTENCE_END_RE.search(text)) and not ABBREV_END_RE.search(text)


def _table_blocks(lines: list[str]) -> list[dict]:
    """Group consecutive table rows into blocks, rejoining page-break splits.

    pymupdf4llm emits one markdown row per printed line, so a table that runs
    over a page break arrives as two blocks with the page header in between.
    Those are stitched back together, otherwise a recommendation straddling the
    break is lost.
    """
    blocks: list[dict] = []
    i = 0
    while i < len(lines):
        if lines[i].lstrip().startswith("|"):
            start = i
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                i += 1
            block = {"start": start, "end": i, "rows": lines[start:i]}
            if blocks:
                gap = lines[blocks[-1]["end"]:start]
                if all(not g.strip() or PAGE_NOISE_RE.match(g.strip()) for g in gap):
                    blocks[-1]["rows"] += block["rows"]
                    blocks[-1]["end"] = i
                    continue
            blocks.append(block)
        else:
            i += 1
    return blocks


def _table_caption(lines: list[str], block: dict, prev_end: int) -> str:
    """Find the "Table N ..." caption printed above a table block."""
    for j in range(block["start"] - 1, prev_end - 1, -1):
        line = lines[j].strip()
        if not line or line.startswith("|"):
            continue
        m = TABLE_CAPTION_RE.match(line)
        if m:
            return re.sub(r"[*_`]", "", m.group(1)).strip()
    return ""


def _class_columns(rows: list[str]) -> list[int]:
    """Return the column indices that hold a class of recommendation.

    Comparison tables (old vs new recommendations) repeat the
    text/class/level triplet across the row, so there can be more than one.
    """
    counts: dict[int, int] = {}
    for row in rows:
        cells = _split_cells(row)
        for j in range(1, len(cells) - 1):
            if CLASS_CELL_RE.match(cells[j].strip()) and EV_CELL_RE.match(cells[j + 1].strip()):
                counts[j] = counts.get(j, 0) + 1
    return sorted(counts)


def extract_table_recommendations(rows: list[str]) -> list[tuple[str, str, str]]:
    """Extract (text, class, evidence) triples from one markdown table block.

    A recommendation is rarely one row: the PDF wraps its text over several
    rows and prints the class/level cells beside whichever line happens to sit
    in the middle. Rows are therefore accumulated until the text closes a
    sentence, with the class/level picked up from whichever row carries them.
    """
    out: list[tuple[str, str, str]] = []

    for cls_col in _class_columns(rows):
        txt_col, ev_col = cls_col - 1, cls_col + 1
        parts: list[str] = []
        cls = ev = ""

        def flush() -> None:
            nonlocal parts, cls, ev
            text = " ".join(parts).strip()
            if text and cls and ev:
                out.append((text, cls, ev))
            parts, cls, ev = [], "", ""

        for row in rows:
            cells = _split_cells(row)
            if _is_separator_row(cells):
                continue
            raw_text = cells[txt_col] if txt_col < len(cells) else ""
            raw_cls = cells[cls_col].strip() if cls_col < len(cells) else ""
            raw_ev = cells[ev_col].strip() if ev_col < len(cells) else ""
            has_class = bool(CLASS_CELL_RE.match(raw_cls) and EV_CELL_RE.match(raw_ev))

            # A cell can hold the tail of one recommendation and the start of
            # the next, separated by <br>, so each printed line is fed in
            # separately and checked for a sentence end of its own. The first
            # line is often a bold column header or sub-heading
            # ("**Recommendations**") glued in front of a real one — that is a
            # boundary, but only for the line it occupies.
            pieces = []
            for raw_piece in re.split(r"<br\s*/?>", raw_text, flags=re.IGNORECASE):
                if raw_piece.strip().startswith("**"):
                    pieces.append(None)  # boundary
                    continue
                piece = _clean_cell(raw_piece)
                if piece and not CONTINUED_CELL_RE.match(piece):
                    pieces.append(piece)
            if not any(pieces) and not has_class:
                if pieces:
                    flush()
                continue

            # A second class cell while one is already pending means the
            # sentence-end heuristic missed a boundary; close the previous one.
            if has_class and cls:
                flush()

            for piece in pieces:
                if piece is None:
                    flush()
                    continue
                parts.append(piece)
                if cls and _ends_recommendation(" ".join(parts)):
                    flush()
            if has_class and not cls:
                cls, ev = raw_cls.replace("*", "").strip(), raw_ev.replace("*", "").strip()
            if cls and _ends_recommendation(" ".join(parts)):
                flush()

        flush()

    return out


def _strip_bracket_citations(text: str) -> tuple[str, list[int]]:
    """Remove "[302][–][304 ]"-style citation runs and return their numbers.

    A single bracket directly after a letter is a unit exponent ("1.73 m[2]")
    rather than a citation, so it is left alone.
    """
    ref_ids: list[int] = []

    def repl(m: re.Match) -> str:
        j = m.start() - 1
        while j >= 0 and text[j] in "* ":
            j -= 1
        if j >= 0 and text[j].isalpha():
            return m.group(0)  # unit exponent, e.g. "m[2]"
        ref_ids.extend(_parse_ref_ids(re.sub(r"[\[\]\s]", "", m.group(0))))
        return ""

    return BRACKET_CITATION_RE.sub(repl, text), ref_ids


def normalize_evidence(raw: str) -> str:
    """Return the canonical level of evidence from a table cell.

    Keeps the ESC 2026 sublevels B1/B2 intact while dropping any footnote
    letter the PDF conversion glued on ("Cd" -> "C").
    """
    m = EV_CELL_RE.match(raw.strip())
    if not m:
        return "NR"
    return m.group(1).upper()


def normalize_class(raw: str) -> str:
    raw = re.sub(r"Class\s+", "", raw, flags=re.IGNORECASE).strip().upper()
    raw = re.sub(r"^IIA$", "IIa", raw)
    raw = re.sub(r"^IIB$", "IIb", raw)
    result = f"Class {raw}"
    # "Class II" without a/b suffix is not a valid ESC class — flag for manual review
    if result == "Class II":
        return "Class II?"
    return result


def split_into_sections(markdown: str) -> list[tuple[str, str]]:
    parts = re.split(r"^(#{1,3} .+)$", markdown, flags=re.MULTILINE)
    sections: list[tuple[str, str]] = []
    if parts[0].strip():
        sections.append(("Introduction", parts[0]))
    i = 1
    while i < len(parts) - 1:
        heading = re.sub(r"[*_`]", "", parts[i]).strip("#").strip()
        sections.append((heading, parts[i + 1]))
        i += 2
    return sections


def extract_recommendations(
    sections: list[tuple[str, str]],
    ref_dict: dict[int, str] | None = None,
    guideline: str = "",
    year: str = "",
) -> list[dict]:
    if ref_dict is None:
        ref_dict = {}
    recs = []
    counter = 0
    seen: set[str] = set()

    for heading, body in sections:
        if SKIP_SECTION_RE.search(heading):
            continue

        disease = detect_disease(heading + " " + body)

        # --- Strategy 1: ESC/ACC recommendation tables ---
        lines = body.split("\n")
        blocks = _table_blocks(lines)
        prev_end = 0
        # A caption promoted to a markdown heading is not part of the body, so
        # seed the title from the section heading when it is one.
        table_title = heading if TABLE_CAPTION_RE.match(heading) else ""
        table_recs = 0
        for block in blocks:
            caption = _table_caption(lines, block, prev_end)
            prev_end = block["end"]
            if caption:
                table_title = caption
            if table_title and SKIP_TABLE_RE.search(table_title):
                continue

            for raw_text, raw_class, raw_ev in extract_table_recommendations(block["rows"]):
                # Strip <sup>citation</sup> markup left by the PDF conversion
                # before the trailing-suffix check below, which only matches
                # bare digits.
                raw_text, sup_ref_ids = _strip_sup_tags(raw_text)
                raw_text = re.sub(r"\s+", " ", raw_text).strip()

                if len(raw_text) < 20 or raw_text in seen:
                    continue
                seen.add(raw_text)

                # Strip trailing citation numbers (".289–293") and resolve them
                cit_match = CITATION_SUFFIX_RE.search(raw_text)
                if cit_match:
                    clean_text = raw_text[: cit_match.start() + 1]  # keep the period
                    ref_ids = _parse_ref_ids(cit_match.group(1))
                else:
                    clean_text = raw_text
                    ref_ids = []
                ref_ids = sorted(set(ref_ids) | set(sup_ref_ids))

                counter += 1
                table_recs += 1
                recs.append({
                    "id": f"rec_{counter}",
                    "text": clean_text,
                    "metadata": {
                        "type": "recommendation",
                        "class": normalize_class(raw_class),
                        "evidence": normalize_evidence(raw_ev),
                        "disease": _pick_disease(table_title, clean_text, disease),
                        "topic": detect_topic(table_title or heading, clean_text),
                        "section": heading,
                        "table_title": table_title,
                        "ref_ids": ref_ids,
                        "references": _ref_entries(ref_ids, ref_dict),
                        "guideline": guideline,
                        "year": year,
                    },
                })

        # --- Strategy 2: prose blocks (fallback) ---
        # Only for sections whose recommendations are not in a table: otherwise
        # this re-reads the same tables as prose and turns figure legends and
        # definitions that merely mention "Class I" into recommendations.
        if table_recs:
            continue
        for block in re.split(r"\n{2,}", body):
            class_match = REC_CLASS_RE.search(block)
            if not class_match:
                continue
            # Drop leftover table rows — those are Strategy 1's job.
            block = "\n".join(l for l in block.split("\n") if not l.lstrip().startswith("|"))
            if not RECOMMENDATION_PHRASE_RE.search(block):
                continue
            text, ref_ids = _strip_sup_tags(block.strip())
            text, bracket_ref_ids = _strip_bracket_citations(text)
            ref_ids = sorted(set(ref_ids) | set(bracket_ref_ids))
            text = re.sub(r"\s+", " ", text).strip()
            # A recommendation is a sentence or two; anything longer is the
            # surrounding discussion that happens to quote a class.
            if not 30 <= len(text) <= 600 or text in seen:
                continue
            seen.add(text)
            evidence_match = REC_EVIDENCE_RE.search(block)
            evidence = next(
                (g for g in (evidence_match.groups() if evidence_match else []) if g),
                "NR",
            )
            counter += 1
            recs.append({
                "id": f"rec_{counter}",
                "text": text,
                "metadata": {
                    "type": "recommendation",
                    "class": normalize_class(class_match.group(1)),
                    "evidence": evidence,
                    "disease": disease,
                    "topic": detect_topic(heading, text),
                    "section": heading,
                    "table_title": "",
                    "guideline": guideline,
                    "year": year,
                    "ref_ids": ref_ids,
                    "references": _ref_entries(ref_ids, ref_dict),
                },
            })

    return recs


# ---------------------------------------------------------------------------
# Quality report
# ---------------------------------------------------------------------------

def build_report(sections: list[tuple[str, str]], recs: list[dict], guideline: str, year: str, ref_dict: dict[int, str] | None = None) -> str:
    lines = []
    sep = "─" * 60

    lines.append(sep)
    lines.append(f"EXTRACTIE RAPPORT  —  {guideline}" + (f" ({year})" if year else ""))
    lines.append(sep)
    lines.append(f"Totaal aanbevelingen: {len(recs)}")
    if ref_dict:
        lines.append(f"Referenties in guideline: {len(ref_dict)}")

    # Class distribution
    classes: dict[str, int] = {}
    for r in recs:
        c = r["metadata"]["class"]
        classes[c] = classes.get(c, 0) + 1
    lines.append("\nKlasse-verdeling:")
    for cls, count in sorted(classes.items()):
        flag = "  ⚠  controleer handmatig" if cls == "Class II?" else ""
        lines.append(f"  {cls}: {count}{flag}")

    # Evidence distribution — ESC 2026 splits B into B1/B2, so it is worth
    # seeing at a glance whether that came through.
    levels: dict[str, int] = {}
    for r in recs:
        e = r["metadata"]["evidence"]
        levels[e] = levels.get(e, 0) + 1
    lines.append("\nEvidence-verdeling:")
    for lvl, count in sorted(levels.items()):
        lines.append(f"  Level {lvl}: {count}")

    # Disease distribution
    diseases: dict[str, int] = {}
    for r in recs:
        d = r["metadata"]["disease"]
        diseases[d] = diseases.get(d, 0) + 1
    lines.append("\nZiekte-verdeling:")
    for disease, count in sorted(diseases.items(), key=lambda x: -x[1]):
        lines.append(f"  {disease}: {count}")

    # Per-section counts
    sec_counts: dict[str, int] = {}
    for r in recs:
        sec = r["metadata"]["section"]
        sec_counts[sec] = sec_counts.get(sec, 0) + 1
    lines.append(f"\nAanbevelingen per sectie ({len(sec_counts)} secties):")
    for sec, count in sorted(sec_counts.items(), key=lambda x: -x[1]):
        lines.append(f"  [{count:3d}]  {sec}")

    # Skipped sections
    skipped = [h for h, _ in sections if SKIP_SECTION_RE.search(h)]
    if skipped:
        lines.append(f"\nOvergeslagen secties ({len(skipped)}):")
        for h in skipped:
            lines.append(f"  —  {h}")

    # Reference statistics
    with_refs = [r for r in recs if r["metadata"].get("ref_ids")]
    if recs:
        total_refs = sum(len(r["metadata"].get("ref_ids", [])) for r in recs)
        avg_refs = round(total_refs / len(recs), 1)
        lines.append(f"\nReferenties:")
        lines.append(f"  Chunks met referenties: {len(with_refs)} van {len(recs)} ({round(len(with_refs)/len(recs)*100)}%)")
        lines.append(f"  Gemiddeld per chunk: {avg_refs}")

    # Potential issues
    issues = []
    if classes.get("Class II?", 0) > 0:
        issues.append(f"{classes['Class II?']} chunk(s) met label 'Class II?' — controleer in Results-tab")
    short = [r for r in recs if len(r["text"]) < 50]
    if short:
        issues.append(f"{len(short)} zeer korte aanbeveling(en) (<50 tekens)")
    general_pct = round(diseases.get("general", 0) / len(recs) * 100) if recs else 0
    if general_pct > 50:
        issues.append(f"{general_pct}% van de aanbevelingen heeft disease='general' — overweeg DISEASE_PATTERNS uit te breiden")

    if issues:
        lines.append("\n⚠  Aandachtspunten:")
        for issue in issues:
            lines.append(f"  •  {issue}")
    else:
        lines.append("\n✓  Geen aandachtspunten gevonden.")

    lines.append(sep)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    if not INPUT_MD.exists():
        print(f"ERROR: {INPUT_MD} not found. Run step 1 first.")
        sys.exit(1)

    print(f"Reading markdown from: {INPUT_MD}")
    markdown = INPUT_MD.read_text(encoding="utf-8")
    print(f"Markdown loaded — {len(markdown):,} characters.")

    print("Parsing references section...")
    ref_dict = parse_reference_section(markdown)
    if ref_dict:
        print(f"Found {len(ref_dict)} references (#{min(ref_dict)} – #{max(ref_dict)}).")
    else:
        print("No references section found — ref_ids will be empty.")

    sections = split_into_sections(markdown)

    print("Extracting recommendations...")
    recs = extract_recommendations(sections, ref_dict=ref_dict,
                                   guideline=PROJECT_TITLE, year=GUIDELINE_YEAR)

    OUTPUT_JSON.write_text(json.dumps(recs, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved {len(recs)} recommendations to: {OUTPUT_JSON}")

    report = build_report(sections, recs, PROJECT_TITLE, GUIDELINE_YEAR, ref_dict=ref_dict)
    print(f"\n{report}")

    report_path = OUTPUT_JSON.parent / "extraction_report.txt"
    report_path.write_text(report, encoding="utf-8")
    print(f"\nRapport opgeslagen: {report_path}")


if __name__ == "__main__":
    main()
