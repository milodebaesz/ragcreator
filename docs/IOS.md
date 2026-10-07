# RAGCreator op de iPhone

De iPhone-app is een native SwiftUI-app in `ios/` — zie `ios/README.md` voor
bouwen, installeren en wat hij kan. Dit document beschrijft hoe de Mac en de
iPhone dezelfde gegevens delen.

## Eén map in iCloud

Er is geen server en geen sync-stap. Beide apps werken op dezelfde bestanden in
de iCloud-container van RAGCreator (`iCloud.com.ragcreator.app`, in iCloud Drive
te zien als **RAGCreator**):

```
~/Library/Mobile Documents/iCloud~com~ragcreator~app/Documents/
  medical_rag_project/
    rag_config.json
    projects/<naam>/      rag_chunks.json, guideline.md, qa_pairs.json,
                          pdf_pages.json, extraction_report.txt, <richtlijn>.pdf
    normalized/           genormaliseerde chunks, embeddings, MANIFEST
    data/                 oudere projecten uit de registry
```

De desktop-app draait de pijplijn rechtstreeks in die map; de iPhone-app leest
eruit. Wat níet in iCloud staat: de Python-scripts, de venv, `.env`
(API-sleutels) en `guidelines_registry.json` (staat in git). Die blijven in de
repo; de desktop-app vindt ze via `storage::code_root()` en geeft de scripts de
datamap mee via `RAG_MED_ROOT`. Los vanuit de terminal kiezen de scripts zelf
dezelfde map (`pipeline_common.DATA_ROOT`).

`pdf_pages.json` (pagina per aanbeveling) bouwt de desktop-app op de achtergrond
met `scripts/build_pdf_pages.py`, bij het starten en na pijplijnstap 2. De
iPhone kan zelf geen PDF doorzoeken en springt alleen naar pagina's die daarin
staan.

## De verhuizing uit de repo

Zolang de container niet op de Mac bestaat, werkt de desktop-app vanuit de repo
en meldt dat bij **Instellingen → Opslag & iOS-app**. Hij maakt de container
niet zelf aan: iCloud synct geen map die hij nooit uitgedeeld heeft. De container
verschijnt zodra de iPhone-app één keer gedraaid heeft.

Bij de eerstvolgende start kopieert de desktop-app `projects/`, `normalized/`,
`data/` en als laatste `rag_config.json` naar iCloud, en zet de repo-kopie opzij
in `medical_rag_project/.pre-icloud-backup/`. Staat er al een `rag_config.json`
in iCloud, dan wordt er niets overschreven.

## Bestanden die iCloud nog niet gedownload heeft

iCloud kan een bestand vervangen door een `.naam.icloud`-placeholder.
`storage::ensure_local` haalt zo'n bestand op voordat het gelezen of
overschreven wordt; zonder die stap zou een nog niet gedownload
`rag_chunks.json` als leeg gelezen — en bij opslaan overschreven — worden. De
iPhone-app leest via `NSFileCoordinator`, dat hetzelfde doet.
