# RAG-integratieplan: RAGCreator → clinicaiderserver → Anamnesis

**Datum:** 12 september 2026
**Scope:** `RAGCreator` (databron) · `clinicaiderserver` (retrieval + API) · `anamnesis-clean` (UI)

---

## 0. Kernconclusie in vijf zinnen

Je hebt **562 geëxtraheerde richtlijn-aanbevelingen** in RAGCreator staan, maar er zitten er **222 in productie — allemaal uit één richtlijn (ESC CCS 2024)**. De andere vier richtlijnen (hartfalen, kleplijden, syncope, longembolie) worden nooit opgehaald door de anamnese-app. De reden dat je ze niet hebt kunnen toevoegen is een **ID-botsing**: elke richtlijn nummert zijn chunks opnieuw als `rec_1, rec_2, …`, en het uploadscript gebruikt dat als MongoDB `_id`, dus richtlijn 2 overschrijft richtlijn 1 stilzwijgend. Daarnaast doet de retrieval een **volledige collectiescan met cosine-similarity in JavaScript**, terwijl er al een werkende Atlas `vector_index` klaarstaat die niet wordt gebruikt. De 105 gegenereerde **Q&A-paren worden nergens opgeslagen of gebruikt** — terwijl juist die het gemeten similariteitsprobleem (max ~0,51–0,54) zouden oplossen.

**Volgorde die het meeste oplevert:** eerst ID's stabiliseren (anders vernietig je data), dan alles uploaden, dan `$vectorSearch` aanzetten, dan Q&A-paren als tweede zoeklaag, dan citaties in de UI.

---

## 1. Inventarisatie — wat heb je precies?

### 1.1 De databron (RAGCreator)

`medical_rag_project/projects/` — de actieve, meest recente extracties:

| Project | Jaar | Chunks | Q&A-paren | Ziektebeelden |
|---|---|---:|---:|---|
| ESC CCS | 2024 | 190 | — | CAD 174, general 11, HCM 5 |
| ESC Hartfalen | 2026 | 125 | **105** | HF 119, CAD 5, VT 1 |
| ESC Valvular | 2025 | 94 | — | VHD 36, CAD 23, HF 13, AF 9 |
| ESC Syncope | 2018 | 78 | — | general 35, VT 18, AF 10, DCM 7 |
| ESC LE | 2019 | 75 | — | general 41, ACS 34 |
| **Totaal** | | **562** | **105** | |

`medical_rag_project/data/` — oudere generatie, deels dubbel:

| Map | Chunks | Status |
|---|---:|---|
| ACS | 259 | **Uniek — ESC ACS 2023 zit nergens anders.** Waardevol. |
| CCS | 194 | Verouderde versie van `projects/ESC CCS` (190) |
| Valvular | 109 | Verouderde versie van `projects/ESC Valvular` (94) |

> **Actie:** ACS 2023 verdient een eigen project in `projects/`. De andere twee `data/`-mappen zijn archief en moeten expliciet buiten de upload blijven, anders krijg je twee versies van dezelfde richtlijn in je zoekresultaten.

### 1.2 Chunkstructuur (goed doordacht — dit is de kracht van je pipeline)

```json
{
  "id": "rec_1",
  "text": "Counselling on healthy lifestyle choices … is recommended for all patients with stage A or B HF …",
  "metadata": {
    "type": "recommendation",
    "class": "Class I",          // aanbevelingsklasse
    "evidence": "C",             // bewijsniveau
    "disease": "HF",
    "topic": "treatment",
    "section": "4.1.3.2. Smoking, alcohol, and substance abuse",
    "table_title": "Recommendation Table 1 — …",
    "guideline": "ESC Hartfalen",
    "year": "2026",
    "references": [ { "id": 74, "text": "Patel KV, … https://doi.org/10.1161/…" } ],
    "ref_ids": [...],
    "approved": true
  }
}
```

Dit is **rijker dan een standaard RAG-chunk**. Je hebt klasse, bewijsniveau, ziektebeeld, onderwerp én volledige literatuurreferenties met DOI's per aanbeveling. Dat is precies wat een klinisch product verkoopbaar maakt — en het wordt op dit moment maar half benut.

### 1.3 Wat er in productie draait

Live MongoDB Atlas (geverifieerd op 12-09-2026):

| Database | Collectie | Docs | Opmerking |
|---|---|---:|---|
| `rag_db` | `rag_chunks` | **222** | **Uitsluitend CCS 2024.** `vector_index` (3072d, cosine) = READY |
| `symvora` | `medicalrules` | 7 | Privé-kennisbank |
| `symvora` | `ragusagelogs` | 92 | Analytics werkt |
| `clinicaider_rag` | `ESC_cardiology` | 0 | Verlaten, kan weg |

Alle 222 zijn `reindexed_v2: true` — de HyDE-verrijking (hypothetische queries + Nederlandse synoniemen, ingebakken in `text`) is toegepast. 7 staan op `status: "merged"`.

### 1.4 De retrievalketen

```
anamnesis-clean (PatientChatV2.vue)
    └─> POST /api/patient-chat-v2/diagnostic
          └─> getRelevantMedicalInfoCombined()        [ragService.js:729]
                ├─> getRelevantMedicalInfo()          → symvora.medicalrules (privé, 7 docs)
                └─> getRelevantGuidelines()           → rag_db.rag_chunks (222 docs)
                      ├─ generateClinicalQuery()      → LLM-call: NL → klinisch Engels
                      ├─ openai.embeddings.create()   → 3072-dim queryvector
                      ├─ Model.find(preFilter).lean() → ⚠️ ALLE docs incl. embeddings
                      ├─ cosineSimilarity() in JS     → ⚠️ 222 × 3072 floats in Node
                      └─ fuseDenseAndLexical()        → BM25 + RRF, topK 15
          └─> prompt: "📋 OFFICIËLE RICHTLIJNEN:\n…"  [patientChatV2Routes.js:129]
```

De hybride RRF-laag (`hybridSearch.js`) is goed werk en moet blijven. Het probleem zit in hoe de kandidaten worden opgehaald.

---

## 2. De vier blokkades

### 🔴 Blokkade 1 — ID-botsing vernietigt data bij upload

Dit is de reden dat er maar één richtlijn in productie staat.

Geverifieerd over de vijf projecten:

```
562 chunk-rijen  →  slechts 191 unieke id's
124 id's komen in meer dan één project voor
```

`5_upload_to_mongodb.py` doet:

```python
UpdateOne({"_id": doc["_id"]}, {"$set": doc}, upsert=True)   # _id = "rec_1"
```

Upload je alle vijf projecten, dan houd je **191 documenten over in plaats van 562** — 66% stille dataverlies, en de overgebleven documenten zijn een willekeurige mengelmoes van richtlijnen. Er is geen foutmelding; `upsert` doet precies wat er staat.

**Dit moet als eerste gefixt worden.** Elke andere verbetering is zinloos zolang je de dataset niet zonder verlies kunt vullen.

### 🔴 Blokkade 2 — volledige collectiescan naast een ongebruikte vectorindex

`guidelinesService.js:167` haalt élk document op, inclusief de 3072-dimensionale embedding, en rekent de cosine uit in JavaScript:

```js
const allChunks = await Model.find(preFilter).lean();     // 222 × 3072 floats ≈ 5,5 MB per query
```

Ondertussen staat in Atlas:

```
vector_index (vectorSearch, READY, queryable)
  path: "embedding", numDimensions: 3072, similarity: "cosine"
```

…die nergens in de codebase wordt aangeroepen. Er is zelfs een `scripts/setup-vector-index.js`, dus de bedoeling was er wel.

Gevolgen bij het uitbreiden naar de volle corpus (~820 docs incl. ACS):
- ~20 MB BSON-transfer **per query**, per chatbeurt
- cosine over 2,5 miljoen floats op de Node-eventloop → blokkeert andere requests
- latency schaalt lineair met de corpus, precies wanneer je hem wilt laten groeien

De comment in `ragService.js:731-734` documenteert het symptoom al: de drempel moest van 0,3 naar 0,4-0,5 worden versoepeld omdat de similariteit blijft steken op ~0,51–0,54.

### 🟠 Blokkade 3 — Q&A-paren worden gegenereerd en weggegooid

`3_generate_qa_pairs.py` produceert paren als:

```json
{
  "question": "What lifestyle counseling is recommended for patients with stage A or B heart failure…?",
  "answer":   "Patients with stage A or B heart failure should receive counseling on…",
  "metadata": { "chunk_id": "rec_1", "disease": "HF", "topic": "treatment", … }
}
```

Er is **geen uploadscript, geen collectie en geen retrievalpad** voor deze data. 105 paren staan op schijf, de rest is nooit gegenereerd.

Dat is een gemiste kans, want dit lost blokkade 2's symptoom structureel op. De **asymmetrie** tussen wat de gebruiker vraagt en wat er in de index staat is nu maximaal:

| | |
|---|---|
| Gebruikersinvoer | *"man 68, pijn op de borst bij inspanning, bekend met DM2"* |
| Geïndexeerde tekst | *"…is recommended for all patients with stage A or B HF to reduce the risk of HF progression."* |

Een vraag en een voorschrijvende volzin liggen in de embeddingruimte ver uit elkaar — vandaar die 0,51. Een **vraag tegen een vraag** matchen scoort structureel veel hoger. De `reindex-rag-chunks.js` HyDE-verrijking is een pleister op dezelfde wond: die plakt gegenereerde vragen ín de chunktekst, wat werkt, maar de embedding vervuilt (één vector moet nu aanbeveling + vragen + synoniemen tegelijk representeren).

### 🟡 Blokkade 4 — taxonomiedrift en ongebruikte kwaliteitssignalen

| Probleem | Bewijs |
|---|---|
| Hoofdlettervariant | `topic: "Diagnosis"` (1×) naast `"diagnosis"` (253×) |
| Ongeldige klassen | `"Class II?"` (3×), `"Class IV"` (2×) in `data/`-archief |
| `approved` niet consistent | 128× `true`, 72× `false`, **362× afwezig** |
| `approved` wordt genegeerd | Geen enkele filter in `getRelevantGuidelines()` — 72 afgekeurde aanbevelingen zouden gewoon in het promptvenster belanden |
| Naamgeving inconsistent | `metadata.guideline` = `"CCS"` in de DB, `"ESC CCS"` in de projectbestanden |
| Geen ontdubbeling tussen richtlijnen | HF-aanbevelingen komen voor in de HF-, ACS- én Valvular-richtlijn; straks krijg je drie bijna-identieke hits die je contextbudget opeten. `semanticDedup.js` bestaat al maar wordt niet op richtlijnresultaten toegepast. |

### 🟡 Blokkade 5 — de bronnen bereiken de gebruiker niet

`PatientChatV2.vue` houdt `sources` bij in de state (regels 568, 673, 1224) maar **rendert ze nergens in de template** — geverifieerd: nul verwijzingen naar `source`, `richtlijn`, `Class` of `bron` binnen `<template>`.

Je haalt dus klasse I/IIa/III-labels, bewijsniveaus, richtlijnnaam, jaartal én DOI-links op uit de database, propt ze in de LLM-prompt, en gooit ze daarna weg. Voor een medisch product is die verifieerbaarheid nu juist het verschil tussen "interessante chatbot" en "instrument dat een arts durft te gebruiken".

---

## 3. Doelarchitectuur

```
                 RAGCreator (bron van waarheid, op schijf)
                 projects/*/rag_chunks.json  +  qa_pairs.json
                              │
                    [ 0_normalize_and_id.py ]   ← nieuw: stabiele id's + taxonomie
                              │
              ┌───────────────┴───────────────┐
     [ 4_embed_and_store ]            [ 3b_embed_qa_pairs ]   ← nieuw
              │                                │
              ▼                                ▼
   rag_db.rag_chunks                   rag_db.qa_pairs        ← nieuw
   (aanbeveling + metadata)            (vraag-embedding → chunk_id)
   vector_index                        qa_vector_index        ← nieuw
              │                                │
              └───────────────┬────────────────┘
                              ▼
              guidelinesService.getRelevantGuidelines()
                 ├─ $vectorSearch op chunks   (numCandidates 150 → 20)
                 ├─ $vectorSearch op qa_pairs (numCandidates 100 → 10)
                 ├─ parent-lookup: qa-hit → bovenliggende chunk
                 ├─ $search BM25 (lexicaal)
                 ├─ RRF-fusie  [bestaande hybridSearch.js]
                 ├─ semantische ontdubbeling  [bestaande semanticDedup.js]
                 └─ nieuwste jaartal wint bij overlap
                              ▼
                     gestructureerd resultaat
                     { text, guideline, year, class, evidence, references[] }
                              ▼
        prompt (LLM)   ─────────────┬─────────────   citaties (UI)
                                    ▼
                        anamnesis-clean: bronnenpaneel
                        met klasse-badge + DOI-link
```

**Ontwerpprincipe:** de aanbeveling blijft één document; de Q&A-paren zijn *extra ingangen* naar dat document, geen aparte kennis. Dit heet multi-representation- of parent-document-retrieval: je zoekt op de representatie die het dichtst bij de vraag ligt, maar levert altijd de volledige, geciteerde aanbeveling aan het model.

---

## 4. Het plan

### Fase 1 — Stabiele identiteit en schone taxonomie ⬅️ *begin hier*

**Waarom eerst:** zonder dit vernietig je data zodra je een tweede richtlijn uploadt.

**1.1 Nieuw script `scripts/0_normalize_and_id.py`**

Genereer een globaal uniek, deterministisch, herhaalbaar ID:

```python
GUIDELINE_SLUGS = {
    "ESC CCS":       ("esc-ccs",  "2024"),
    "ESC Hartfalen": ("esc-hf",   "2026"),
    "ESC Valvular":  ("esc-vhd",  "2025"),
    "ESC Syncope":   ("esc-syn",  "2018"),
    "ESC LE":        ("esc-pe",   "2019"),
    "ESC ACS":       ("esc-acs",  "2023"),
}

# rec_1 in ESC Hartfalen 2026  →  "esc-hf_2026_rec_1"
new_id = f"{slug}_{year}_{chunk['id']}"
```

Deterministisch (geen UUID) zodat je opnieuw kunt uploaden zonder duplicaten en `approved`-vlaggen behoudt.

**1.2 Normaliseer in hetzelfde script**

```python
topic  = topic.strip().lower()                      # "Diagnosis" → "diagnosis"
cls    = cls if cls in VALID_CLASSES else None      # "Class II?" → None + class_raw
meta["guideline"]     = canonical_name              # overal "ESC CCS", nooit "CCS"
meta["guideline_id"]  = slug                        # machineleesbaar filterveld
meta["source_project"]= project_name                # herkomst traceerbaar
```

> **Gecorrigeerd t.o.v. de eerste versie van dit plan.** Ik schreef eerst
> `approved` standaard op `True`. Dat was fout: `ESC LE` heeft **72 chunks die je
> bewust hebt afgekeurd** in de RAGCreator-UI. Die zouden daarmee alsnog zijn
> geupload. De juiste regel is drie-standen — zie 1.5.
>
> Tweede correctie: `VALID_EVIDENCE` mag niet `{A,B,C}` zijn. ESC Hartfalen 2026
> gebruikt **B1** (32×) en **B2** (7×), ESC ACS gebruikt **NR** (5×). Dat zijn
> echte bewijsniveaus; een strikte whitelist gooide ze weg. Alleen `Class II?`
> (2× in ACS) is een echte extractiefout, en die wordt nu bewaard als
> `class_raw` in plaats van stilzwijgend gewist.

**1.5 Drie-standen goedkeuring — jouw controle over de database**

| `metadata.approved` | Betekenis | Gaat naar de DB? |
|---|---|---|
| `true` | Beoordeeld en akkoord | Ja |
| `false` | **Bewust afgekeurd in de UI** | **Nooit — niet te overrulen** |
| ontbreekt | Nog niet beoordeeld | Alleen bij `upload_policy: include_unreviewed` |

Vastgelegd in `guidelines_registry.json`, een handmatig bestand dat scripts
alleen lezen. Per richtlijn: `include` (meedoen ja/nee) en `upload_policy`.
Geen enkel script schrijft naar MongoDB; `0_normalize_and_id.py` produceert
`normalized/` plus een `MANIFEST.md` die je leest vóórdat er iets geupload wordt.

Laat het script een **botsingsrapport** printen en met exitcode 1 stoppen als er ná normalisatie nog duplicaten zijn. Dat maakt de fout onmogelijk in plaats van onwaarschijnlijk.

**1.3 Migreer de bestaande 222 documenten — hernoemen, niet heruploaden**

Bij het bouwen bleek productie **niet reproduceerbaar uit de bronbestanden**:

| Soort | Aantal | Waar |
|---|---:|---|
| Geëxtraheerde aanbevelingen | 190 | ook in `data/CCS` |
| `rec_manual_*` | 4 | **alleen in productie** — handmatig toegevoegd (o.a. colchicine) |
| `summary_ccs_*` | 28 | **alleen in productie** — uit `generate-table-summaries.js` |

Een herupload vanuit `normalized/` zou die 32 documenten vernietigen. De
migratie is daarom een **pure hernoeming in plaats**: `_id` is onveranderlijk in
MongoDB, dus insert → verifiëren (incl. embeddingdimensie) → oude verwijderen,
document voor document. Embeddings, `reindexed_v2`, `status: merged` en de
HyDE-verrijking blijven intact; er wordt **niets opnieuw geëmbed**, dus het kost
geen OpenAI-credits.

Deze 222 zijn nooit door de reviewworkflow gegaan. Ze krijgen
`review_state: "legacy_production"` en géén `approved`-veld — eerlijk, en het
laat live gedrag ongemoeid omdat het filter uit fase 3 (`approved: {$ne: false}`)
ze gewoon doorlaat.

**1.4 Neem ACS 2023 op**

Verplaatsen bleek onnodig: de registry wijst met `source` naar een willekeurig
pad, dus `ESC ACS` leest gewoon uit `data/ACS`. `data/CCS` en `data/Valvular`
staan op `include: false` — oudere extracties van richtlijnen die je al hebt.

> **Resultaat fase 1:** ~820 chunks met gegarandeerd unieke, betekenisvolle, herhaalbare ID's. Upload wordt idempotent en veilig.

---

### Fase 2 — Volledige corpus in productie

**2.1 Embed en upload alle projecten**

Draai `4_embed_and_store.py` + `5_upload_to_mongodb.py` per project. Kosten: ~600 nieuwe chunks × ~800 tekens ≈ 150k tokens op `text-embedding-3-large` — verwaarloosbaar (enkele centen).

**2.2 Pas de HyDE-verrijking toe op de nieuwe richtlijnen**

`scripts/reindex-rag-chunks.js` heeft nu een `DUTCH_SYNONYMS`-tabel met alleen `CAD:*` en `HCM:*` sleutels. Breid uit met de nieuwe combinaties die nu daadwerkelijk voorkomen:

`HF:diagnosis`, `HF:treatment`, `HF:follow_up`, `VHD:diagnosis`, `VHD:treatment`, `AF:treatment`, `ACS:diagnosis`, `ACS:treatment`, `VT:diagnosis`, `DCM:diagnosis`, `general:diagnosis`

Zonder deze uitbreiding krijgen de vier nieuwe richtlijnen géén Nederlandse synoniemen en presteren ze meetbaar slechter dan CCS bij Nederlandstalige invoer.

**2.3 Werk de vectorindex bij met filtervelden**

Filteren tijdens `$vectorSearch` (in plaats van erna) vereist dat de velden in de indexdefinitie staan:

```json
{
  "fields": [
    { "type": "vector", "path": "embedding", "numDimensions": 3072, "similarity": "cosine" },
    { "type": "filter", "path": "metadata.disease" },
    { "type": "filter", "path": "metadata.topic" },
    { "type": "filter", "path": "metadata.guideline_id" },
    { "type": "filter", "path": "metadata.status" },
    { "type": "filter", "path": "metadata.approved" }
  ]
}
```

**2.4 Voeg een Atlas Search-index toe voor de lexicale helft**

Nu draait BM25 in JS op documenten die je toch al in geheugen had. Na fase 3 heb je die volledige set niet meer — dus de lexicale kant moet naar Atlas:

```json
{ "mappings": { "dynamic": false, "fields": { "text": { "type": "string" } } } }
```

> **Resultaat fase 2:** vijf tot zes richtlijnen doorzoekbaar in plaats van één. Dekking van hartfalen, kleplijden, syncope, longembolie en ACS — de klinische breedte die de anamnese-app nodig heeft.

---

### Fase 3 — `$vectorSearch` in plaats van de volledige scan

Herschrijf de kern van `getRelevantGuidelines()`:

```js
const pipeline = [
  {
    $vectorSearch: {
      index: 'vector_index',
      path: 'embedding',
      queryVector: queryEmbedding,
      numCandidates: 200,          // brede ANN-zoektocht
      limit: 25,                   // top-N terug naar de app
      filter: {
        'metadata.status':   { $ne: 'merged' },
        'metadata.approved': { $ne: false },
        ...(options.disease && { 'metadata.disease': options.disease })
      }
    }
  },
  {
    $project: {
      text: 1, metadata: 1,
      score: { $meta: 'vectorSearchScore' },
      embedding: 0                 // ⚠️ cruciaal: nooit terugsturen
    }
  }
];
```

Twee dingen die je hierbij moet doen:

1. **Behoud de RRF-fusie.** Draai een parallelle `$search`-pipeline (BM25) met dezelfde `limit`, en voer beide ranglijsten in `fuseDenseAndLexical()`. De bestaande RRF-implementatie is prima; alleen de invoer verandert van "alles" naar "top-25 van elke tak".
2. **Houd de dimensiecheck.** De bestaande mismatch-detectie (`guidelinesService.js:184`) is waardevol — verplaats hem naar een eenmalige startup-check in plaats van per query.

**Verwachte winst:** van ~20 MB en 2,5M floats per query naar een enkele geïndexeerde ANN-lookup. Latency wordt vlak in plaats van lineair met corpusgrootte — dat is wat "verkoopbaar" mogelijk maakt.

---

### Fase 4 — Q&A-paren als tweede zoeklaag (de grootste kwaliteitswinst)

**4.1 Genereer Q&A voor alle richtlijnen**

Nu bestaat alleen `ESC Hartfalen/qa_pairs.json` (105 paren). Draai `3_generate_qa_pairs.py` voor alle projecten. Verbeter de prompt zodat je **2–3 vragen per aanbeveling** krijgt in **zowel Engels als Nederlands**:

```
Genereer 3 vragen die een arts zou stellen en waarop deze aanbeveling het antwoord is.
Eén in het Engels, één in het Nederlands, één als beknopte klinische scenario-beschrijving
(bv. "man 68, pijn op de borst bij inspanning, DM2").
```

Die derde variant is de belangrijkste: hij matcht de vorm van wat er daadwerkelijk uit de anamnese-app komt.

Volume: ~820 chunks × 3 ≈ 2.500 paren. Met `gpt-4.1-mini` een paar euro.

**4.2 Nieuwe collectie `rag_db.qa_pairs`**

```json
{
  "_id": "esc-hf_2026_rec_1_q2",
  "question": "Welke leefstijladviezen zijn aanbevolen bij stadium A of B hartfalen?",
  "answer": "Patiënten met stadium A of B hartfalen moeten advies krijgen over …",
  "chunk_id": "esc-hf_2026_rec_1",        ← verwijzing naar de aanbeveling
  "lang": "nl",
  "embedding": [ … ],                      ← embedding van de VRAAG, niet het antwoord
  "metadata": { "disease": "HF", "topic": "treatment", "guideline_id": "esc-hf", "year": "2026" }
}
```

Nieuw script `3b_embed_and_upload_qa.py`. Aparte `qa_vector_index` met dezelfde filtervelden.

**4.3 Parent-document-retrieval in `getRelevantGuidelines()`**

```js
// Zoek parallel in beide representaties
const [chunkHits, qaHits] = await Promise.all([
  vectorSearchChunks(queryEmbedding, filter, 25),
  vectorSearchQA(queryEmbedding, filter, 15)
]);

// Een Q&A-treffer levert altijd de VOLLEDIGE bovenliggende aanbeveling terug —
// nooit het gegenereerde antwoord. De aanbeveling is de bron van waarheid;
// de vraag was alleen de ingang.
const parentIds = [...new Set(qaHits.map(h => h.chunk_id))];
const parents   = await Chunk.find({ _id: { $in: parentIds } }, { embedding: 0 }).lean();

// Drie ranglijsten → RRF → ontdubbeling
const fused = reciprocalRankFusion([chunkHits, mapToParents(qaHits, parents), bm25Hits]);
```

Dit is de kern van het voorstel. **Het model ziet nooit LLM-gegenereerde antwoorden** — alleen de letterlijke richtlijntekst. De Q&A-paren zijn puur een zoekhulpmiddel. Dat is essentieel voor een medisch product: je hallucinatie-oppervlak groeit niet.

**4.4 Overweeg daarna de HyDE-verrijking uit de chunktekst te halen**

Zodra Q&A-retrieval werkt, doet `[Clinical queries: …]` en `[Dutch: …]` in `text` hetzelfde werk, maar slechter (één vector voor drie soorten inhoud) — en het lekt in de LLM-prompt en in de UI. Meet eerst, verwijder daarna: houd de verrijking in `metadata`, haal hem uit het geëmbedde `text`-veld.

> **Resultaat fase 4:** de similariteitsscores die nu op 0,51–0,54 blijven steken, komen in het bereik 0,75–0,90 voor Q&A-treffers. Je kunt de drempel weer aanscherpen, wat het aantal valse positieven in het promptvenster verlaagt.

---

### Fase 5 — Ontdubbeling en recency bij meerdere richtlijnen

Zodra er zes richtlijnen in zitten, overlappen ze. Hartfalenaanbevelingen staan in de HF-, ACS- én Valvular-richtlijn (132 HF-chunks verspreid over drie bronnen). Zonder ingreep vult één vraag je contextvenster met drie parafrases van dezelfde aanbeveling.

```js
// 1. Semantische ontdubbeling — bestaat al, wordt alleen niet gebruikt
const { deduplicate } = require('./semanticDedup');
let results = deduplicate(fused, { threshold: 0.92 });

// 2. Bij bijna-duplicaten: nieuwste richtlijn wint
results = preferNewest(results, r => r.metadata.year);

// 3. Klasse I / III eerst — die zijn klinisch het meest sturend
results = boostByClass(results, { 'Class I': 1.15, 'Class III': 1.10 });
```

Voeg ook een **contextbudget** toe. Nu geldt er een harde `substring(0, 4000)`-afkapping (`patientChatV2Routes.js:448`) die een aanbeveling middenin een zin kan doormidden hakken. Beter: neem hele aanbevelingen op tot het budget vol is, en laat de rest weg.

---

### Fase 6 — Citaties zichtbaar maken in Anamnesis

Dit is de kleinste technische ingreep met de grootste zichtbare waarde.

**6.1 Backend: stuur gestructureerde bronnen mee**

`getRelevantGuidelines()` levert al `sources[]` met `guideline`, `year`, `evidenceClass`, `evidence`, `disease`. Voeg toe: `section` en de eerste 2–3 `references` (met DOI-URL). Geef dit door in de API-respons naast `rag_source_count`.

**6.2 Frontend: een bronnenpaneel onder het antwoord**

```
📋 Onderbouwing (4 richtlijnaanbevelingen)

  ┌ ESC Hartfalen 2026 · Klasse I · Niveau A ─────────┐
  │ 4.2.1  Diuretica bij congestie                     │
  │ "Diuretics are recommended in patients with HF …"  │
  │ → Referentie: doi.org/10.1161/CIRCULATIONAHA…      │
  └────────────────────────────────────────────────────┘
```

Klasse als gekleurde badge (I groen, IIa/IIb amber, III rood) — dat is de visuele taal die cardiologen al kennen uit de ESC-richtlijnen zelf. De componenten in `src/views/rag/components/` (`RagViewDialog`, `GuidelinesViewDialog`) hebben deze rendering al grotendeels; die logica is herbruikbaar.

**6.3 Sluit de feedbacklus**

Je hebt al `RecommendationFeedback.js`, `recommendationevents` (877 rijen!) en `ragusagelogs` (92). Koppel een duim-omhoog/omlaag aan elke getoonde bron. Dat geeft je binnen enkele weken data over welke aanbevelingen daadwerkelijk nuttig zijn — de basis voor herrangschikking én een sterk verhaal richting klanten.

---

## 5. Volgorde, inspanning, effect

| # | Fase | Inspanning | Effect | Risico bij overslaan |
|---|---|---|---|---|
| 1 | Stabiele ID's + taxonomie | ~4 uur | Maakt alles hierna mogelijk | **Dataverlies bij elke upload** |
| 2 | Volledige corpus uploaden | ~3 uur + centen | 222 → ~820 chunks, 6 richtlijnen | App blijft blind buiten CAD |
| 3 | `$vectorSearch` aanzetten | ~4 uur | Vlakke latency, geen 20 MB/query | Onbruikbaar bij schaal |
| 4 | Q&A-paren als tweede laag | ~8 uur + paar euro | **Grootste kwaliteitssprong** | Blijft hangen op 0,51 similariteit |
| 5 | Ontdubbeling + recency | ~3 uur | Schoner contextvenster | Duplicaten verdringen goede hits |
| 6 | Citaties in de UI | ~6 uur | Verifieerbaarheid = verkoopbaarheid | Verspilde metadata |

**Fase 1 t/m 3 zijn een aaneengesloten blok** — begin er niet aan als je ze niet alle drie afmaakt, want tussenstadia zijn instabiel. Fase 4 is de grootste kwaliteitswinst per bestede uur. Fase 6 is het meest zichtbaar voor een gebruiker of koper.

---

## 6. Hoe je weet dat het werkt

Leg een **evaluatieset** aan vóór fase 3 — anders verbeter je op gevoel:

```
tests/rag-eval/cases.json
[
  {
    "query": "man 68, pijn op de borst bij inspanning, bekend met DM2",
    "expect_guideline": "ESC CCS",
    "expect_chunk_ids": ["esc-ccs_2024_rec_12", "esc-ccs_2024_rec_15"],
    "expect_disease": "CAD"
  },
  {
    "query": "vrouw 74, kortademig, enkeloedeem, NT-proBNP 2400",
    "expect_guideline": "ESC Hartfalen",
    "expect_disease": "HF"
  },
  { "query": "collaps tijdens sporten bij 22-jarige", "expect_guideline": "ESC Syncope" },
  { "query": "acute dyspneu na langdurige vlucht",     "expect_guideline": "ESC LE" }
]
```

Meet per fase: **Recall@5**, **MRR**, **p95-latency** en **gemiddelde top-1 similariteit**. Twintig tot dertig casussen is genoeg om regressie te zien. Je hebt hier al infrastructuur voor (`tests/`, `test-runner.js`, `jest.config.js`).

Concrete verwachting:

| Meting | Nu | Na fase 4 |
|---|---|---|
| Doorzoekbare richtlijnen | 1 | 6 |
| Chunks | 222 | ~820 |
| Top-1 similariteit | 0,51–0,54 | 0,75–0,90 |
| Data per query | ~20 MB | < 100 KB |
| Zichtbare citaties | 0 | alle |

---

## 7. Twee ontwerpkeuzes waar ik expliciet in ben

**De Q&A-paren zijn een zoekingang, geen kennisbron.** Ik stel voor het gegenereerde `answer`-veld wél op te slaan (handig voor debuggen en voor de RAGCreator-UI) maar **nooit naar de LLM te sturen**. Alleen de letterlijke richtlijntekst gaat de prompt in. Anders bouw je een tweede-orde-hallucinatie in je medische product, en dat is precies het risico dat je bij een verkoopgesprek niet wilt hoeven uitleggen.

**Bewaar de gegevens per richtlijn, niet samengevoegd.** Één `rag_chunks`-collectie met een `guideline_id`-filterveld is beter dan een collectie per richtlijn: één index, één zoekopdracht, en filteren blijft mogelijk. Maar houd `metadata.source_project` erin, zodat je een richtlijn altijd in zijn geheel kunt intrekken als er een nieuwe versie uitkomt — ESC herziet ongeveer elke vijf jaar, en dat gaat gebeuren.

---

## 8. Fase 1 — uitgevoerd op 12-09-2026

### Wat er is gebouwd

| Bestand | Rol |
|---|---|
| `RAGCreator/medical_rag_project/guidelines_registry.json` | **Controlebestand.** Handmatig; per richtlijn `include` + `upload_policy`. Scripts lezen het, schrijven het nooit. |
| `RAGCreator/medical_rag_project/scripts/0_normalize_and_id.py` | Normaliseert metadata, kent stabiele ID's toe, schrijft `normalized/` + `MANIFEST.md`. **Raakt MongoDB nooit aan.** |
| `clinicaiderserver/scripts/migrate-chunk-ids.js` | Hernoemt de 222 productiedocumenten in plaats, met backup en rollback. |
| `clinicaiderserver/tests/openaiClient.test.js` | 11 regressietests op de parameter-compatibiliteitslaag. |

### Resultaat

- **ID-botsingen weg.** 821 rijen → 821 unieke ID's (was: 562 rijen → 191 unieke).
  Het script stopt met exitcode 2 als er ooit nog één overblijft.
- **Productie gemigreerd.** 222/222 hernoemd naar `esc-ccs_2024_*`, aantal gelijk,
  alle embeddings 3072-dims intact, `reindexed_v2` en `status: merged` behouden.
  Backup: `clinicaiderserver/backups/rag_chunks-2026-09-12T13-23-55-628Z.json` (14,3 MB).
- **Reviewbeleid staat op streng** (`approved_only`). Manifest: 128 van 821 chunks
  komen in aanmerking — ESC Hartfalen 125/125 plus 3 uit ESC LE. De 72 afgekeurde
  LE-chunks zijn hard uitgesloten.

### Bug gevonden tijdens verificatie (bestond al, los van deze migratie)

Bij de end-to-end-test faalde de richtlijnen-retrieval volledig:

```
400 Invalid 'input[0]': input cannot be an empty string.
```

Oorzaak: `generateClinicalQuery()` vroeg `max_tokens: 120`. De compat-laag maakt
daar `max_completion_tokens: 120` van, maar een reasoning-model besteedt dat
budget eerst aan redeneertokens. Resultaat: `finish_reason: "length"`,
`reasoning_tokens: 120`, **`content: ""`**. Die lege string glipt door de
try/catch (een `.trim()` op `''` gooit niets) en gaat rechtstreeks naar
`embeddings.create({ input: [''] })`.

Gemeten: **2 van de 6 aanroepen leeg — ongeveer een derde van alle
richtlijn-lookups in de anamnese-app faalde stil.** Dat verklaart waarschijnlijk
een deel van waarom RAG onbetrouwbaar aanvoelde.

Twee-lagen fix:

1. `openaiClient.normalizeChatParams()` telt er `REASONING_HEADROOM = 512` bij op
   voor reasoning-modellen — lost het probleem op voor alle ~100 call-sites.
2. Nieuwe `openaiClient.chatText()` geeft **null** bij een lege respons in plaats
   van `''`, zodat de aanroeper bewust terugvalt. Toegepast op de drie plekken
   waar LLM-uitvoer rechtstreeks een embedding in gaat: `generateClinicalQuery`,
   `generateRAGQuery`, `generateEnrichedRAGQuery`.

Na de fix: **0 van de 8 leeg**, 4/4 testquery's slagen, 122 tests groen.

> Dit is een symptoombestrijding op de goede plek, maar de latency blijft
> 2,8–5,9 s per query — dat is de volledige collectiescan uit blokkade 2.
> Fase 3 pakt dat aan.

---

## 9. Fase 2-4 — pijplijn en retrieval herbouwd (12-09-2026)

De RAGCreator-knoppen 3, 4 en 5 zijn nu het veilige pad. **Geen Rust-herbouw
nodig**: de stapnummers bleven, alleen wat de scripts doen is veranderd.

### Pijplijn

| Stap | Doet nu | Poort |
|---|---|---|
| 3 | Normaliseert, dan 3 zoekingangen per aanbeveling: Engelse vraag, Nederlandse vraag, casusbeschrijving | alleen goedgekeurde |
| 4 | Embedt aanbevelingen **en** Q&A-vragen; hergebruikt ongewijzigde teksten | alleen goedgekeurde |
| 5 | Upsert naar `rag_chunks` + `qa_pairs` op stabiele ID's | opnieuw gecontroleerd |

Elke stap roept eerst `ensure_normalized()` aan — idempotent en zonder API-calls,
dus een stap kan nooit op ruwe of verouderde chunks draaien, ook niet als je ze
in een andere volgorde start. Gedeelde logica staat in `scripts/pipeline_common.py`,
zodat de stappen het niet oneens kunnen worden over ID's of goedkeuring.

Stap 5 draait vanaf de CLI standaard als dry run; vanuit de UI is het indrukken
van de uploadknop zelf de bevestiging (herkend aan `RAG_DATA_DIR`).

**Getest op ESC Hartfalen:** 315 Q&A-paren uit 105 aanbevelingen in 22 s (8 threads),
440 embeddings, en bij opnieuw draaien 0 nieuw / 440 hergebruikt — gratis.
20 aanbevelingen zijn te kort (<120 tekens) voor een zinnige vraag en krijgen er geen.

### Retrieval

`getRelevantGuidelines()` combineert nu drie bronnen via de bestaande RRF-fusie:

1. `$vectorSearch` op `rag_chunks` — semantisch
2. `$vectorSearch` op `qa_pairs` → levert de **bovenliggende aanbeveling**
3. `$search` (BM25) op `rag_chunks` — exacte termen

Daarna semantische ontdubbeling waarbij bij overlap het nieuwste jaartal wint.
Valt automatisch terug op de volledige scan zolang de indexen niet READY zijn.

Twee dingen die stilzwijgend fout hadden kunnen gaan:

- Atlas geeft voor een cosine-index `(1 + cosine) / 2`, niet de ruwe cosine.
  Zonder terugrekenen zou elke drempel in de codebase verschuiven.
- `$vectorSearch` op een **niet-bestaande** collectie geeft geen fout maar een
  lege lijst. Mijn eerste terugvalcheck keek naar beide vectorbronnen, waardoor
  het lege `qa_pairs` het echte falen van `rag_chunks` maskeerde en de query 0
  resultaten gaf. Nu is alleen de chunk-zoekopdracht bepalend.

### Gemeten effect

| | Voor | Na |
|---|---|---|
| DB-tijd per query | 807 ms | **147 ms** |
| Data per query | 14,3 MB | **56 KB** |
| Kandidaten | alle 222 | 25 + 15 + 15 |
| Tests | 122 groen | 122 groen |

De resterende latency (2,8–6,9 s) is nu vrijwel volledig de **LLM-query-expansie
(2,9 s)**, niet de database. Dat is het volgende dat de moeite loont: cachen per
sessie, of overslaan als de query al Engels is.

### Uitgevoerd: slot vrijgemaakt en geupload

`symvora.medicalrules.vector_index` verwijderd (ongebruikt), privé-KB daarna
gecontroleerd en ongewijzigd. Vervolgens geupload:

| Collectie | Inhoud |
|---|---|
| `rag_db.rag_chunks` | **350** — CCS 222, Hartfalen 125, LE 3 |
| `rag_db.qa_pairs` | **321** — Hartfalen 315, LE 6 |

Nul overschrijvingen; 0 oude ID's over; 0 afgekeurde chunks in de database.
De 72 afgekeurde LE-aanbevelingen zijn door de poort tegengehouden.
`qa_vector_index` staat READY.

### Drie keer fout gerangschikt — wat het leerde

De fusie was de lastigste stap. Twee versies faalden **stil**: de query slaagde,
maar leverde de verkeerde richtlijn.

1. **Ongewogen RRF.** De query wordt naar lang Engels uitgebreid, dus bijna elk
   document krijgt een zwakke BM25-match. Elke zwakke lexicale treffer versloeg
   daardoor een sterke semantische zonder lexicale hit → hartfalen-vragen gaven CCS.
2. **Q&A als aparte, zwaarder gewogen ranglijst.** Dat gaf een richtlijn *mét*
   Q&A-paren een structurele voorsprong op een richtlijn zonder, los van
   relevantie → nu gaven CCS-vragen hartfalen. Dekking blijft ongelijk zolang je
   stapsgewijs beoordeelt, dus dit moest coverage-neutraal.
3. **Gewogen RRF** hielp maar niet genoeg: `1/(k+rang)` met k=60 comprimeert
   rangverschillen zo sterk dat zelfs gewicht 0,4 een groot semantisch gat kon
   overrulen.

Uiteindelijk: cosine is een betekenisvolle, begrensde schaal, dus rangschikken op
similariteit plus een **begrensde lexicale bonus** (max +0,05). De Q&A-bijdrage
zit al in `similarity = max(simChunk, simQa)`, waardoor Q&A-paren hebben op
zichzelf geen voordeel is — alleen een betere match. Vastgelegd in
`tests/guidelinesFusion.test.js` (8 tests, waaronder expliciet coverage-neutraliteit).

### De belangrijkste fout: Q&A doorzocht met de vertaling

De Q&A-paren bevatten Nederlandse vragen en casusbeschrijvingen, maar werden
doorzocht met de **Engelse expansie**. Daarmee was juist het sterkste signaal
onbruikbaar. Gemeten op "leefstijladvies bij beginnend hartfalen":

| Zoekvector | Beste Q&A-match |
|---|---|
| Engelse expansie | 0,609 |
| **Originele NL-query** | **0,740** |

Nu worden beide vectoren in één embedding-call gemaakt: de expansie voor de
Engelse richtlijntekst, het origineel voor de Nederlandse Q&A-varianten.

### Resultaat op 10 testvragen

| | Voor | Na |
|---|---|---|
| Juiste richtlijn op plek 1 | n.v.t. (één richtlijn) | **9/10** |
| Juiste richtlijn in top 3 | — | **10/10** |
| Gemiddelde max-similariteit | 0,51–0,54 | **0,708** |
| Tests | 122 | **130 groen** |

### Gemeten: is de HyDE-verrijking nog nodig?

`scripts/experiments/hyde-ablation.js` — 30 testvragen, alle 350 chunks als
kandidatenpool, cosine lokaal berekend (geen Atlas-indexslots nodig), en de
échte `fuseWeighted` uit de service.

**Leakage vermeden:** per chunk vier vraagvarianten gegenereerd. Drie (en/nl/
scenario) gaan de index in, de vierde is de testvraag en zit nergens in de index.
Er wordt dus generalisatie gemeten, niet het terugvinden van een identieke string.

| Conditie | Recall@1 | Recall@5 | MRR | richtlijn@1 | gem. max-sim |
|---|---:|---:|---:|---:|---:|
| A  HyDE, geen Q&A *(productie nu)* | 40% | 63% | 0,500 | 90% | 0,677 |
| B  niets | 33% | 70% | 0,467 | 87% | 0,673 |
| **C  Q&A, geen HyDE** | **63%** | **80%** | **0,706** | **97%** | **0,778** |
| D  Q&A + HyDE | 60% | 80% | 0,693 | 97% | 0,778 |

- **HyDE alleen** (B→A): +0,033 MRR
- **Q&A alleen** (B→C): **+0,239 MRR** — ruim zeven keer zoveel
- **HyDE bovenop Q&A** (C→D): −0,013 MRR

Per vraag vergeleken zijn C en D bij **26 van de 30** exact gelijk; van de vier
die verschillen is het 2–2. Dat is ruis, geen signaal.

**Conclusie: zodra een richtlijn Q&A-paren heeft, voegt de HyDE-verrijking niets
meer toe.** Weghalen levert bovendien op dat `[Clinical queries: ...]` en
`[Dutch: ...]` niet langer meelekken in de LLM-prompt en straks in het
bronnenpaneel, en dat één vector niet langer aanbeveling én vragen én synoniemen
tegelijk hoeft te representeren.

**Maar niet ongeconditioneerd weghalen.** Zonder Q&A helpt HyDE wél een beetje
(B→A). CCS is precies dat geval: het is de enige richtlijn mét HyDE en zónder
Q&A. Nu strippen maakt CCS meetbaar slechter (MRR 0,443 → 0,413 op CCS-vragen).

Volgorde is dus: **CCS beoordelen in de UI → stap 3/4/5 → daarna pas strippen.**

Wat hiermee vervalt: fase 2.2 uit dit plan — `DUTCH_SYNONYMS` in
`reindex-rag-chunks.js` uitbreiden met `HF:*`, `VHD:*`, `AF:*`, `ACS:*` — is niet
meer nodig. De Q&A-laag doet dat werk beter. Draai `reindex-rag-chunks.js` niet
opnieuw op nieuwe richtlijnen.

**Beperkingen van deze meting.** n=30 is klein, en de testvragen zijn
LLM-gegenereerde vignetten uit dezelfde verdeling als de geïndexeerde Q&A-
varianten; dat vleit de absolute Q&A-cijfers. Echte gebruikersinvoer is rommeliger.
De vergelijking C vs D is daar níét gevoelig voor — beide hebben dezelfde Q&A —
dus "HyDE voegt niets toe bovenop Q&A" staat stevig. De grootte van de sprong
B→C is richtinggevend, niet exact.

### Was: search-index-limiet bereikt

De Atlas-cluster staat op zijn maximum aantal search-indexen (3) en weigert
`qa_vector_index`. Zonder die index werkt vraag-tegen-vraag-retrieval niet.

| Index | Docs | Nodig? |
|---|---:|---|
| `rag_db.rag_chunks.vector_index` | 222 | ja, primair |
| `rag_db.rag_chunks.text_index` | 222 | lexicale helft |
| `symvora.medicalrules.vector_index` | 7 | **nee — ongebruikt** |

`ragService.js` bevat geen enkele `$vectorSearch` of `$search`: de privé-kennisbank
van 7 documenten wordt met een volledige scan in JS doorzocht. Die index wordt dus
nergens bevraagd en houdt alleen een slot bezet.

```bash
node scripts/setup-guidelines-indexes.js --free-unused
```

---

## 10. Eerste concrete stap

Fase 1 is klaar. De volgende stap is fase 2: de goedgekeurde chunks embedden en
uploaden. Beoordeel eerst in de RAGCreator-UI wat je mee wilt nemen, of pas
`guidelines_registry.json` aan, en draai daarna:

```bash
cd /Users/mkdebie/Programms/RAGCreator/medical_rag_project && python3 scripts/0_normalize_and_id.py --write
```

Lees `normalized/MANIFEST.md` en pas daarna uploaden.
