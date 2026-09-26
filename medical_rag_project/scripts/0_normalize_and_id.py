"""
Step 0: Normalise metadata and assign globally stable chunk IDs.

Input:  guidelines_registry.json  +  <source>/rag_chunks.json  per guideline
Output: normalized/<slug>.chunks.json  +  normalized/MANIFEST.{json,md}

WHY THIS EXISTS
---------------
Every guideline numbers its chunks from scratch as rec_1, rec_2, ... Across the
five projects that is 562 rows but only 191 distinct ids: 124 collide. Because
5_upload_to_mongodb.py upserts on _id, uploading a second guideline silently
overwrites the first. This script gives every chunk an id that is unique across
guidelines, deterministic (re-runnable without creating duplicates) and readable:

    rec_1  in ESC Hartfalen 2026   ->   esc-hf_2026_rec_1

THIS SCRIPT NEVER TOUCHES MONGODB.
It writes normalised files and a manifest to disk. Uploading is a separate,
explicit step that reads the manifest. Nothing reaches the database that you
have not seen in MANIFEST.md first.

Usage:
    python3 scripts/0_normalize_and_id.py                    # dry run, report only
    python3 scripts/0_normalize_and_id.py --write            # write normalized/
    python3 scripts/0_normalize_and_id.py --project "ESC Hartfalen" --write
    python3 scripts/0_normalize_and_id.py --verbose          # per-chunk detail

Exit codes:
    0  clean
    1  configuration or input error
    2  id collisions remain after normalisation (must never happen)
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from pipeline_common import (  # noqa: E402
    APPROVED, REJECTED, UNREVIEWED, OUTPUT_DIR, PROJECT_ROOT,
    PipelineError, chunks_path, load_registry, normalize_project,
)


def render_markdown(results: list[dict], totals: Counter) -> str:
    L: list[str] = []
    L.append("# Uploadmanifest \u2014 richtlijnen naar rag_db\n")
    L.append("Gegenereerd door `scripts/0_normalize_and_id.py`. **Dit bestand is de "
             "controlelijst: alleen wat hieronder onder _Upload_ staat, gaat naar "
             "de database.**\n")
    L.append(f"**Totaal:** {totals['eligible']} van {totals['total']} chunks komen in "
             f"aanmerking voor upload.\n")
    L.append("| Richtlijn | Bron | Policy | Chunks | \u2705 Upload | \u23f8 Onbeoordeeld | \u26d4 Afgekeurd |")
    L.append("|---|---|---|---:|---:|---:|---:|")
    for r in results:
        if r["skipped"]:
            L.append(f"| {r['key']} | `{r['source']}` | _{r['reason']}_ | \u2013 | \u2013 | \u2013 | \u2013 |")
            continue
        L.append(f"| {r['key']} | `{r['source']}` | {r['policy']} | {r['total']} | "
                 f"**{r['eligible']}** | {r['unreviewed']} | {r['rejected']} |")
    L.append("")
    for r in results:
        if r["skipped"]:
            continue
        L.append(f"## {r['key']}  \u00b7  `{r['slug']}_{r['year']}_*`\n")
        L.append(f"- Bron: `{r['source']}/rag_chunks.json`")
        L.append(f"- Policy: **{r['policy']}**")
        L.append(f"- Wordt geupload: **{r['eligible']} / {r['total']}**")
        if r["note"]:
            L.append(f"- Notitie: {r['note']}")
        if r["eligible"] == 0:
            L.append(f"\n> \u26a0\ufe0f **Er wordt niets geupload voor deze richtlijn.** {r['zero_hint']}")
        if r["warnings"]:
            L.append("\n<details><summary>Normalisatiemeldingen</summary>\n")
            for w, n in sorted(r["warnings"].items(), key=lambda x: -x[1]):
                L.append(f"- `{w}` \u00d7 {n}")
            L.append("\n</details>")
        L.append("")
    L.append("---\n\n## Volgende stap\n")
    L.append("Klopt dit? Dan pas uploaden (stap 4 en 5 in RAGCreator). Wil je meer of "
             "minder meenemen, pas dan `guidelines_registry.json` aan (`include`, "
             "`upload_policy`) of beoordeel chunks in de UI, en draai dit opnieuw.\n")
    return "\n".join(L)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true",
                    help="schrijf normalized/ weg (zonder deze vlag: alleen rapport)")
    ap.add_argument("--project", action="append", default=None,
                    help="beperk tot deze richtlijn (mag meerdere keren)")
    ap.add_argument("--verbose", action="store_true", help="toon meldingen per richtlijn")
    args = ap.parse_args()

    try:
        guidelines, _ = load_registry()
    except PipelineError as e:
        print(f"FOUT: {e}", file=sys.stderr)
        sys.exit(1)

    if args.project:
        unknown = [p for p in args.project if p not in guidelines]
        if unknown:
            print(f"FOUT: onbekende richtlijn(en): {', '.join(unknown)}", file=sys.stderr)
            print(f"Bekend: {', '.join(guidelines)}", file=sys.stderr)
            sys.exit(1)
        guidelines = {k: v for k, v in guidelines.items() if k in args.project}

    mode = "SCHRIJVEN" if args.write else "DRY RUN (geen bestanden geschreven)"
    print(f"\n{'=' * 74}\n  Stap 0 \u2014 normaliseren en stabiele ID's   [{mode}]\n{'=' * 74}\n")

    results: list[dict] = []
    all_ids: dict[str, str] = {}
    collisions: list[tuple[str, str, str]] = []
    totals = Counter()
    to_write: dict[Path, list[dict]] = {}

    for key, entry in guidelines.items():
        if not entry.get("include", False):
            print(f"  \u26d4 {key:24s} overgeslagen (include=false)")
            results.append({"key": key, "source": entry["source"], "skipped": True,
                            "reason": "include=false"})
            continue
        try:
            normalised, warnings = normalize_project(key, entry)
        except PipelineError as e:
            print(f"  \u26a0\ufe0f  {key:24s} OVERGESLAGEN \u2014 {e}")
            results.append({"key": key, "source": entry["source"], "skipped": True,
                            "reason": str(e)})
            continue

        states = Counter(n["metadata"]["review_state"] for n in normalised)
        eligible = [n for n in normalised if n["metadata"]["upload_eligible"]]
        for n in normalised:
            if n["id"] in all_ids:
                collisions.append((n["id"], all_ids[n["id"]], key))
            else:
                all_ids[n["id"]] = key

        zero_hint = ""
        if not eligible:
            if states[UNREVIEWED] and entry["upload_policy"] == "approved_only":
                zero_hint = (f"Alle {states[UNREVIEWED]} chunks zijn nog niet beoordeeld. "
                             f"Beoordeel ze in de RAGCreator-UI, of zet `upload_policy` "
                             f"op `include_unreviewed`.")
            elif states[REJECTED]:
                zero_hint = "Alle chunks zijn afgekeurd in de UI."

        results.append({
            "key": key, "source": entry["source"], "slug": entry["slug"],
            "year": entry["year"], "policy": entry["upload_policy"], "skipped": False,
            "total": len(normalised), "eligible": len(eligible),
            "approved": states[APPROVED], "unreviewed": states[UNREVIEWED],
            "rejected": states[REJECTED], "warnings": dict(warnings),
            "note": entry.get("note", ""), "zero_hint": zero_hint,
        })
        totals["total"] += len(normalised)
        totals["eligible"] += len(eligible)
        totals["unreviewed"] += states[UNREVIEWED]
        totals["rejected"] += states[REJECTED]

        print(f"  {'\u2705' if eligible else '\u26a0\ufe0f '} {key:24s} {len(normalised):4d} chunks \u2192 "
              f"{len(eligible):4d} upload  (\u23f8 {states[UNREVIEWED]}  \u26d4 {states[REJECTED]})"
              f"   [{entry['upload_policy']}]")
        if args.verbose and warnings:
            for w, n in sorted(warnings.items(), key=lambda x: -x[1]):
                print(f"       \u00b7 {w} \u00d7 {n}")
        to_write[chunks_path(entry)] = normalised

    print(f"\n{'-' * 74}")
    if collisions:
        print(f"  \u274c {len(collisions)} ID-BOTSING(EN) NA NORMALISATIE \u2014 dit mag nooit.\n")
        for nid, a, b in collisions[:20]:
            print(f"       {nid}  \u2190  {a}  \u00e9n  {b}")
        print("\n  Oorzaak is vrijwel zeker twee registry-entries met dezelfde slug+jaar.")
        print("  Niets geschreven. Corrigeer guidelines_registry.json.\n")
        sys.exit(2)

    active = len([r for r in results if not r["skipped"]])
    print(f"  \u2705 Geen ID-botsingen. {len(all_ids)} unieke ID's over {active} richtlijnen.")
    print(f"  \U0001f4cb {totals['eligible']} van {totals['total']} chunks komen in aanmerking voor upload.")
    if totals["rejected"]:
        print(f"     \u26d4 {totals['rejected']} afgekeurd \u2014 gaan nooit mee.")
    if totals["unreviewed"]:
        print(f"     \u23f8  {totals['unreviewed']} nog niet beoordeeld.")

    if not args.write:
        print(f"\n  DRY RUN \u2014 niets geschreven. Draai met --write.\n")
        return

    OUTPUT_DIR.mkdir(exist_ok=True)
    for path, data in to_write.items():
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"     geschreven: {path.relative_to(PROJECT_ROOT)}  ({len(data)} chunks)")

    manifest = {
        "generated_by": "scripts/0_normalize_and_id.py",
        "totals": dict(totals), "unique_ids": len(all_ids),
        "guidelines": [r for r in results if not r["skipped"]],
        "skipped": [r for r in results if r["skipped"]],
    }
    (OUTPUT_DIR / "MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    (OUTPUT_DIR / "MANIFEST.md").write_text(
        render_markdown(results, totals), encoding="utf-8")
    print("     geschreven: normalized/MANIFEST.json")
    print("     geschreven: normalized/MANIFEST.md   \u2190 lees dit voordat je uploadt")
    print("\n  Niets is naar MongoDB geschreven. Dat is een aparte, expliciete stap.\n")


if __name__ == "__main__":
    main()
