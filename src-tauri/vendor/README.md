# Lokaal gepatchte dependencies

## tao 0.35.3

Eén regel gewijzigd in `src/platform_impl/ios/view.rs`, in
`configuration_for_connecting_scene_session`:

```rust
-Retained::as_ptr(&config) as _
+Retained::autorelease_ptr(config) as _
```

Zonder die patch crasht de iOS-app meteen bij het opstarten met
`EXC_BAD_ACCESS` in `objc_retain`, aangeroepen vanuit
`-[UIApplication _connectUISceneFromFBSScene:transitionContext:]`. De
`Retained` wordt namelijk gedropt zodra de functie terugkeert, dus UIKit
krijgt een pointer naar een object dat net is vrijgegeven.

Dat pad wordt pas geraakt sinds we de UIScene-lifecycle aanzetten
(`UIApplicationSceneManifest` in `gen/apple/project.yml`), wat iOS 26+ eist —
zie docs/IOS.md.

tao 0.37.0 heeft dit upstream opgelost, maar tauri 2.11.2 pint tao op `0.35`,
dus een versiebump is geen optie: de patch moet via `[patch.crates-io]` in
`src-tauri/Cargo.toml`.

**Weg te gooien** zodra Tauri een tao met deze fix meelevert. Controle:

```sh
grep -n autorelease_ptr \
  ~/.cargo/registry/src/*/tao-*/src/platform_impl/ios/view.rs
```

Staat de fix in de tao-versie die Tauri zelf trekt, verwijder dan deze map en
het `[patch.crates-io]`-blok.
