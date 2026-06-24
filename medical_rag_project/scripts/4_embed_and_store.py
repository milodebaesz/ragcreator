"""
Step 4: Generate embeddings and save to JSON (ready for MongoDB)

Input:  data/rag_chunks.json
Output: data/embeddings.json

Each document in embeddings.json has the structure that maps directly
to a MongoDB document — ready to insert with pymongo later.

Uses OpenAI text-embedding-3-large.
Requires OPENAI_API_KEY environment variable.
"""

import json
import os
import sys
from pathlib import Path

from openai import OpenAI
from tqdm import tqdm

PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = Path(os.getenv("RAG_DATA_DIR", str(PROJECT_ROOT / "data")))
INPUT_JSON = DATA_DIR / "rag_chunks.json"
OUTPUT_JSON = DATA_DIR / "embeddings.json"

EMBEDDING_MODEL = "text-embedding-3-large"
BATCH_SIZE = 50


def get_embeddings(client: OpenAI, texts: list[str]) -> list[list[float]]:
    response = client.embeddings.create(model=EMBEDDING_MODEL, input=texts)
    return [item.embedding for item in response.data]


def main() -> None:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("ERROR: OPENAI_API_KEY environment variable is not set.")
        sys.exit(1)

    if not INPUT_JSON.exists():
        print(f"ERROR: {INPUT_JSON} not found. Run step 2 first.")
        sys.exit(1)

    print(f"Loading chunks from: {INPUT_JSON}")
    chunks = json.loads(INPUT_JSON.read_text(encoding="utf-8"))
    print(f"Loaded {len(chunks)} chunks.")

    client = OpenAI(api_key=api_key)
    documents = []
    errors = 0

    batches = [chunks[i:i + BATCH_SIZE] for i in range(0, len(chunks), BATCH_SIZE)]

    for batch in tqdm(batches, desc="Embedding chunks"):
        texts = [c["text"] for c in batch]
        try:
            embeddings = get_embeddings(client, texts)
        except Exception as e:
            print(f"  [ERROR] Embedding batch failed: {e} — skipping")
            errors += len(batch)
            continue

        for chunk, embedding in zip(batch, embeddings):
            documents.append({
                "_id": chunk["id"],          # maps to MongoDB _id
                "text": chunk["text"],
                "embedding": embedding,      # list[float], 3072 dims
                "metadata": chunk["metadata"],
            })

    OUTPUT_JSON.write_text(json.dumps(documents, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nSaved {len(documents)} embedded documents to: {OUTPUT_JSON}")
    if errors:
        print(f"Skipped due to errors: {errors}")
    print("Each document is ready for MongoDB insertion (use pymongo collection.insert_many()).")
    print("Done.")


if __name__ == "__main__":
    main()
