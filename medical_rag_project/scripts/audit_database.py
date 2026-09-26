"""
Controleer of de RAG-database alleen bevat wat de goedkeuringspoort toelaat.

Los van stap 0-5, want dit kijkt naar de DATABASE in plaats van naar een project:
ook documenten die ooit door een ander script (of met de hand) zijn toegevoegd.

Een aanbeveling hoort er alleen in als:
  * metadata.approved === true en review_state == "approved"
  * de richtlijn in guidelines_registry.json op include:true staat en de
    upload_policy dit document toelaat
  * hij niet samengevoegd is (metadata.status != "merged")

Een Q&A-vraag hoort er alleen in als:
  * de bovenliggende aanbeveling er (terecht) in staat
  * source_hash klopt met de huidige tekst van die aanbeveling

Standaard alleen rapporteren. Met --fix worden afwijkende documenten VERPLAATST
naar <collectie>_quarantine (eerst kopie, dan verwijderen) — niets gaat
definitief verloren; terugzetten kan met --restore.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from pipeline_common import (  # noqa: E402
    PipelineError, die, load_registry, qa_source_hash,
)

try:
    from pymongo import MongoClient
except ImportError:
    die("pymongo is niet geinstalleerd. Draai: pip install pymongo")


def chunk_problem(doc: dict, by_slug: dict) -> str | None:
    meta = doc.get("metadata") or {}
    entry = by_slug.get(meta.get("guideline_id"))
    if entry is None:
        return f"richtlijn '{meta.get('guideline_id')}' onbekend in registry"
    if not entry.get("include") or entry["upload_policy"] == "blocked":
        return "richtlijn staat op include:false of blocked"
    if meta.get("status") == "merged":
        return "samengevoegd in een andere aanbeveling (status=merged)"
    if meta.get("merged_from"):
        return "samenvoeging buiten de reviewworkflow (merged_from)"
    if meta.get("approved") is False:
        return "afgekeurd (approved=false)"
    if meta.get("approved") is not True:
        if entry["upload_policy"] == "include_unreviewed" and meta.get("review_state") == "unreviewed":
            return None
        return f"niet goedgekeurd (review_state={meta.get('review_state')})"
    return None


def move(src, dst, ids: list) -> int:
    moved = 0
    for i in range(0, len(ids), 100):
        batch = ids[i:i + 100]
        docs = list(src.find({"_id": {"$in": batch}}))
        for d in docs:
            dst.replace_one({"_id": d["_id"]}, d, upsert=True)
        # Pas verwijderen wat aantoonbaar in de doelcollectie staat.
        present = [d["_id"] for d in dst.find({"_id": {"$in": batch}}, {"_id": 1})]
        moved += src.delete_many({"_id": {"$in": present}}).deleted_count
    return moved


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fix", action="store_true",
                    help="verplaats afwijkende documenten naar *_quarantine")
    ap.add_argument("--restore", metavar="GUIDELINE_ID",
                    help="zet gequarantaineerde documenten van deze richtlijn terug")
    args = ap.parse_args()

    uri = os.getenv("MONGODB_URI") or die("MONGODB_URI is niet gezet.")
    db = MongoClient(uri, serverSelectionTimeoutMS=10_000)[os.getenv("MONGODB_DB", "rag_db")]
    coll = db[os.getenv("MONGODB_COLL", "rag_chunks")]
    qa_coll = db[os.getenv("MONGODB_QA_COLL", "qa_pairs")]
    q_coll, q_qa = db[f"{coll.name}_quarantine"], db[f"{qa_coll.name}_quarantine"]

    if args.restore:
        ids = [d["_id"] for d in q_coll.find({"metadata.guideline_id": args.restore}, {"_id": 1})]
        qa_ids = [d["_id"] for d in q_qa.find({"chunk_id": {"$in": ids}}, {"_id": 1})]
        print(f"Terugzetten: {move(q_coll, coll, ids)} aanbevelingen, "
              f"{move(q_qa, qa_coll, qa_ids)} Q&A-vragen")
        return

    try:
        guidelines, _ = load_registry()
    except PipelineError as e:
        die(str(e))
    by_slug = {e["slug"]: e for e in guidelines.values()}

    chunks = {d["_id"]: d for d in coll.find({}, {"embedding": 0})}
    bad_chunks: dict[str, str] = {}
    for _id, d in chunks.items():
        why = chunk_problem(d, by_slug)
        if why:
            bad_chunks[_id] = why

    bad_qa: dict[str, str] = {}
    for q in qa_coll.find({}, {"embedding": 0}):
        parent = chunks.get(q.get("chunk_id"))
        if parent is None:
            bad_qa[q["_id"]] = "aanbeveling bestaat niet"
        elif q.get("chunk_id") in bad_chunks:
            bad_qa[q["_id"]] = "aanbeveling wordt zelf gequarantaineerd"
        elif not q.get("source_hash"):
            bad_qa[q["_id"]] = "geen source_hash (herkomst onbekend)"
        elif q["source_hash"] != qa_source_hash({"text": parent.get("text"),
                                                 "metadata": parent.get("metadata")}):
            bad_qa[q["_id"]] = "aanbeveling gewijzigd sinds de vraag gemaakt is"

    per_gl = defaultdict(Counter)
    for _id, d in chunks.items():
        per_gl[(d.get("metadata") or {}).get("guideline_id")]["ok" if _id not in bad_chunks else "fout"] += 1

    print(f"\n{coll.name}: {len(chunks)} documenten")
    for gl, c in sorted(per_gl.items(), key=lambda x: str(x[0])):
        print(f"  {gl:<12} {c['ok']:>4} in orde   {c['fout']:>4} afwijkend")
    for why, n in Counter(bad_chunks.values()).most_common():
        print(f"    - {n}x {why}")

    print(f"\n{qa_coll.name}: {qa_coll.estimated_document_count()} documenten, "
          f"{len(bad_qa)} afwijkend")
    for why, n in Counter(bad_qa.values()).most_common():
        print(f"    - {n}x {why}")

    if not bad_chunks and not bad_qa:
        print("\nDatabase is schoon.\n")
        return
    if not args.fix:
        print(f"\nAlleen gerapporteerd. Draai met --fix om te verplaatsen naar "
              f"{q_coll.name} / {q_qa.name}.\n")
        return

    n_qa = move(qa_coll, q_qa, list(bad_qa))
    n_c = move(coll, q_coll, list(bad_chunks))
    print(f"\nVerplaatst: {n_c} aanbevelingen -> {q_coll.name}, "
          f"{n_qa} Q&A-vragen -> {q_qa.name}")
    print(f"Nu in {coll.name}: {coll.count_documents({})}, "
          f"{qa_coll.name}: {qa_coll.count_documents({})}\n")


if __name__ == "__main__":
    main()
