# RAGCreator voor iOS (native)

SwiftUI-versie van de iPhone-app. Leest dezelfde bestanden als de Tauri-iOS-app
uit de iCloud-container `iCloud.com.ragcreator.app` (zie `docs/IOS.md`); de
desktop-app schrijft ze. Er is geen eigen Rust- of web-code.

```
ios/
  project.yml              bron voor het Xcode-project (xcodegen)
  RAGCreator/Data/         modellen, iCloud-opslag, referenties
  RAGCreator/Views/        schermen
```

Bundle-ID `com.ragcreator.native`, naam "RAGCreator β", zodat hij naast de
Tauri-app op dezelfde telefoon staat tot hij die vervangt.

## Bouwen

```sh
npm run native:build                      # xcodegen + Release-build voor een toestel
IOS_DEVICE=<UDID> npm run native:install  # installeren
```

De eerste keer moet Xcode het profiel voor de nieuwe app-ID aanmaken, en dat
kan alleen vanuit Xcode zelf (de command line ziet het Apple-account niet):
open `ios/RAGCreator.xcodeproj`, kies je iPhone als bestemming en druk op ⌘R.
Onder **Signing & Capabilities** moet iCloud → iCloud Documents aanstaan met
de container `iCloud.com.ragcreator.app`.

## Stand

| Scherm | Status |
|---|---|
| Aanbevelingen (zoeken, filters, detail, referenties, Q&A) | klaar |
| PDF (PDFKit, opent op de pagina van de aanbeveling) | klaar |
| Richtlijn-tab (PDF van de gekozen richtlijn) | klaar |
| Vraag (Apple Intelligence, antwoord verschijnt woord voor woord) | klaar |
| Q&A (zoeken, taalfilter, naar de aanbeveling) | klaar |
| Overzicht (tellingen, grafieken, tabellen) | klaar |

Het icoon wordt getekend door `scripts/make_icon.swift`:

```sh
swift ios/scripts/make_icon.swift ios/RAGCreator/Resources/Assets.xcassets/AppIcon.appiconset/AppIcon.png
```
