"""
Step 5: Upload embeddings to MongoDB Atlas

Input:  data/embeddings.json
Output: documents inserted into MongoDB collection

Expects a MongoDB Atlas connection string with a collection that has a
vector search index named 'vector_index' on the 'embedding' field
(3072 dimensions, cosine similarity — text-embedding-3-large).

Required environment variables:
  MONGODB_URI   — MongoDB Atlas connection string
                  e.g. mongodb+srv://user:pass@cluster.mongodb.net/

Optional environment variables:
  MONGODB_DB    — database name (default: rag_db)
  MONGODB_COLL  — collection name (default: rag_chunks)
"""

import json
import os
import sys
from pathlib import Path

try:
    from pymongo import MongoClient, UpdateOne
    from pymongo.errors import BulkWriteError
except ImportError:
    print("ERROR: pymongo is not installed. Run: pip install pymongo")
    sys.exit(1)

PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = Path(os.getenv("RAG_DATA_DIR", str(PROJECT_ROOT / "data")))
INPUT_JSON = DATA_DIR / "embeddings.json"

BATCH_SIZE = 100


def main() -> None:
    uri = os.getenv("MONGODB_URI")
    if not uri:
        print("ERROR: MONGODB_URI environment variable is not set.")
        sys.exit(1)

    db_name = os.getenv("MONGODB_DB", "rag_db")
    coll_name = os.getenv("MONGODB_COLL", "rag_chunks")

    if not INPUT_JSON.exists():
        print(f"ERROR: {INPUT_JSON} not found. Run step 4 first.")
        sys.exit(1)

    print(f"Loading documents from: {INPUT_JSON}")
    documents = json.loads(INPUT_JSON.read_text(encoding="utf-8"))
    print(f"Loaded {len(documents)} documents.")

    print(f"Connecting to MongoDB...")
    client = MongoClient(uri, serverSelectionTimeoutMS=10_000)

    # Ping to verify connection
    try:
        client.admin.command("ping")
        print("Connected to MongoDB.")
    except Exception as e:
        print(f"ERROR: Could not connect to MongoDB: {e}")
        sys.exit(1)

    collection = client[db_name][coll_name]

    # Upsert in batches (idempotent — safe to re-run)
    inserted = 0
    updated = 0
    errors = 0

    batches = [documents[i:i + BATCH_SIZE] for i in range(0, len(documents), BATCH_SIZE)]

    for batch_num, batch in enumerate(batches, start=1):
        ops = [
            UpdateOne(
                {"_id": doc["_id"]},
                {"$set": doc},
                upsert=True,
            )
            for doc in batch
        ]
        try:
            result = collection.bulk_write(ops, ordered=False)
            inserted += result.upserted_count
            updated += result.modified_count
            print(f"  Batch {batch_num}/{len(batches)}: {result.upserted_count} inserted, {result.modified_count} updated")
        except BulkWriteError as bwe:
            errors += len(bwe.details.get("writeErrors", []))
            print(f"  Batch {batch_num}/{len(batches)}: BulkWriteError — {bwe.details}")

    print(f"\nDone. Inserted: {inserted}, Updated: {updated}, Errors: {errors}")
    print(f"Collection: {db_name}.{coll_name}")
    print(
        "\nNext step: Create a vector search index in MongoDB Atlas on the 'embedding' field:\n"
        "  - Index name : vector_index\n"
        "  - Field      : embedding\n"
        "  - Dimensions : 3072\n"
        "  - Similarity : cosine\n"
    )

    client.close()


if __name__ == "__main__":
    main()
