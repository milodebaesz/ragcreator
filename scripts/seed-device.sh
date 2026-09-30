#!/bin/sh
# Kopieert medical_rag_project rechtstreeks naar de Documents-map van de
# iOS-app op een aangesloten toestel, zonder iCloud.
#
# Bedoeld als tussenoplossing zolang de iCloud-container niet geregistreerd is
# (zie docs/IOS.md). De app leest die map als fallback, dus voor de app zelf is
# er geen verschil met een iCloud-sync.
#
#   IOS_DEVICE=<UDID> npm run ios:seed
#
# UDID's opvragen: xcrun devicectl list devices
set -e

: "${IOS_DEVICE:?zet IOS_DEVICE op de UDID van je toestel (xcrun devicectl list devices)}"

BUNDLE=com.ragcreator.app
DATA=$(sh "$(dirname "$0")/data-root.sh")
copy() {
    xcrun devicectl device copy to \
        --device "$IOS_DEVICE" \
        --domain-type appDataContainer \
        --domain-identifier "$BUNDLE" \
        --source "$1" \
        --destination "$2" >/dev/null
}

echo "rag_config.json"
copy "$DATA/rag_config.json" Documents/medical_rag_project/rag_config.json

# Alles gaat mee: rag_config.json bepaalt welk project actief is, en een actief
# project dat ontbreekt geeft een leeg scherm zonder uitleg.
for dir in "$DATA"/projects/*/; do
    name=$(basename "$dir")
    echo "$name"
    copy "$dir" "Documents/medical_rag_project/projects/$name"
done

echo "Klaar. Start de app opnieuw op het toestel."
