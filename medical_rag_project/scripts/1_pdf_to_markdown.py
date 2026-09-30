"""
Step 1: Convert guideline PDF to Markdown

Input:  data/<pdf_name>  (RAG_PDF_NAME env var, or first .pdf found in data dir)
Output: data/guideline.md
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from pipeline_common import DATA_ROOT  # noqa: E402

DATA_DIR = Path(os.getenv("RAG_DATA_DIR", str(DATA_ROOT / "data")))
OUTPUT_MD = DATA_DIR / "guideline.md"

# Resolve PDF: prefer explicit env var, fallback to first PDF in data dir
_pdf_name = os.getenv("RAG_PDF_NAME", "")
if _pdf_name:
    INPUT_PDF = DATA_DIR / _pdf_name
else:
    _pdfs = sorted(DATA_DIR.glob("*.pdf"))
    INPUT_PDF = _pdfs[0] if _pdfs else DATA_DIR / "guideline.pdf"


def convert_pdf_to_markdown(pdf_path: Path, output_path: Path) -> None:
    import pymupdf4llm

    print(f"Loading PDF: {pdf_path}")

    if not pdf_path.exists():
        print(f"ERROR: PDF not found at {pdf_path}")
        sys.exit(1)

    print("Converting PDF to markdown (this may take a moment)...")
    markdown_text = pymupdf4llm.to_markdown(str(pdf_path))

    # pymupdf4llm drops spaces and ligatures in table cells ("inpatients",
    # "signifcant"); repair against the PDF's own plain text. See text_repair.py.
    from text_repair import repair_markdown

    markdown_text, repaired = repair_markdown(markdown_text, pdf_path)
    print(f"Repaired {repaired} words (missing spaces, ligatures, footnote letters).")

    output_path.write_text(markdown_text, encoding="utf-8")
    print(f"Saved markdown to: {output_path}")

    word_count = len(markdown_text.split())
    line_count = markdown_text.count("\n")
    print(f"Done — {line_count} lines, ~{word_count} words written.")


if __name__ == "__main__":
    convert_pdf_to_markdown(INPUT_PDF, OUTPUT_MD)
