# RAGCreator voor iOS (native)

De iPhone-app, native in SwiftUI. Leest de bestanden die de desktop-app in de
iCloud-container `iCloud.com.ragcreator.app` schrijft (zie `docs/IOS.md`).

```
ios/
  project.yml              bron voor het Xcode-project (xcodegen)
  RAGCreator/Data/         modellen, iCloud-opslag, referenties
  RAGCreator/Views/        schermen
```

Bundle-ID `com.ragcreator.app`, naam "RAGCreator". Hij heeft de eerdere
Tauri-iOS-app (webview) vervangen, die uit de repo verwijderd is.

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
