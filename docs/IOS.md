# RAGCreator voor iOS

Een read-only versie van RAGCreator voor iPhone en iPad: aanbevelingen inzien,
de richtlijntekst lezen, en zoeken — in de aanbevelingen én in de volledige
richtlijn. De pijplijn (PDF → chunks → MongoDB) blijft op de Mac.

## Hoe de twee apps met elkaar praten

Er is geen server en geen netwerkverbinding tussen de apps. De Mac schrijft
projectbestanden naar de iCloud Drive-map van RAGCreator, iOS leest daaruit.

```
Mac                                          iPhone
───                                          ──────
medical_rag_project/projects/<naam>/    ──►  iCloud Drive/RAGCreator/
  rag_chunks.json      aanbevelingen           medical_rag_project/
  guideline.md         richtlijntekst            rag_config.json
  pdf_pages.json       paginanummers             projects/<naam>/…
  extraction_report.txt
  <richtlijn>.pdf      (optioneel)
```

De mapstructuur is aan beide kanten identiek. Daardoor werkt elk pad-hulpje in
`commands.rs` op beide platforms zonder platformcheck; alleen de wortel
verschilt, en die wordt bepaald in `src-tauri/src/storage.rs`.

`qa_pairs.json` gaat wel mee, maar staat in `OPTIONAL_FILES` in `sync.rs`:
het bestand ontstaat pas als pijplijnstap 3 gedraaid heeft, en een project
zonder Q&A-paren mag geen syncfout geven. Is de Q&A-tab leeg terwijl de rest
gevuld is, kijk dan eerst of dat bestand in het project bestaat.

Wat níet meegaat: de Python-scripts, de venv, `.env` en `embeddings.json`. De
viewer heeft ze niet nodig en API-sleutels horen niet op een telefoon.

### Synchroniseren

In de desktop-app: **Instellingen → iCloud & iOS-app → Synchroniseer naar
iCloud**. Vink aan welke richtlijnen mee moeten en of de bron-PDF meegaat.
Ongewijzigde bestanden worden overgeslagen, dus een tweede sync na een kleine
wijziging kopieert alleen wat echt veranderd is.

`rag_config.json` wordt als laatste geschreven. Tot een project daarin staat
negeert de iOS-app de map, zodat een halve kopie nooit gelezen wordt.

## Wat de iOS-app kan en niet kan

| | |
|---|---|
| **Aanbevelingen** | Bladeren, zoeken, filteren op klasse/aandoening/onderwerp; referenties doorklikken naar PubMed, DOI of Scholar |
| **Richtlijn** | Inhoudsopgave, sectie per sectie lezen, full-text zoeken door de hele richtlijn |
| **Overzicht** | Aantallen, klasse- en bewijsniveauverdeling, referentiekwaliteit |
| **PDF** | Pagina-nummer per aanbeveling; de PDF zelf opent in de Bestanden-app |
| **Niet** | Pijplijn draaien, aanbevelingen bewerken of accorderen, MongoDB |

Dat laatste is afgedwongen in de build, niet alleen in de UI: `src-tauri/src/lib.rs`
registreert die commands simpelweg niet in de iOS-variant, dus een verdwaalde
frontend-aanroep faalt hard in plaats van half te werken.

## Setup — al gedaan op deze Mac

De toolchain staat en het Xcode-project is gegenereerd. Wat er is gebeurd, voor
het geval je het op een andere machine opnieuw moet doen:

```sh
brew install rustup cocoapods       # rustup is keg-only naast brew's rust
brew uninstall rust                 # brew-rust kan geen iOS-targets toevoegen
export PATH="/opt/homebrew/opt/rustup/bin:$PATH"   # staat in ~/.zshrc
rustup default stable
rustup target add aarch64-apple-ios aarch64-apple-ios-sim x86_64-apple-ios
rustup component add llvm-tools     # swift-rs heeft llvm-objcopy nodig
npm run tauri ios init              # maakt src-tauri/gen/apple/
```

De iCloud-configuratie staat niet in de gegenereerde `Info.plist` maar in
`src-tauri/gen/apple/project.yml`, de bron waaruit xcodegen die plist maakt —
daar overleven de keys een regeneratie. De entitlements staan in
`src-tauri/gen/apple/ragcreator_iOS/ragcreator_iOS.entitlements`, met een kopie
in `src-tauri/ios/` voor als het project ooit opnieuw gegenereerd wordt.

### Bouwen en draaien

```sh
npm run ios:sim                        # bouwen en starten in de simulator
npm run ios:build                      # gesigneerde .ipa voor een toestel
IOS_DEVICE=<UDID> npm run ios:install  # installeren op dat toestel
```

`xcrun devicectl list devices` geeft de UDID van een gekoppelde telefoon.

`ios:build` en `ios:sim` doen twee dingen, en die volgorde is niet
vrijblijvend: eerst `ios:prebuild` (de Rust-lib, met de swift-shim op
`PATH`; `ios:prebuild:sim` voor de simulator), dan pas
`tauri ios build`. De cargo-aanroep binnen Xcode is daarna een cache-hit en
gebruikt het resultaat van stap 1. Draai je `tauri ios build` los, dan bouwt
Xcode de Swift-kant zelf en faalt de link — zie hieronder.

Let op: `ios:build` verwijdert `src-tauri/gen/apple/build/` eerst. De bundler
hernoemt de app naar een pad dat hij niet overschrijft, en faalt anders met
`failed to rename app … Directory not empty`.

### Data op een toestel zetten zonder iCloud

Zolang de iCloud-container niet geregistreerd is, kun je de projectbestanden
rechtstreeks in de Documents-map van de app zetten — dezelfde fallback die
`storage.rs` gebruikt, dus de app merkt het verschil niet:

```sh
IOS_DEVICE=<UDID> npm run ios:seed
```

Daarna de app op het toestel opnieuw starten. Controleren wat erop staat:

```sh
xcrun devicectl device info files --device <UDID> \
  --domain-type appDataContainer --domain-identifier com.ragcreator.app
```

Is `Documents/medical_rag_project/projects` leeg, dan toont de app zijn
lege-toestand — dat is geen bug in de viewer maar ontbrekende data.

### Testen op de Mac

De simulator is de snelste manier om de iOS-app te bekijken zonder telefoon, en
de enige plek waar je de webview met Safari's Web Inspector kunt openen
(Safari → Ontwikkel → Simulator → RAGCreator).

```sh
xcrun simctl boot "iPhone 17"   # of een ander toestel uit `xcrun simctl list devices`
npm run ios:sim                 # bouwen, installeren, starten
npm run ios:sim:seed            # projectdata erin zetten
```

De simulator heeft geen iCloud-account, dus de app valt daar terug op zijn eigen
Documents-map — vandaar `ios:sim:seed`, dat `medical_rag_project/` naar
`$(xcrun simctl get_app_container booted com.ragcreator.app data)/Documents/`
kopieert. Start de app daarna opnieuw; `rag_config.json` bepaalt welk project
actief is, dus kopieer minstens dat project mee.

Crasht de app bij het starten, kijk dan in het crashrapport in plaats van in de
console — die staat vol UIKit-ruis:

```sh
ls -t ~/Library/Logs/DiagnosticReports/RAGCreator-*.ips | head -1
```

### De swift-shim

`src-tauri/ios/swift-shim/swift` forceert `swift build --build-system native`.
Zonder die shim faalt de toestel-build bij het linken:

```
Undefined symbols for architecture arm64:
  "_retain_object", "_release_object", "_string_from_bytes", ...
```

Sinds Swift 6.2 is `swiftbuild` de standaard backend, en die maakt van de
@_cdecl-exports in het Tauri Swift-package lokale symbolen (`t` in `nm`) in
plaats van globale (`T`). swift-rs 1.0.8 repareert dat achteraf met
`llvm-objcopy`, maar alleen voor de symbolen van het package zelf; die van de
meegebouwde SwiftRs-module blijven lokaal. De `native` backend houdt alles
globaal, dus die gebruiken we.

Twee dingen die daarbij nodig zijn:

- `rustup component add llvm-tools` — zonder `llvm-objcopy` slaat swift-rs zijn
  reparatiestap stilzwijgend over.
- De shim moet op `PATH` staan *van de cargo-aanroep*. Een `export PATH` in de
  Xcode-buildfase werkt niet (de shim wordt daar nooit aangeroepen), vandaar de
  losse `ios:prebuild`-stap.

Zodra swift-rs dit zelf afvangt kunnen de shim en `ios:prebuild` weg.

### UIScene-lifecycle (iOS 26+)

`UIApplicationSceneManifest` staat in `project.yml` en moet daar blijven staan.
Zonder die sleutel beschouwt iOS 26+ de app als niet-aangepast aan de
UIScene-lifecycle: op de simulator crasht hij meteen
(`_UIApplicationEvaluateRuntimeIssueForNoSceneLifecycleAdoption`,
`EXC_BREAKPOINT`), op een toestel zie je een leeg wit scherm.

`UIApplicationSupportsMultipleScenes` moet `true` zijn: tao zet zijn
scene-delegate alleen in als die vlag aanstaat — zie `multiple_scenes_enabled()`
in tao's `platform_impl/ios/scene.rs`. Staat hij op `false`, dan maakt tao zijn
venster nog op de oude manier aan en blijft het scherm alsnog wit.

Dat scene-pad van tao 0.35.3 bevat zelf een use-after-free, die met een lokale
patch in `src-tauri/vendor/tao` is verholpen. Zie `src-tauri/vendor/README.md`
voor wat er precies gewijzigd is en wanneer die map weg kan.

### Signing

Team en signing-stijl staan in `src-tauri/gen/apple/project.yml`
(`DEVELOPMENT_TEAM`, `CODE_SIGN_STYLE: Automatic`) — niet in Xcode, want
xcodegen genereert het `.xcodeproj` opnieuw uit dat bestand en gooit
wijzigingen die direct in Xcode gemaakt zijn weg. Na een wijziging:
`cd src-tauri/gen/apple && xcodegen generate`.

Het deployment target moet minstens 15.0 zijn; Xcode 27 weigert lager
("supported deployment target versions is 15.0 to 27.0.x"). Het staat op twee
plekken: `project.yml` (`deploymentTarget`) en `src-tauri/tauri.conf.json`
(`bundle.iOS.minimumSystemVersion`).

#### iCloud staat nog niet aan

De build signeert met een profiel zonder iCloud-entitlements — te zien met:

```sh
unzip -o src-tauri/gen/apple/build/arm64/RAGCreator.ipa -d /tmp/ipa
codesign -d --entitlements :- /tmp/ipa/Payload/RAGCreator.app
```

Staan daar alleen `application-identifier` en `team-identifier`, dan is de
container niet meegegeven en valt de app terug op zijn eigen Documents-map
(Bestanden-app → Op mijn iPhone → RAGCreator). Dat werkt, maar dan zet je de
projectmappen er zelf in in plaats van te synchroniseren.

Aanzetten kan alleen via Xcode, omdat de iCloud-container in het Apple
Developer-portal moet bestaan:

- Open `src-tauri/gen/apple/ragcreator.xcodeproj`.
- **Signing & Capabilities** → **+ Capability → iCloud** → vink *iCloud
  Documents* aan en maak/selecteer de container `iCloud.com.ragcreator.app`.
- Bouw één keer vanuit Xcode zodat het profiel vernieuwd wordt; daarna werkt
  `npm run ios:build` weer.

## Waar dingen kunnen misgaan

**"Nog geen richtlijn" terwijl je net gesynchroniseerd hebt.** iCloud is
asynchroon. Kijk in de Bestanden-app of `RAGCreator/medical_rag_project/` er al
staat; de eerste sync van een PDF van enkele megabytes kan even duren.

**De map verschijnt niet in iCloud Drive op de Mac.** De container bestaat pas
nadat de iOS-app minstens één keer gedraaid heeft met de juiste entitlement.
`get_icloud_status` laat het pad zien waar de desktop-app naartoe zou schrijven;
tot die tijd maakt hij die map zelf aan, wat werkt zodra de container bestaat.

**De PDF opent niet.** De knop gebruikt de `shareddocuments://`-URL van de
Bestanden-app. Werkt dat niet op jouw iOS-versie, dan staat het volledige pad
eronder — de PDF is gewoon te vinden onder *Bestanden → iCloud Drive →
RAGCreator*.

**Kopteksten midden in de richtlijntekst.** Regels als een los paginanummer of
"ESC Guidelines" komen uit de PDF-conversie en staan zo in `guideline.md`; de
viewer geeft weer wat er staat. Dat is werk voor stap 1 van de pijplijn, niet
voor de app.
