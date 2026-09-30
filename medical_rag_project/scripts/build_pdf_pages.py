"""
Paginanummers voor alle aanbevelingen van een project, in één keer.

Schrijft pdf_pages.json in de projectmap: {chunk_id: 0-based pagina}. Dat is
dezelfde cache die "Toon in PDF" in de desktop-app per aanbeveling vult, maar
dan compleet — de iOS-app kan geen PyMuPDF draaien en springt alleen naar een
pagina die hier al staat.

    python build_pdf_pages.py "<projectmap>" [--all]

Zonder --all worden alleen aanbevelingen zonder pagina opgezocht, zodat een
pagina die de gebruiker al via de desktop-app bekeken heeft blijft staan.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from pdf_locate import norm, shingles  # noqa: E402
import pdf_locate  # noqa: E402


class _Pages:
    """Genormaliseerde paginateksten, één keer uitgelezen voor alle chunks."""

    def __init__(self, doc):
        self._texts = [norm(doc[i].get_text()) for i in range(doc.page_count)]
        self.page_count = doc.page_count

    def __getitem__(self, i):
        return _Page(self._texts[i])


class _Page:
    def __init__(self, text):
        self._text = text

    def get_text(self):
        return self._text


def main() -> None:
    import pymupdf

    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    redo_all = "--all" in sys.argv
    if not args:
        print(__doc__.strip(), file=sys.stderr)
        sys.exit(2)

    project = Path(args[0])
    chunks_file = project / "rag_chunks.json"
    cache_file = project / "pdf_pages.json"
    pdfs = sorted(project.glob("*.pdf"))
    if not chunks_file.exists() or not pdfs:
        print(f"{project.name}: overgeslagen (geen rag_chunks.json of PDF)")
        return

    chunks = json.loads(chunks_file.read_text(encoding="utf-8"))
    cache = {}
    if cache_file.exists() and not redo_all:
        try:
            cache = json.loads(cache_file.read_text(encoding="utf-8"))
        except ValueError:
            cache = {}

    todo = [c for c in chunks if c.get("id") and c["id"] not in cache]
    if not todo:
        print(f"{project.name}: alle {len(chunks)} pagina's al bekend")
        return

    doc = pymupdf.open(pdfs[0])
    try:
        pages = _Pages(doc)
    finally:
        doc.close()

    found = 0
    for chunk in todo:
        if not shingles(norm(chunk.get("text", ""))):
            continue
        result = pdf_locate.locate(
            pages, chunk.get("text", ""), (chunk.get("metadata") or {}).get("table_title") or ""
        )
        if result.get("found"):
            cache[chunk["id"]] = result["page"]
            found += 1

    # Alleen chunks die nog bestaan: een verwijderde aanbeveling hoort er niet
    # meer in te staan.
    ids = {c.get("id") for c in chunks}
    cache = {k: v for k, v in cache.items() if k in ids}
    cache_file.write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"{project.name}: {found} van {len(todo)} nieuwe pagina's gevonden, "
          f"{len(cache)}/{len(chunks)} bekend")


if __name__ == "__main__":
    main()
