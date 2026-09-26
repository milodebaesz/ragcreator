"""
Gedeelde pijplijnlogica: registry, normalisatie, stabiele ID's, goedkeuringspoort.

Eén bron van waarheid voor stap 0 (CLI), 3 (Q&A), 4 (embedden) en 5 (uploaden),
zodat die het nooit oneens kunnen zijn over welke chunk welk ID heeft of welke
chunk geupload mag worden.

Belangrijkste regels die hier worden afgedwongen:

  * ID's zijn globaal uniek en deterministisch:  {slug}_{year}_{origineel_id}
    Zonder dit overschrijft de tweede richtlijn de eerste (upsert op _id).

  * metadata.approved === false gaat NOOIT naar de database, ongeacht policy.
    Dat is bewust afgekeurd werk in de RAGCreator-UI.

  * De registry (guidelines_registry.json) is leidend en wordt nooit
    door scripts geschreven — alleen gelezen.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
REGISTRY_PATH = PROJECT_ROOT / "guidelines_registry.json"
OUTPUT_DIR = PROJECT_ROOT / "normalized"

# ── Gecontroleerde vocabulaires ──────────────────────────────────────────────
VALID_CLASSES = {"Class I", "Class IIa", "Class IIb", "Class III"}
# ESC 2026 (hartfalen) splitst niveau B in B1/B2; ACC/AHA-tabellen gebruiken NR
# voor non-randomised. Dat zijn echte niveaus, geen extractieruis — geverifieerd
# tegen het corpus: B1x32 en B2x7 in ESC Hartfalen, NRx5 in ESC ACS.
VALID_EVIDENCE = {"A", "B", "B1", "B2", "C", "NR"}
VALID_TOPICS = {
    "diagnosis", "treatment", "general", "risk_stratification",
    "screening", "follow_up", "lifestyle",
}
VALID_POLICIES = {"approved_only", "include_unreviewed", "blocked"}

TOPIC_ALIASES = {
    "diagnostics": "diagnosis",
    "management": "treatment",
    "therapy": "treatment",
    "followup": "follow_up",
    "follow-up": "follow_up",
    "riskstratification": "risk_stratification",
    "risk stratification": "risk_stratification",
}

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")

APPROVED = "approved"
REJECTED = "rejected"
UNREVIEWED = "unreviewed"


class PipelineError(RuntimeError):
    """Fout die de gebruiker moet zien en die de stap moet afbreken."""


# ── Goedkeuring ──────────────────────────────────────────────────────────────
def approval_state(meta: dict) -> str:
    raw = meta.get("approved")
    if raw is True:
        return APPROVED
    if raw is False:
        return REJECTED
    return UNREVIEWED


def is_eligible(state: str, policy: str) -> tuple[bool, str]:
    """(mag_geupload_worden, reden). REJECTED is nooit toegestaan."""
    if policy == "blocked":
        return False, "richtlijn staat op blocked"
    if state == REJECTED:
        return False, "afgekeurd in de UI (approved=false)"
    if state == APPROVED:
        return True, "goedgekeurd"
    if policy == "include_unreviewed":
        return True, "nog niet beoordeeld, toegelaten via include_unreviewed"
    return False, "nog niet beoordeeld (approved ontbreekt)"


# ── Normalisatie ─────────────────────────────────────────────────────────────
def normalise_topic(raw, warnings: Counter) -> str:
    if not raw or not str(raw).strip():
        warnings["topic_missing"] += 1
        return "general"
    t = str(raw).strip().lower().replace(" ", "_")
    t = TOPIC_ALIASES.get(t, t)
    if t not in VALID_TOPICS:
        warnings[f"topic_unknown:{t}"] += 1
        return "general"
    return t


def normalise_class(raw, warnings: Counter):
    """(waarde, afgekeurde_ruwe_waarde). Gooit nooit stilzwijgend iets weg."""
    if raw is None or not str(raw).strip():
        warnings["class_missing"] += 1
        return None, None
    c = re.sub(r"\s+", " ", str(raw).strip()).replace("Klasse", "Class")
    if not c.lower().startswith("class"):
        c = f"Class {c}"
    m = re.match(r"^class\s+(i{1,3}v?|iv)(a|b)?$", c.lower())
    if m:
        c = f"Class {m.group(1).upper()}{(m.group(2) or '').lower()}"
    if c not in VALID_CLASSES:
        warnings[f"class_invalid:{c}"] += 1
        return None, str(raw).strip()
    return c, None


def normalise_evidence(raw, warnings: Counter):
    if raw is None or not str(raw).strip():
        warnings["evidence_missing"] += 1
        return None, None
    e = str(raw).strip().upper()
    if e not in VALID_EVIDENCE:
        warnings[f"evidence_invalid:{e}"] += 1
        return None, str(raw).strip()
    return e, None


def normalise_chunk(chunk: dict, entry: dict, key: str, warnings: Counter) -> dict:
    meta = dict(chunk.get("metadata") or {})
    slug, year = entry["slug"], entry["year"]

    orig_id = str(chunk.get("id") or "").strip()
    if not orig_id:
        raise PipelineError(f"chunk zonder id in {key}")

    meta["topic"] = normalise_topic(meta.get("topic"), warnings)
    meta["class"], bad_class = normalise_class(meta.get("class"), warnings)
    meta["evidence"], bad_evidence = normalise_evidence(meta.get("evidence"), warnings)
    if bad_class:
        meta["class_raw"] = bad_class
    if bad_evidence:
        meta["evidence_raw"] = bad_evidence

    if meta.get("guideline") not in (None, "", entry["canonical_name"]):
        warnings[f"guideline_renamed:{meta.get('guideline')}->{entry['canonical_name']}"] += 1
    if not meta.get("guideline"):
        warnings["guideline_missing_filled_from_registry"] += 1
    if not meta.get("year"):
        warnings["year_missing_filled_from_registry"] += 1

    meta["guideline"] = entry["canonical_name"]
    meta["year"] = year
    meta["guideline_id"] = slug
    meta["source_project"] = key
    meta["original_id"] = orig_id

    if not meta.get("disease"):
        meta["disease"] = "general"
        warnings["disease_missing"] += 1
    if not meta.get("type"):
        meta["type"] = "recommendation"

    state = approval_state(meta)
    meta["approved"] = (state == APPROVED)
    meta["review_state"] = state

    ok, reason = is_eligible(state, entry["upload_policy"])
    meta["upload_eligible"] = ok
    meta["eligibility_reason"] = reason

    return {"id": f"{slug}_{year}_{orig_id}", "text": chunk.get("text", ""), "metadata": meta}


# ── Q&A-herkomst ────────────────────────────────────────────────────────────
def qa_source_hash(chunk: dict) -> str:
    """
    Vingerafdruk van alles wat stap 3 aan het model voert voor één aanbeveling.

    Wordt op elk Q&A-paar opgeslagen. Wijzigt de aanbeveling daarna (tekst
    bewerkt, samengevoegd, klasse aangepast), dan klopt de hash niet meer en
    weigeren stap 4 en 5 die vragen: ze zouden naar een andere tekst verwijzen
    dan waar ze voor gemaakt zijn.
    """
    meta = chunk.get("metadata") or {}
    basis = "\x1f".join(str(v or "") for v in (
        chunk.get("text"), meta.get("section"), meta.get("class"),
        meta.get("evidence"), meta.get("disease"), meta.get("topic"),
    ))
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


def split_qa_by_freshness(pairs: list[dict], chunks: list[dict]):
    """
    (actueel, verouderd, wees). Alleen `actueel` mag geembed of geupload worden.

      actueel  - bovenliggende aanbeveling bestaat en source_hash klopt
      verouderd- aanbeveling bestaat, maar is gewijzigd sinds de vragen gemaakt
                 zijn, of het paar heeft geen source_hash (van voor deze check)
      wees     - aanbeveling bestaat niet (meer) in de toegelaten set
    """
    hashes = {c["id"]: qa_source_hash(c) for c in chunks}
    fresh, stale, orphan = [], [], []
    for p in pairs:
        h = hashes.get(p.get("chunk_id"))
        if h is None:
            orphan.append(p)
        elif p.get("source_hash") == h:
            fresh.append(p)
        else:
            stale.append(p)
    return fresh, stale, orphan


# ── Registry ─────────────────────────────────────────────────────────────────
def load_registry() -> tuple[dict, str]:
    if not REGISTRY_PATH.exists():
        raise PipelineError(f"{REGISTRY_PATH} niet gevonden.")
    reg = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    guidelines = reg.get("guidelines") or {}
    if not guidelines:
        raise PipelineError("registry bevat geen 'guidelines'.")

    default_policy = (reg.get("defaults") or {}).get("upload_policy", "approved_only")
    if default_policy not in VALID_POLICIES:
        raise PipelineError(f"onbekende defaults.upload_policy '{default_policy}'.")

    seen: dict[str, str] = {}
    for key, e in guidelines.items():
        for field in ("slug", "canonical_name", "year", "source"):
            if not e.get(field):
                raise PipelineError(f"'{key}' mist verplicht veld '{field}'.")
        if not SLUG_RE.match(e["slug"]):
            raise PipelineError(f"'{key}' heeft ongeldige slug '{e['slug']}'.")
        e["year"] = str(e["year"])
        # slug+jaar samen vormen het ID-voorvoegsel; alleen die combinatie hoeft
        # uniek te zijn (dezelfde richtlijn in twee jaargangen mag).
        fp = f"{e['slug']}_{e['year']}"
        if fp in seen:
            raise PipelineError(
                f"slug+jaar '{fp}' wordt gedeeld door '{seen[fp]}' en '{key}'. "
                f"Dat zou ID's laten botsen."
            )
        seen[fp] = key
        policy = e.get("upload_policy", default_policy)
        if policy not in VALID_POLICIES:
            raise PipelineError(
                f"'{key}' heeft onbekende upload_policy '{policy}'. "
                f"Kies uit: {', '.join(sorted(VALID_POLICIES))}."
            )
        e["upload_policy"] = policy
    return guidelines, default_policy


def resolve_project_key(guidelines: dict, title: str | None = None) -> str:
    """
    Zoek de registry-sleutel voor het actieve project.

    De Tauri-backend zet RAG_PROJECT_TITLE op de projectnaam; die is gelijk aan
    de registry-sleutel. Valt terug op de mapnaam uit RAG_DATA_DIR.
    """
    title = title or os.getenv("RAG_PROJECT_TITLE")
    if title and title in guidelines:
        return title

    data_dir = os.getenv("RAG_DATA_DIR")
    if data_dir:
        folder = Path(data_dir).name
        for key, e in guidelines.items():
            if Path(e["source"]).name == folder or key == folder:
                return key

    raise PipelineError(
        f"Kan project '{title or data_dir or '?'}' niet vinden in "
        f"guidelines_registry.json.\nBekende projecten: {', '.join(guidelines)}"
    )


# ── Normaliseren van één richtlijn ───────────────────────────────────────────
def normalize_project(key: str, entry: dict) -> tuple[list[dict], Counter]:
    src = PROJECT_ROOT / entry["source"] / "rag_chunks.json"
    if not src.exists():
        raise PipelineError(
            f"{src} bestaat niet. Draai eerst stap 2 (structuur extractie)."
        )
    chunks = json.loads(src.read_text(encoding="utf-8"))
    warnings: Counter = Counter()
    normalised = [normalise_chunk(c, entry, key, warnings) for c in chunks]

    counts = Counter(n["id"] for n in normalised)
    dupes = [i for i, n in counts.items() if n > 1]
    if dupes:
        raise PipelineError(
            f"Dubbele ID's binnen {key}: {', '.join(sorted(set(dupes))[:5])}. "
            f"Controleer {src}."
        )
    return normalised, warnings


def chunks_path(entry: dict) -> Path:
    return OUTPUT_DIR / f"{entry['slug']}.chunks.json"


def qa_path(entry: dict) -> Path:
    return OUTPUT_DIR / f"{entry['slug']}.qa.json"


def chunk_embeddings_path(entry: dict) -> Path:
    return OUTPUT_DIR / f"{entry['slug']}.embeddings.json"


def qa_embeddings_path(entry: dict) -> Path:
    return OUTPUT_DIR / f"{entry['slug']}.qa-embeddings.json"


def ensure_normalized(title: str | None = None, verbose: bool = True):
    """
    Normaliseer het actieve project en schrijf normalized/<slug>.chunks.json.

    Idempotent en zonder API-calls, dus stap 3, 4 en 5 roepen dit aan het begin
    aan. Zo kan een stap nooit op verouderde of niet-genormaliseerde chunks
    draaien, ook niet als je ze in een andere volgorde start.

    Returns: (key, entry, normalised_chunks)
    """
    guidelines, _ = load_registry()
    key = resolve_project_key(guidelines, title)
    entry = guidelines[key]

    if not entry.get("include", False):
        raise PipelineError(
            f"'{key}' staat op include:false in guidelines_registry.json.\n"
            f"Zet include op true als deze richtlijn mee moet doen."
        )

    normalised, warnings = normalize_project(key, entry)
    OUTPUT_DIR.mkdir(exist_ok=True)
    chunks_path(entry).write_text(
        json.dumps(normalised, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    if verbose:
        eligible = sum(1 for n in normalised if n["metadata"]["upload_eligible"])
        print(f"[normalisatie] {key}: {len(normalised)} chunks, "
              f"{eligible} goedgekeurd voor upload  "
              f"(policy: {entry['upload_policy']}, prefix: {entry['slug']}_{entry['year']}_)")
        if warnings:
            for w, n in sorted(warnings.items(), key=lambda x: -x[1])[:6]:
                print(f"               · {w} x {n}")

    return key, entry, normalised


def eligible_only(chunks: list[dict]) -> list[dict]:
    return [c for c in chunks if c["metadata"].get("upload_eligible")]


def explain_skipped(chunks: list[dict]) -> Counter:
    return Counter(
        c["metadata"].get("eligibility_reason", "onbekend")
        for c in chunks if not c["metadata"].get("upload_eligible")
    )


def die(message: str) -> None:
    print(f"\nFOUT: {message}\n", file=sys.stderr)
    sys.exit(1)
