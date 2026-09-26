"""
Stap 5: Upload de geembedde aanbevelingen en Q&A-vragen naar MongoDB Atlas.

Input:  normalized/<slug>.embeddings.json      -> rag_db.rag_chunks
        normalized/<slug>.qa-embeddings.json   -> rag_db.qa_pairs

VEILIGHEID
----------
* Vanaf de CLI draait dit standaard als DRY RUN; --write schrijft echt.
  Gestart vanuit de RAGCreator-UI (herkenbaar aan RAG_DATA_DIR) is het indrukken
  van de uploadknop zelf de bevestiging, dus dan wordt er wel geschreven.
  --dry-run forceert altijd een proefdraai.
* Uploadt alleen wat de goedkeuringspoort is gepasseerd (upload_eligible).
  De poort wordt hier nogmaals gecontroleerd, niet alleen in stap 4.
* Upsert op de stabiele ID's uit stap 0, dus opnieuw draaien maakt geen
  duplicaten en overschrijft geen andere richtlijn.
* Synchroniseert de poort ook naar de database: een aanbeveling die in dit
  project bestaat maar niet (meer) goedgekeurd is, wordt verwijderd, net als
  Q&A-vragen die niet in deze upload zitten (wees, of gemaakt voor een oudere
  tekst van de aanbeveling). Anders blijft een intrekking in de UI zonder
  effect op de RAG.
* Documenten van deze richtlijn die helemaal niet in het project voorkomen
  (bijv. handmatig of door een ander script toegevoegd) blijven staan; die ruim
  je bewust op met --prune (toont eerst wat er weg zou gaan).

Vereiste omgevingsvariabelen:
  MONGODB_URI    - Atlas connection string
Optioneel:
  MONGODB_DB     - database (default: rag_db)
  MONGODB_COLL   - collectie voor aanbevelingen (default: rag_chunks)
  MONGODB_QA_COLL- collectie voor Q&A-vragen   (default: qa_pairs)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from pipeline_common import (  # noqa: E402
    PipelineError, chunk_embeddings_path, die, eligible_only, ensure_normalized,
    qa_embeddings_path, split_qa_by_freshness,
)

try:
    from pymongo import MongoClient, UpdateOne
    from pymongo.errors import BulkWriteError
except ImportError:
    die("pymongo is niet geinstalleerd. Draai: pip install pymongo")

BATCH_SIZE = 100


def upsert(collection, docs: list[dict], label: str) -> None:
    inserted = updated = errors = 0
    batches = [docs[i:i + BATCH_SIZE] for i in range(0, len(docs), BATCH_SIZE)]
    for num, batch in enumerate(batches, start=1):
        ops = [UpdateOne({"_id": d["_id"]}, {"$set": d}, upsert=True) for d in batch]
        try:
            r = collection.bulk_write(ops, ordered=False)
            inserted += r.upserted_count
            updated += r.modified_count
            print(f"    batch {num}/{len(batches)}: "
                  f"{r.upserted_count} nieuw, {r.modified_count} bijgewerkt")
        except BulkWriteError as e:
            errors += len(e.details.get("writeErrors", []))
            print(f"    batch {num}/{len(batches)}: FOUT - {e.details}")
    print(f"  {label}: {inserted} nieuw, {updated} bijgewerkt"
          + (f", {errors} fouten" if errors else ""))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true",
                    help="forceer uploaden")
    ap.add_argument("--dry-run", action="store_true",
                    help="forceer proefdraai, ook vanuit de RAGCreator-UI")
    ap.add_argument("--prune", action="store_true",
                    help="verwijder documenten van deze richtlijn die niet meer "
                         "in de bron staan")
    args = ap.parse_args()

    # De UI kan geen argumenten meegeven, maar zet wel RAG_DATA_DIR. Daar op
    # afgaan houdt de knop bruikbaar zonder de CLI onbedoeld te laten schrijven.
    from_ui = bool(os.getenv("RAG_DATA_DIR"))
    if args.dry_run:
        do_write, why = False, "--dry-run opgegeven"
    elif args.write:
        do_write, why = True, "--write opgegeven"
    elif from_ui:
        do_write, why = True, "gestart vanuit RAGCreator (uploadknop)"
    else:
        do_write, why = False, "CLI zonder --write"

    uri = os.getenv("MONGODB_URI")
    if not uri:
        die("MONGODB_URI is niet gezet.")

    db_name = os.getenv("MONGODB_DB", "rag_db")
    coll_name = os.getenv("MONGODB_COLL", "rag_chunks")
    qa_coll_name = os.getenv("MONGODB_QA_COLL", "qa_pairs")

    try:
        key, entry, normalised = ensure_normalized()
    except PipelineError as e:
        die(str(e))

    eligible = eligible_only(normalised)
    chunk_file = chunk_embeddings_path(entry)
    if chunk_file.exists():
        chunk_docs = json.loads(chunk_file.read_text(encoding="utf-8"))
    elif eligible:
        die(f"{chunk_file} bestaat niet. Draai eerst stap 4 (embedden).")
    else:
        chunk_docs = []          # niets goedgekeurd: alleen opruimen
    qa_file = qa_embeddings_path(entry)
    qa_docs = json.loads(qa_file.read_text(encoding="utf-8")) if qa_file.exists() else []

    # Poort opnieuw controleren: stap 4 filtert al, maar embeddings.json kan
    # ouder zijn dan een recente afkeuring in de UI.
    allowed = {c["id"] for c in normalised if c["metadata"].get("upload_eligible")}
    blocked = [d for d in chunk_docs if d["_id"] not in allowed]
    if blocked:
        print(f"\n  {len(blocked)} chunk(s) uit {chunk_file.name} zijn intussen "
              f"afgekeurd of ingetrokken en worden NIET geupload.")
        chunk_docs = [d for d in chunk_docs if d["_id"] in allowed]

    # Q&A alleen als de aanbeveling nog precies de tekst heeft waarvoor de vraag
    # gemaakt is. Stap 4 controleert dit ook, maar qa-embeddings.json kan ouder
    # zijn dan een bewerking in de UI.
    uploaded = {d["_id"] for d in chunk_docs}
    qa_docs, qa_stale, qa_orphan = split_qa_by_freshness(
        qa_docs, [c for c in eligible if c["id"] in uploaded])
    if qa_stale or qa_orphan:
        print(f"\n  {len(qa_stale) + len(qa_orphan)} Q&A-vraag/vragen worden NIET "
              f"geupload: {len(qa_stale)} horen bij een gewijzigde aanbeveling, "
              f"{len(qa_orphan)} bij een aanbeveling die niet mee gaat. "
              f"Draai stap 3 en 4 opnieuw.")

    prefix = f"{entry['slug']}_{entry['year']}_"
    stray = [d["_id"] for d in chunk_docs if not str(d["_id"]).startswith(prefix)]
    if stray:
        die(f"{len(stray)} document(en) hebben niet het verwachte ID-voorvoegsel "
            f"'{prefix}': {', '.join(map(str, stray[:3]))}. "
            f"Draai stap 4 opnieuw.")

    mode = "UPLOADEN" if do_write else "DRY RUN (er wordt niets geschreven)"
    print(f"\n{'=' * 74}")
    print(f"  Stap 5 - upload {key}   [{mode}]")
    print(f"{'=' * 74}\n")
    print(f"  Modus       : {why}")
    print(f"  Doel        : {db_name}.{coll_name} + {db_name}.{qa_coll_name}")
    print(f"  ID-prefix   : {prefix}")
    print(f"  Aanbevelingen: {len(chunk_docs)}")
    print(f"  Q&A-vragen   : {len(qa_docs)}")
    if chunk_docs:
        dims = len(chunk_docs[0].get("embedding") or [])
        print(f"  Dimensies    : {dims}")
        if dims != 3072:
            die(f"Onverwachte embeddingdimensie {dims}; de Atlas vector_index "
                f"verwacht 3072. Controleer OPENAI_EMBEDDING_MODEL.")

    client = MongoClient(uri, serverSelectionTimeoutMS=10_000)
    try:
        client.admin.command("ping")
    except Exception as e:                                        # noqa: BLE001
        die(f"Kan niet verbinden met MongoDB: {e}")

    coll = client[db_name][coll_name]
    qa_coll = client[db_name][qa_coll_name]

    existing = coll.count_documents({"metadata.guideline_id": entry["slug"]})
    existing_qa = qa_coll.count_documents({"metadata.guideline_id": entry["slug"]})
    print(f"\n  Al aanwezig voor deze richtlijn: {existing} aanbevelingen, "
          f"{existing_qa} Q&A-vragen")
    print(f"  Totaal in {coll_name}: {coll.count_documents({})}")

    # ── Wat moet eruit? ──────────────────────────────────────────────────────
    keep = {d["_id"] for d in chunk_docs}
    keep_qa = {d["_id"] for d in qa_docs}
    in_project = {c["id"] for c in normalised}
    in_db = [d["_id"] for d in coll.find(
        {"metadata.guideline_id": entry["slug"]}, {"_id": 1})]
    # Bestaat in het project, maar mag niet (meer) in de database.
    revoked = [i for i in in_db if i in in_project and i not in keep]
    # Komt helemaal niet uit dit project: alleen met --prune.
    foreign = [i for i in in_db if i not in in_project and i not in keep]
    to_delete = revoked + (foreign if args.prune else [])
    stale_qa = [d["_id"] for d in qa_coll.find(
        {"$or": [{"metadata.guideline_id": entry["slug"]},
                 {"chunk_id": {"$in": in_db}}]}, {"_id": 1})
        if d["_id"] not in keep_qa]

    def show(label: str, ids: list) -> None:
        print(f"\n  {label}: {len(ids)}")
        for i in ids[:10]:
            print(f"      {i}")
        if len(ids) > 10:
            print(f"      ... en nog {len(ids) - 10}")

    if revoked:
        show("Niet (meer) goedgekeurd, wordt verwijderd", revoked)
    if stale_qa:
        show("Q&A-vragen die niet (meer) kloppen, worden verwijderd", stale_qa)
    if foreign:
        if args.prune:
            show("--prune: niet in project, wordt verwijderd", foreign)
        else:
            show("Staan wel in de database maar niet in dit project "
                 "(blijven staan; opruimen met --prune)", foreign)

    if not do_write:
        print(f"\n  DRY RUN - er is niets geschreven.")
        print(f"  Draai met --write om te uploaden.\n")
        client.close()
        return

    print()
    if chunk_docs:
        upsert(coll, chunk_docs, "Aanbevelingen")
    if qa_docs:
        upsert(qa_coll, qa_docs, "Q&A-vragen")

    if to_delete:
        coll.delete_many({"_id": {"$in": to_delete}})
        print(f"  Verwijderd: {len(to_delete)} aanbevelingen")
    if stale_qa or to_delete:
        r = qa_coll.delete_many({"$or": [{"_id": {"$in": stale_qa}},
                                         {"chunk_id": {"$in": to_delete}}]})
        print(f"  Verwijderd: {r.deleted_count} Q&A-vragen")

    print(f"\n  Totaal nu in {coll_name}: {coll.count_documents({})}")
    print(f"  Totaal nu in {qa_coll_name}: {qa_coll.count_documents({})}")

    if qa_docs and qa_coll.count_documents({}) == len(qa_docs):
        print(f"\n  LET OP: {qa_coll_name} is nieuw. Maak in Atlas een vector "
              f"search index aan:")
        print(f"     naam       : qa_vector_index")
        print(f"     veld       : embedding  (3072 dims, cosine)")
        print(f"     filtervelden: metadata.disease, metadata.topic, "
              f"metadata.guideline_id")
        print(f"     of draai: node scripts/setup-vector-index.js  (clinicaiderserver)")

    client.close()
    print()


if __name__ == "__main__":
    main()
