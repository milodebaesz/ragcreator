"""
Herstel van extractiefouten in de markdown van stap 1.

pymupdf4llm's layout-modus verliest in tabelcellen spaties ("inpatients",
"diagnosingPE") en ligaturen ("signifcant", "frst"). De klassieke modus heeft
dat niet, maar levert een tabelstructuur waar stap 2 heel andere aanbevelingen
uit haalt — dus die gebruiken we niet.

In plaats daarvan repareren we achteraf, met de gewone tekst van dezelfde PDF
(page.get_text()) als referentie: daarin kloppen spaties en ligaturen wel.
Een woord wordt alleen veranderd als het níet in die referentie voorkomt én de
gerepareerde vorm wél. Een woord dat de richtlijn zelf gebruikt (bijv. een
echt "inpatients") blijft dus altijd staan.

Gebruik:
  * stap 1 roept repair_markdown() aan op verse uitvoer;
  * voor bestaande projecten:  python text_repair.py <projectmap> [--dry-run]
    Dat past alleen tekstvelden aan in guideline.md en rag_chunks.json;
    metadata (klasse, accordering, bewerkingen) blijft onaangeroerd.
"""

from __future__ import annotations

import json
import re
import unicodedata
import shutil
import sys
from collections import Counter
from pathlib import Path

WORD = re.compile(r"[A-Za-z]+")
# Een ligatuur-glyph ("fi", "fl") komt eruit als een kale "f": "signifcant", "frst".
LIGATURES = ("fi", "fl", "ff", "ffi", "ffl")
# Voetnootletters in superscript plakken aan het woord: "surgerycshould".
FOOTNOTE_LETTERS = "abcdefgh"
# "emer-<br>gency" in markdown, "emer- gency" nadat stap 2 <br> door een spatie verving.
BROKEN_HYPHEN = re.compile(r"\b([A-Za-z]+)-(?:\s*<br\s*/?>\s*|\s+)([a-z]+)(?![a-z])")
LINE_HYPHEN = re.compile(r"([A-Za-z]+)-\n([a-z]+)")
# Korte stukken die we bij het opsplitsen toelaten; verder alleen afkortingen
# in hoofdletters ("PE", "AS"). Anders wordt "Classa" "Cl ss a".
SHORT_WORDS = {"a", "an", "as", "at", "be", "by", "do", "if", "in", "is", "it",
               "no", "of", "on", "or", "so", "to", "up", "we"}
# Ontbrekende spatie naast leestekens: "circumstances)is", "CTPA(depending".
PUNCT_GLUE = re.compile(r"\b([A-Za-z]+)([()])([A-Za-z]+)\b")


class Reference:
    """Woordenschat en woordparen uit de correct geëxtraheerde PDF-tekst."""

    def __init__(self, text: str):
        text = unicodedata.normalize("NFKC", text)
        # Afbreking aan het regeleinde ("dis-\ntrict") telt als één woord;
        # anders staan "dis" en "trict" als woordpaar in de referentie en wordt
        # een correct "district" in de markdown juist opgesplitst.
        flat = re.sub(r"\s+", " ", LINE_HYPHEN.sub(r"\1\2", text))
        words = [w.lower() for w in WORD.findall(flat)]
        self.vocab = Counter(words)
        self.bigrams = Counter(zip(words, words[1:]))
        self.flat = flat
        # Voor het samenvoegen van afbrekingen tellen alleen woorden die de PDF
        # ergens heel schrijft; een afgebroken "weight-\nadjusted" mag geen
        # "weightadjusted" opleveren.
        whole = re.sub(r"\s+", " ", LINE_HYPHEN.sub(" ", text))
        self.whole = Counter(w.lower() for w in WORD.findall(whole))
        self.hyphenated = {m.lower() for m in re.findall(r"[A-Za-z]+-[A-Za-z]+", whole)}

    @classmethod
    def from_pdf(cls, pdf_path: Path) -> "Reference":
        import pymupdf

        # Korte superscript-spans (voetnootletters, citatienummers) laten we
        # weg: in de platte tekst plakken die net zo aan het woord, en dan zou
        # "surgeryc" als echt woord in de woordenschat belanden. Alleen korte:
        # sommige PDF's markeren hele tekstregels ten onrechte als superscript.
        lines = []
        with pymupdf.open(pdf_path) as doc:
            for page in doc:
                for block in page.get_text("dict")["blocks"]:
                    for line in block.get("lines", []):
                        lines.append("".join(
                            s["text"] for s in line["spans"]
                            if not (s["flags"] & pymupdf.TEXT_FONT_SUPERSCRIPT
                                    and len(s["text"].strip()) <= 3)
                        ))
        return cls("\n".join(lines))

    def known(self, word: str) -> bool:
        return word.lower() in self.vocab


def _ligature_variants(word: str) -> list[str]:
    """Het woord zelf plus elke vorm waarin één kale "f" weer een ligatuur is."""
    return [word] + [
        word[:i] + lig + word[i + 1:]
        for i, ch in enumerate(word) if ch in "fF"
        for lig in LIGATURES
    ]


def _segment(word: str, ref: Reference) -> list[str] | None:
    """Splits een plakwoord in woorden die zo ook in de referentie staan.

    "inpatients" -> in|patients, "inproperlyselectedpatients" -> in|properly|
    selected|patients, "surgerycshould" -> surgery|should (voetnootletter c
    valt weg). Elk opeenvolgend paar moet als woordpaar in de referentie
    voorkomen: dat is wat een echte spatie van een toevallige opsplitsing
    onderscheidt. Alleen over een weggevallen voetnootletter heen volstaat dat
    beide delen vaker in de richtlijn staan.
    """
    low = word.lower()
    n = len(low)

    def piece_ok(p: str, orig: str) -> bool:
        if p not in ref.vocab:
            return False
        return len(p) >= 3 or p in SHORT_WORDS or (len(p) == 2 and orig.isupper())

    best: dict[tuple[int, str], tuple[list[str], int] | None] = {}

    def solve(i: int, prev: str) -> tuple[list[str], int] | None:
        # Beste opsplitsing van low[i:], gegeven het vorige stuk.
        if i == n:
            return [], 0
        key = (i, prev)
        if key in best:
            return best[key]
        result = None
        for j in range(i + 1, n + 1):
            piece = low[i:j]
            if not piece_ok(piece, word[i:j]):
                continue
            skips = [0]
            if j < n - 1 and low[j] in FOOTNOTE_LETTERS:
                skips.append(1)
            for skip in skips:
                if prev and not ref.bigrams.get((prev, piece)):
                    continue
                nxt = "" if skip else piece
                # Een letter weggooien alleen na een volwaardig woord, niet na
                # een fragment: "infor-" is geen "in" + f + "or".
                if skip and (ref.vocab[piece] < 2 or (len(piece) < 3 and not word[i:j].isupper())):
                    continue
                rest = solve(j + skip, nxt)
                if rest is None:
                    continue
                if skip and rest[0] and ref.vocab[rest[0][0].lower()] < 2:
                    continue
                cand = ([word[i:j]] + rest[0], skip + rest[1])
                # Minste stukken, en bij gelijkspel géén weggegooide letter:
                # anders wordt "theprocedure" "th procedure" (e als voetnoot).
                if result is None or (len(cand[0]), cand[1]) < (len(result[0]), result[1]):
                    result = cand
        best[key] = result
        return result

    solved = solve(0, "")
    return solved[0] if solved and len(solved[0]) > 1 else None


def repair_word(word: str, ref: Reference) -> str:
    if len(word) < 4 or ref.known(word):
        return word
    variants = _ligature_variants(word)
    fixed = [v for v in variants[1:] if ref.known(v)]
    # Alleen bij één eenduidige kandidaat; anders gokken we.
    if len(fixed) == 1:
        return fixed[0]
    # Voetnootletter aan het eind: "riskc", "consideredc". Vóór het opsplitsen,
    # anders wordt "consideredc" "consider dc". Niet voor "a": dat is net zo
    # vaak een vastgeplakt lidwoord ("usinga" -> "using a").
    # Niet bij korte woorden: "cand" is "c" + "and", niet "can" + "d".
    if word[-1] in FOOTNOTE_LETTERS[1:] and len(word) >= 5 and ref.known(word[:-1]):
        return word[:-1]
    for v in variants:
        parts = _segment(v, ref)
        if parts:
            return " ".join(parts)
    # "Classa" -> "Class", maar een afgebroken "thera-" blijft staan.
    if word[-1] == "a" and len(word) > 5 and ref.known(word[:-1]):
        return word[:-1]
    # En aan het begin: "cafter", "cand". Niet "fits" -> "its".
    rest = word[1:]
    if word[0] in FOOTNOTE_LETTERS and ref.known(rest) and (len(rest) >= 4 or rest in ("and", "the")):
        return rest
    return word


def repair_text(text: str, ref: Reference) -> str:
    def join_hyphen(m: re.Match) -> str:
        a, b = m.group(1), m.group(2)
        joined = a + b
        if joined.lower() in ref.whole and f"{a}-{b}".lower() not in ref.hyphenated:
            return joined
        return m.group(0)

    def space_punct(m: re.Match) -> str:
        a, p, b = m.groups()
        spaced = f"{a} {p}{b}" if p == "(" else f"{a}{p} {b}"
        return spaced if spaced in ref.flat and m.group(0) not in ref.flat else m.group(0)

    # Volgorde telt: eerst afbrekingen herstellen ("emer- gencyCTPA" ->
    # "emergencyCTPA"), dan woorden ("emergency CTPA"), dan pas leestekens,
    # want die check zoekt het buurwoord letterlijk op in de referentie.
    text = BROKEN_HYPHEN.sub(join_hyphen, text)
    text = WORD.sub(lambda m: repair_word(m.group(0), ref), text)
    return PUNCT_GLUE.sub(space_punct, text)


def repair_markdown(markdown: str, pdf_path: Path) -> tuple[str, int]:
    """Repareer verse stap-1-uitvoer. Geeft (tekst, aantal gewijzigde woorden)."""
    ref = Reference.from_pdf(pdf_path)
    repaired = repair_text(markdown, ref)
    return repaired, _count_changes(markdown, repaired)


def _count_changes(before: str, after: str) -> int:
    a, b = Counter(WORD.findall(before)), Counter(WORD.findall(after))
    return sum((a - b).values())


def repair_project(project_dir: Path, dry_run: bool = False) -> None:
    pdfs = sorted(project_dir.glob("*.pdf"))
    if not pdfs:
        sys.exit(f"Geen PDF in {project_dir} — zonder referentie repareren we niets.")
    ref = Reference.from_pdf(pdfs[0])

    md_path = project_dir / "guideline.md"
    if md_path.exists():
        before = md_path.read_text(encoding="utf-8")
        after = repair_text(before, ref)
        print(f"guideline.md: {_count_changes(before, after)} woorden hersteld")
        if not dry_run and after != before:
            shutil.copy2(md_path, md_path.with_suffix(".md.bak"))
            md_path.write_text(after, encoding="utf-8")

    chunks_path = project_dir / "rag_chunks.json"
    if chunks_path.exists():
        chunks = json.loads(chunks_path.read_text(encoding="utf-8"))
        changed = 0
        for chunk in chunks:
            old = chunk.get("text", "")
            new = repair_text(old, ref)
            if new != old:
                changed += 1
                if dry_run and changed <= 5:
                    print(f"  - {old[:110]}\n  + {new[:110]}")
                chunk["text"] = new
        print(f"rag_chunks.json: {changed} van {len(chunks)} chunks hersteld")
        if not dry_run and changed:
            shutil.copy2(chunks_path, chunks_path.with_suffix(".json.bak"))
            chunks_path.write_text(json.dumps(chunks, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 1:
        sys.exit("Gebruik: python text_repair.py <projectmap> [--dry-run]")
    repair_project(Path(args[0]), dry_run="--dry-run" in sys.argv)
