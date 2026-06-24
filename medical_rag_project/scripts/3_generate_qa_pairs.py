"""
Step 3: Generate clinical QA pairs from guideline chunks

Input:  data/rag_chunks.json
Output: data/qa_pairs.json

Uses OpenAI gpt-4.1-mini to create physician-style Q&A pairs from each chunk.
Requires OPENAI_API_KEY environment variable.
"""

import json
import os
import re
import sys
from pathlib import Path

from openai import OpenAI
from tqdm import tqdm

PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = Path(os.getenv("RAG_DATA_DIR", str(PROJECT_ROOT / "data")))
INPUT_JSON = DATA_DIR / "rag_chunks.json"
OUTPUT_JSON = DATA_DIR / "qa_pairs.json"

MODEL = "gpt-4.1-mini"
MIN_CHUNK_LENGTH = 120  # characters

SYSTEM_PROMPT = """You are a medical knowledge extraction system.

Convert the following clinical guideline text into a concise clinical question and answer pair.

Rules:
- Question should be something a physician might ask
- Answer must be factual and based only on the text
- Keep answers concise (1-3 sentences)
- Use proper medical terminology

Return JSON only, no extra text:

{
  "question": "...",
  "answer": "..."
}"""


def generate_qa(client: OpenAI, chunk_text: str) -> dict | None:
    """Call OpenAI and return parsed {question, answer} or None on failure."""
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": chunk_text},
            ],
            temperature=0.2,
            max_tokens=300,
        )
        raw = response.choices[0].message.content.strip()

        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = re.sub(r"^```[a-z]*\n?", "", raw)
            raw = raw.rstrip("`").strip()

        return json.loads(raw)

    except json.JSONDecodeError as e:
        print(f"  [WARN] JSON parse error: {e} — skipping chunk")
        return None
    except Exception as e:
        print(f"  [ERROR] API call failed: {e} — skipping chunk")
        return None


def main() -> None:

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("ERROR: OPENAI_API_KEY environment variable is not set.")
        sys.exit(1)

    if not INPUT_JSON.exists():
        print(f"ERROR: {INPUT_JSON} not found. Run step 2 first.")
        sys.exit(1)

    client = OpenAI(api_key=api_key)

    print(f"Loading chunks from: {INPUT_JSON}")
    chunks = json.loads(INPUT_JSON.read_text(encoding="utf-8"))
    print(f"Loaded {len(chunks)} chunks.")

    # Filter out very short chunks
    eligible = [c for c in chunks if len(c["text"]) >= MIN_CHUNK_LENGTH]
    skipped = len(chunks) - len(eligible)
    print(f"Eligible chunks: {len(eligible)}  (skipped {skipped} too-short chunks)")

    qa_pairs: list[dict] = []
    errors = 0

    for chunk in tqdm(eligible, desc="Generating QA pairs"):
        result = generate_qa(client, chunk["text"])
        if result is None:
            errors += 1
            continue

        qa_pairs.append({
            "question": result.get("question", ""),
            "answer": result.get("answer", ""),
            "metadata": {
                "chunk_id": chunk["id"],
                "disease": chunk["metadata"].get("disease", "general"),
                "topic": chunk["metadata"].get("topic", "general"),
                "type": chunk["metadata"].get("type", "guideline_text"),
                "source": chunk["metadata"].get("source", ""),
                "section": chunk["metadata"].get("section", ""),
            },
        })

    OUTPUT_JSON.write_text(json.dumps(qa_pairs, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nSaved {len(qa_pairs)} QA pairs to: {OUTPUT_JSON}")
    if errors:
        print(f"Skipped due to errors: {errors}")
    print("Done.")


if __name__ == "__main__":
    main()
