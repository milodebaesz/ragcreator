"""
Stap 4: Embed de goedgekeurde aanbevelingen en hun Q&A-vragen.

Input:  normalized/<slug>.chunks.json   (via ensure_normalized)
        normalized/<slug>.qa.json       (optioneel, uit stap 3)
Output: normalized/<slug>.embeddings.json
        normalized/<slug>.qa-embeddings.json

TWEE ZOEKINGANGEN
-----------------
De aanbeveling wordt geembed zoals hij is; de Q&A-vragen worden apart geembed.
Bij retrieval doorzoek je beide, maar een Q&A-treffer levert altijd de
bovenliggende aanbeveling terug (parent-document retrieval). Zo profiteer je van
vraag-tegen-vraag-matching zonder gegenereerde tekst aan het model te voeren.

Alleen chunks met upload_eligible=true worden geembed. Afgekeurde en
onbeoordeelde chunks kosten zo geen geld en kunnen niet per ongeluk meeliften.

Hergebruikt bestaande embeddings: bij opnieuw draaien worden alleen chunks
opnieuw geembed waarvan de tekst is gewijzigd (vergelijking op hash).
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from pipeline_common import (  # noqa: E402
    PipelineError, chunk_embeddings_path, die, eligible_only, ensure_normalized,
    explain_skipped, qa_embeddings_path, qa_path, split_qa_by_freshness,
)

try:
    from openai import OpenAI
except ImportError:
    die("openai is niet geinstalleerd. Draai: pip install openai")

try:
    from tqdm import tqdm
except ImportError:
    def tqdm(x, **k):                                   # type: ignore
        return x

EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-large")
BATCH_SIZE = 50


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def load_existing(path: Path) -> dict[str, dict]:
    """Bestaande embeddings op _id, om onnodig opnieuw embedden te voorkomen."""
    if not path.exists():
        return {}
    try:
        return {d["_id"]: d for d in json.loads(path.read_text(encoding="utf-8"))}
    except (json.JSONDecodeError, KeyError, TypeError):
        return {}


def embed_batch(client: OpenAI, texts: list[str]) -> list[list[float]]:
    response = client.embeddings.create(model=EMBEDDING_MODEL, input=texts)
    return [item.embedding for item in response.data]


def embed_all(client: OpenAI, items: list[dict], existing: dict[str, dict],
              label: str) -> tuple[list[dict], int, int]:
    """
    items: [{_id, embed_text, payload}]
    Geeft (documenten, aantal_nieuw, aantal_hergebruikt).
    """
    todo, out, reused = [], [], 0

    for it in items:
        h = text_hash(it["embed_text"])
        prev = existing.get(it["_id"])
        if prev and prev.get("hash") == h and prev.get("embedding"):
            out.append({**it["payload"], "_id": it["_id"],
                        "embedding": prev["embedding"], "hash": h,
                        "embedding_model": prev.get("embedding_model", EMBEDDING_MODEL)})
            reused += 1
        else:
            todo.append((it, h))

    if todo:
        batches = [todo[i:i + BATCH_SIZE] for i in range(0, len(todo), BATCH_SIZE)]
        for batch in tqdm(batches, desc=f"{label} embedden"):
            try:
                vectors = embed_batch(client, [it["embed_text"] for it, _ in batch])
            except Exception as e:                                # noqa: BLE001
                die(f"Embedding mislukt: {e}")
            for (it, h), vec in zip(batch, vectors):
                out.append({**it["payload"], "_id": it["_id"],
                            "embedding": vec, "hash": h,
                            "embedding_model": EMBEDDING_MODEL})

    return out, len(todo), reused


def main() -> None:
    if not os.getenv("OPENAI_API_KEY"):
        die("OPENAI_API_KEY is niet gezet.")

    try:
        key, entry, normalised = ensure_normalized()
    except PipelineError as e:
        die(str(e))

    eligible = eligible_only(normalised)
    skipped = explain_skipped(normalised)

    print(f"\nEmbeddingmodel: {EMBEDDING_MODEL}")
    print(f"Goedgekeurd voor upload: {len(eligible)} van {len(normalised)}")
    for reason, n in skipped.most_common():
        print(f"  overgeslagen: {n}x {reason}")

    if not eligible:
        print("\nNiets te embedden. Beoordeel chunks in de RAGCreator-UI of pas "
              "upload_policy aan in guidelines_registry.json.\n")
        return

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    # ── Aanbevelingen ────────────────────────────────────────────────────────
    # De tabeltitel wordt meegegeven voor context bij het embedden, maar niet
    # opgeslagen in het getoonde text-veld.
    chunk_items = []
    for c in eligible:
        title = c["metadata"].get("table_title")
        chunk_items.append({
            "_id": c["id"],
            "embed_text": f"{title}\n\n{c['text']}" if title else c["text"],
            "payload": {"text": c["text"], "metadata": c["metadata"]},
        })

    chunk_out = chunk_embeddings_path(entry)
    chunk_docs, new_c, reused_c = embed_all(
        client, chunk_items, load_existing(chunk_out), "Aanbevelingen")
    chunk_out.write_text(json.dumps(chunk_docs, ensure_ascii=False), encoding="utf-8")
    print(f"\nGeschreven: {chunk_out.name}  ({len(chunk_docs)} docs; "
          f"{new_c} nieuw, {reused_c} hergebruikt)")

    # ── Q&A-vragen ───────────────────────────────────────────────────────────
    qa_src = qa_path(entry)
    if not qa_src.exists():
        print(f"\nGeen {qa_src.name} gevonden - stap 3 (Q&A) is niet gedraaid.")
        print("Dat mag: je uploadt dan alleen de aanbevelingen. Draai stap 3 "
              "eerst als je vraag-tegen-vraag-retrieval wilt.\n")
        return

    pairs = json.loads(qa_src.read_text(encoding="utf-8"))
    # Een Q&A-paar mag alleen mee als de aanbeveling nog goedgekeurd is EN nog
    # dezelfde tekst heeft als toen de vragen gemaakt werden. Anders ontstaat er
    # een zoekingang naar een ingetrokken of inmiddels andere aanbeveling.
    usable, stale, orphans = split_qa_by_freshness(pairs, eligible)

    if orphans:
        print(f"\n{len(orphans)} Q&A-paren overgeslagen: bovenliggende aanbeveling "
              f"niet (meer) goedgekeurd.")
    if stale:
        n_chunks = len({p["chunk_id"] for p in stale})
        print(f"\n{len(stale)} Q&A-paren overgeslagen: {n_chunks} aanbeveling(en) "
              f"gewijzigd sinds de vragen gemaakt zijn (of paren van voor de "
              f"herkomstcontrole). Draai stap 3 opnieuw; die maakt alleen voor "
              f"deze aanbevelingen nieuwe vragen.")

    if not usable:
        print("Geen bruikbare Q&A-paren.\n")
        return

    qa_items = [{
        "_id": p["id"],
        "embed_text": p["question"],      # de VRAAG wordt geembed, niet het antwoord
        "payload": {
            "question": p["question"], "answer": p.get("answer", ""),
            "chunk_id": p["chunk_id"], "lang": p.get("lang", "en"),
            "source_hash": p["source_hash"],
            "metadata": p.get("metadata", {}),
        },
    } for p in usable]

    qa_out = qa_embeddings_path(entry)
    qa_docs, new_q, reused_q = embed_all(
        client, qa_items, load_existing(qa_out), "Q&A-vragen")
    qa_out.write_text(json.dumps(qa_docs, ensure_ascii=False), encoding="utf-8")
    print(f"Geschreven: {qa_out.name}  ({len(qa_docs)} docs; "
          f"{new_q} nieuw, {reused_q} hergebruikt)")

    print(f"\nKlaar. Volgende stap: 5 (uploaden naar MongoDB).\n")


if __name__ == "__main__":
    main()
