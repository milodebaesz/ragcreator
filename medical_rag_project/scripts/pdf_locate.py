"""
PDF locator/renderer for the "Toon in PDF" feature.

Reads a JSON request on stdin, writes a JSON response on stdout, so the Tauri
side needs no PDF library of its own — PyMuPDF is already a pipeline dependency.

Request:
  {
    "pdf":         "/abs/path/to/guideline.pdf",
    "text":        "the recommendation text",   # locate mode
    "table_title": "Recommendation Table 7 — …", # optional anchor
    "page":        17,                           # 0-based; render this page instead of searching
    "zoom":        2.0
  }

Response:
  {
    "page": 17, "total_pages": 112, "page_label": "18",
    "found": true, "score": 0.92,
    "rects": [[x0,y0,x1,y1], …],   # in image pixels, for the UI overlay
    "width": 1224, "height": 1584,
    "png_base64": "…",
    "candidates": [17, 9]
  }

Locating is a text search rather than a stored page number on purpose: it works
for chunks that were extracted before page tracking existed, and it survives
hand-edits to the recommendation text.
"""

import base64
import io
import json
import re
import sys

# Ligature/typography damage from PDF→markdown conversion, normalised away on
# both sides of the comparison so a chunk still matches its source page.
_TRANSLATE = {
    "­": "",   # soft hyphen
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-",
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "ﬁ": "fi", "ﬂ": "fl", " ": " ",
}

SHINGLE_LEN = 8
SHINGLE_STEP = 4


def norm(text: str) -> str:
    for src, dst in _TRANSLATE.items():
        text = text.replace(src, dst)
    return re.sub(r"\s+", " ", text).strip().lower()


def shingles(text: str, size: int = SHINGLE_LEN, step: int = SHINGLE_STEP) -> list[str]:
    """Overlapping word windows — a recommendation that breaks across a column
    or a page still matches on most of its windows."""
    words = text.split()
    if len(words) <= size:
        return [" ".join(words)] if words else []
    return [
        " ".join(words[i:i + size])
        for i in range(0, len(words) - size + 1, step)
    ]


def caption_anchor(table_title: str) -> "re.Pattern | None":
    """Pattern matching the table caption, e.g. 'Recommendation Table 7'.

    The trailing (?!\\d) matters: without it 'Table 1' also matches 'Table 19'.
    """
    m = re.match(r"\s*((?:recommendation\s+)?table\s+(\d+))", norm(table_title or ""))
    if not m:
        return None
    return re.compile(re.escape(m.group(1)) + r"(?!\d)")


def locate(doc, text: str, table_title: str) -> dict:
    target = norm(text)
    probes = shingles(target)
    if not probes:
        return {"found": False, "page": 0, "score": 0.0, "candidates": []}

    page_texts = [norm(doc[i].get_text()) for i in range(doc.page_count)]

    anchor = caption_anchor(table_title)
    anchor_pages = (
        [i for i, pt in enumerate(page_texts) if anchor.search(pt)] if anchor else []
    )
    # The table of contents lists every caption; the real table is the one that
    # also carries recommendation text, so anchors are only used as a tiebreak.

    scored = []
    for i, pt in enumerate(page_texts):
        hits = sum(1 for p in probes if p in pt)
        if hits:
            scored.append((hits / len(probes), i))
    if not scored:
        return {"found": False, "page": 0, "score": 0.0, "candidates": []}

    def rank(entry):
        score, page = entry
        # Distance to the nearest caption occurrence; a recommendation sits on
        # the caption's page or the page or two after it where the table runs on.
        dist = min((abs(page - a) for a in anchor_pages), default=0)
        # Guidelines restate recommendations in the summary/"what is new"
        # section, which can match the text just as well as the real table.
        # Pages near the table caption therefore win outright, and only within
        # that window does the text score decide.
        near_table = 0 if (anchor_pages and dist <= 2) else 1
        return (near_table, -round(score, 3), dist, page)

    scored.sort(key=rank)
    best_score, best_page = scored[0]
    return {
        "found": True,
        "page": best_page,
        "score": round(best_score, 3),
        "candidates": [p for _, p in scored[:5]],
    }


def highlight_rects(page, text: str) -> list:
    """Boxes for the parts of `text` PyMuPDF can find on this page.

    Searched per shingle because search_for only reliably matches text that
    stays on one line; the union of the windows covers the whole paragraph.
    """
    rects = []
    for probe in shingles(text, size=6, step=3):
        try:
            found = page.search_for(probe)
        except Exception:
            found = []
        rects.extend(found)

    if not rects:
        return []

    # Merge boxes that sit on the same text line, so the overlay draws a few
    # clean bands instead of dozens of overlapping fragments.
    rects.sort(key=lambda r: (round(r.y0, 1), r.x0))
    merged = []
    for r in rects:
        if merged and abs(merged[-1][1] - r.y0) < 4 and r.x0 <= merged[-1][2] + 6:
            m = merged[-1]
            merged[-1] = [min(m[0], r.x0), min(m[1], r.y0), max(m[2], r.x1), max(m[3], r.y1)]
        else:
            merged.append([r.x0, r.y0, r.x1, r.y1])
    return merged


def render(doc, page_no: int, zoom: float, text: str) -> dict:
    import pymupdf

    page = doc[page_no]
    rects = highlight_rects(page, norm(text)) if text else []

    matrix = pymupdf.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=matrix, alpha=False)
    buf = io.BytesIO(pix.tobytes("png"))

    return {
        "page": page_no,
        "total_pages": doc.page_count,
        "page_label": page.get_label() or str(page_no + 1),
        "width": pix.width,
        "height": pix.height,
        # Scaled to image pixels so the UI can position the overlay directly.
        "rects": [[c * zoom for c in r] for r in rects],
        "png_base64": base64.b64encode(buf.getvalue()).decode("ascii"),
    }


def main() -> None:
    import pymupdf

    try:
        req = json.load(sys.stdin)
    except Exception as exc:
        json.dump({"error": f"bad request: {exc}"}, sys.stdout)
        return

    pdf_path = req.get("pdf") or ""
    zoom = float(req.get("zoom") or 2.0)
    text = req.get("text") or ""

    try:
        doc = pymupdf.open(pdf_path)
    except Exception as exc:
        json.dump({"error": f"kan PDF niet openen: {exc}"}, sys.stdout)
        return

    try:
        result = {"found": True, "score": None, "candidates": []}

        page_no = req.get("page")
        if page_no is None:
            result = locate(doc, text, req.get("table_title") or "")
            page_no = result.get("page", 0)

        page_no = max(0, min(int(page_no), doc.page_count - 1))
        result.update(render(doc, page_no, zoom, text))
        json.dump(result, sys.stdout)
    except Exception as exc:
        json.dump({"error": str(exc)}, sys.stdout)
    finally:
        doc.close()


if __name__ == "__main__":
    main()
