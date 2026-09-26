"""
Stap 3: Genereer klinische Q&A-paren uit de genormaliseerde aanbevelingen.

Input:  normalized/<slug>.chunks.json   (via pipeline_common.ensure_normalized)
Output: normalized/<slug>.qa.json       (voor stap 4/5)
        <project>/qa_pairs.json         (voor de RAGCreator-viewer)

WAAROM Q&A-PAREN
----------------
De aanbevelingen zijn voorschrijvende volzinnen ("... is recommended in patients
with ..."), maar gebruikers stellen vragen of plakken een casus. In de
embeddingruimte liggen die ver uit elkaar: gemeten blijft de top-similariteit
tegen de richtlijnen steken rond 0,51-0,54. Een vraag tegen een vraag matchen
scoort structureel veel hoger.

Daarom drie varianten per aanbeveling:
  en       Engelse artsvraag        - matcht Engelstalige/klinische invoer
  nl       Nederlandse artsvraag    - matcht de taal van de anamnese-app
  scenario korte casusbeschrijving  - matcht de vorm die de app echt oplevert
                                      ("man 68, pijn op de borst bij inspanning")

BELANGRIJK
----------
Het gegenereerde `answer` wordt bewaard voor review en debugging, maar gaat
NOOIT naar het taalmodel toe bij retrieval. Een Q&A-treffer levert altijd de
letterlijke bovenliggende aanbeveling. Zo groeit het hallucinatie-oppervlak niet.

Alleen chunks die de goedkeuringspoort passeren krijgen Q&A-paren; de rest
kost anders onnodig geld.

Elk paar krijgt een `source_hash` van de aanbeveling waarvoor het gemaakt is.
Bij opnieuw draaien worden paren met een kloppende hash hergebruikt; een
bewerkte of samengevoegde aanbeveling krijgt nieuwe vragen. Zo kan een vraag
nooit blijven hangen aan een tekst die intussen iets anders zegt.
"""

from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from pipeline_common import (  # noqa: E402
    PipelineError, die, eligible_only, ensure_normalized, explain_skipped, qa_path,
    qa_source_hash, split_qa_by_freshness,
)

try:
    from openai import OpenAI
except ImportError:
    die("openai is niet geinstalleerd. Draai: pip install openai")

try:
    from tqdm import tqdm
except ImportError:                                     # tqdm is optioneel
    def tqdm(x, **k):                                   # type: ignore
        return x

MODEL = os.getenv("RAG_QA_MODEL", "gpt-4.1-mini")
MIN_CHUNK_LENGTH = 120          # tekens; korter levert geen zinnige vraag op
MAX_RETRIES = 2
# Losse calls per aanbeveling; sequentieel duurt 821 chunks ruim een half uur.
WORKERS = int(os.getenv("RAG_QA_WORKERS", "8"))

SYSTEM_PROMPT = """You are a medical knowledge extraction system.

You receive one clinical guideline recommendation. Produce search questions for
which this recommendation is the answer. These are used to retrieve the
recommendation later, so they must sound like what a physician would actually
type.

Return exactly three questions:
  "en"       - an English question a physician would ask
  "nl"       - the equivalent question in Dutch, using Dutch clinical terminology
  "scenario" - a short Dutch patient vignette (max 20 words) that should lead a
               clinician to this recommendation. Format like a case note, e.g.
               "man 68, pijn op de borst bij inspanning, bekend met DM2".
               No question mark, no full sentence.

Also return:
  "answer"   - a factual 1-3 sentence answer based ONLY on the given text.

Rules:
- Use proper medical terminology; keep abbreviations a clinician would use.
- Never invent facts that are not in the text.
- Return JSON only, no markdown fences, no commentary.

{
  "en": "...",
  "nl": "...",
  "scenario": "...",
  "answer": "..."
}"""


def generate_qa(client: OpenAI, chunk: dict) -> dict | None:
    """Vraag het model om drie vraagvarianten + antwoord. None bij mislukking."""
    meta = chunk["metadata"]
    context = (
        f"Guideline: {meta.get('guideline')} {meta.get('year')}\n"
        f"Disease: {meta.get('disease')} | Topic: {meta.get('topic')}\n"
        f"Class: {meta.get('class') or 'n/a'} | Level: {meta.get('evidence') or 'n/a'}\n"
        f"Section: {meta.get('section') or 'n/a'}\n\n"
        f"Recommendation:\n{chunk['text']}"
    )

    for attempt in range(MAX_RETRIES + 1):
        try:
            response = client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": context},
                ],
                temperature=0.2,
                max_tokens=500,
                response_format={"type": "json_object"},
            )
            raw = (response.choices[0].message.content or "").strip()
            if not raw:
                continue
            data = json.loads(raw)
            if not any(str(data.get(k, "")).strip() for k in ("en", "nl", "scenario")):
                continue
            return data
        except json.JSONDecodeError:
            if attempt == MAX_RETRIES:
                print(f"  [WARN] {chunk['id']}: JSON onleesbaar na {MAX_RETRIES + 1} pogingen")
        except Exception as e:                                    # noqa: BLE001
            if attempt == MAX_RETRIES:
                print(f"  [WARN] {chunk['id']}: {str(e)[:120]}")
    return None


def main() -> None:
    if not os.getenv("OPENAI_API_KEY"):
        die("OPENAI_API_KEY is niet gezet.")

    try:
        key, entry, normalised = ensure_normalized()
    except PipelineError as e:
        die(str(e))

    eligible = eligible_only(normalised)
    if not eligible:
        skipped = explain_skipped(normalised)
        print(f"\nGeen enkele chunk van '{key}' is goedgekeurd voor upload:")
        for reason, n in skipped.most_common():
            print(f"  - {n}x {reason}")
        print("\nQ&A-generatie overgeslagen: dat zou alleen geld kosten.")
        print("Beoordeel de chunks in de RAGCreator-UI, of pas upload_policy aan "
              "in guidelines_registry.json.\n")
        return

    long_enough = [c for c in eligible if len(c["text"]) >= MIN_CHUNK_LENGTH]
    too_short = len(eligible) - len(long_enough)

    # Hergebruik paren waarvan de aanbeveling sinds generatie niet is gewijzigd.
    out = qa_path(entry)
    previous = json.loads(out.read_text(encoding="utf-8")) if out.exists() else []
    fresh, stale, orphan = split_qa_by_freshness(previous, long_enough)
    reuse_ids = {p["chunk_id"] for p in fresh}
    todo = [c for c in long_enough if c["id"] not in reuse_ids]

    print(f"\nQ&A voor {len(long_enough)} aanbevelingen "
          f"({too_short} te kort, {len(normalised) - len(eligible)} niet goedgekeurd)")
    print(f"  hergebruikt : {len(reuse_ids)} (tekst ongewijzigd)")
    print(f"  genereren   : {len(todo)}"
          + (f"  waarvan {len({p['chunk_id'] for p in stale})} gewijzigd sinds "
             f"vorige generatie" if stale else ""))
    if orphan:
        print(f"  weggegooid  : {len(orphan)} paren van aanbevelingen die niet "
              f"meer goedgekeurd zijn")
    print(f"Model: {MODEL}  -  3 vraagvarianten per aanbeveling\n")

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    pairs: list[dict] = []
    errors = 0

    # Parallel, maar de uitvoer wordt op chunk-id gesorteerd zodat het bestand
    # deterministisch blijft en diffs leesbaar zijn.
    results: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(generate_qa, client, c): c for c in todo}
        for fut in tqdm(as_completed(futures), total=len(futures), desc="Q&A-paren"):
            chunk = futures[fut]
            try:
                res = fut.result()
            except Exception as e:                                # noqa: BLE001
                print(f"  [WARN] {chunk['id']}: {str(e)[:120]}")
                res = None
            if res is None:
                errors += 1
            else:
                results[chunk["id"]] = res

    fresh_by_chunk: dict[str, list[dict]] = {}
    for p in fresh:
        fresh_by_chunk.setdefault(p["chunk_id"], []).append(p)

    for chunk in long_enough:
        chunk_id = chunk["id"]
        if chunk_id in fresh_by_chunk:
            pairs.extend(fresh_by_chunk[chunk_id])
            continue
        result = results.get(chunk_id)
        if result is None:
            continue
        meta = chunk["metadata"]
        answer = str(result.get("answer", "")).strip()
        for lang in ("en", "nl", "scenario"):
            question = str(result.get(lang, "")).strip()
            if not question:
                continue
            pairs.append({
                # Deterministisch, zodat opnieuw draaien geen duplicaten geeft.
                "id": f"{chunk['id']}_q_{lang}",
                "question": question,
                "answer": answer,          # alleen voor review; nooit naar het LLM
                "chunk_id": chunk["id"],   # verwijzing naar de echte aanbeveling
                "lang": lang,
                "source_hash": qa_source_hash(chunk),
                "metadata": {
                    "disease": meta.get("disease"),
                    "topic": meta.get("topic"),
                    "guideline": meta.get("guideline"),
                    "guideline_id": meta.get("guideline_id"),
                    "year": meta.get("year"),
                    "section": meta.get("section", ""),
                    "class": meta.get("class"),
                    "evidence": meta.get("evidence"),
                },
            })

    out.write_text(json.dumps(pairs, indent=2, ensure_ascii=False), encoding="utf-8")

    # Tweede kopie in de projectmap, zodat de Q&A-viewer in RAGCreator blijft werken.
    data_dir = os.getenv("RAG_DATA_DIR")
    if data_dir:
        legacy = Path(data_dir) / "qa_pairs.json"
        legacy.write_text(json.dumps(pairs, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nGeschreven: {legacy}")

    by_lang: dict[str, int] = {}
    for p in pairs:
        by_lang[p["lang"]] = by_lang.get(p["lang"], 0) + 1

    print(f"Geschreven: {out}")
    print(f"\n{len(pairs)} Q&A-paren over {len({p['chunk_id'] for p in pairs})} aanbevelingen")
    print(f"  per variant: {by_lang}")
    if errors:
        print(f"  mislukt: {errors} aanbevelingen")
    print("\nVolgende stap: 4 (embedden).\n")


if __name__ == "__main__":
    main()
