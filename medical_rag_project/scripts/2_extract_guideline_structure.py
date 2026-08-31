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

PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = Path(os.getenv("RAG_DATA_DIR", str(PROJECT_ROOT / "data")))
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
CITATION_SUFFIX_RE = re.compile(r"[.;](\d[\d,\s\u2013\-]*)$")

# ESC/ACC standard recommendation table: | text | Class | Level |
TABLE_REC_RE = re.compile(
    r"^\|(.+?)\|\s*\*{0,2}(I{1,3}|IIa|IIb|III|IV)\*{0,2}\s*\|\s*\*{0,2}([ABC])\*{0,2}\s*\|",
    re.IGNORECASE | re.MULTILINE,
)

# Prose fallback: blocks containing "Class I/II..." + Level of Evidence
REC_CLASS_RE = re.compile(r"(Class\s+(?:I{1,3}|IIa|IIb|III|IV))\b", re.IGNORECASE)
REC_EVIDENCE_RE = re.compile(
    r"Level of [Ee]vidence[:\s]+([ABC])\b|LOE[:\s]+([ABC])\b|Evidence[:\s]+([ABC])\b",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def detect_disease(text: str) -> str:
    text_lower = text.lower()
    for code, keywords in DISEASE_PATTERNS.items():
        if any(kw in text_lower for kw in keywords):
            return code
    return "general"


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


def find_preceding_title(body: str, pos: int) -> str:
    """Return the table caption/heading that precedes the table row at `pos`.

    Walks backwards through the lines before `pos`, skipping blank lines and
    table rows (header + separator), and returns the first non-empty content
    line that is long enough to be a meaningful title.
    """
    before = body[:pos]
    for line in reversed(before.split("\n")):
        stripped = re.sub(r"[*_`#>]", "", line).strip()
        if not stripped:
            continue
        if line.strip().startswith("|"):
            continue  # skip table header / separator rows
        if len(stripped) > 15:
            return stripped
        break  # too short to be a meaningful title
    return ""


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

        # --- Strategy 1: ESC/ACC table rows ---
        last_match_end: int = -200   # triggers title lookup for first match
        current_table_title: str = ""
        for match in TABLE_REC_RE.finditer(body):
            # New table detected when there is a gap of > 100 chars since last row
            if match.start() - last_match_end > 100:
                current_table_title = find_preceding_title(body, match.start())
            last_match_end = match.end()

            raw_text = re.sub(r"\s*<br\s*/?>\s*", " ", match.group(1)).strip()
            raw_text = re.sub(r"\s+", " ", raw_text).strip("|").strip()

            # Strip <sup>citation</sup> markup left by the PDF conversion before
            # the trailing-suffix check below, which only matches bare digits.
            raw_text, sup_ref_ids = _strip_sup_tags(raw_text)
            raw_text = re.sub(r"\s+", " ", raw_text).strip()

            if len(raw_text) < 20 or raw_text in seen:
                continue
            seen.add(raw_text)

            # Strip trailing citation numbers (e.g. ".289–293") and resolve them
            cit_match = CITATION_SUFFIX_RE.search(raw_text)
            if cit_match:
                clean_text = raw_text[: cit_match.start() + 1]  # keep the period
                ref_ids = _parse_ref_ids(cit_match.group(1))
            else:
                clean_text = raw_text
                ref_ids = []
            ref_ids = sorted(set(ref_ids) | set(sup_ref_ids))
            references = [ref_dict[i] for i in ref_ids if i in ref_dict]

            counter += 1
            recs.append({
                "id": f"rec_{counter}",
                "text": clean_text,
                "metadata": {
                    "type": "recommendation",
                    "class": normalize_class(match.group(2)),
                    "evidence": match.group(3).upper(),
                    "disease": disease,
                    "topic": detect_topic(heading, clean_text),
                    "section": heading,
                    "table_title": current_table_title,
                    "ref_ids": ref_ids,
                    "references": references,
                    "guideline": guideline,
                    "year": year,
                },
            })

        # --- Strategy 2: prose blocks (fallback) ---
        for block in re.split(r"\n{2,}", body):
            class_match = REC_CLASS_RE.search(block)
            if not class_match:
                continue
            text, ref_ids = _strip_sup_tags(block.strip())
            text = re.sub(r"\s+", " ", text).strip()
            if len(text) < 30 or text in seen:
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
                    "guideline": guideline,
                    "year": year,
                    "ref_ids": ref_ids,
                    "references": [ref_dict[i] for i in ref_ids if i in ref_dict],
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
