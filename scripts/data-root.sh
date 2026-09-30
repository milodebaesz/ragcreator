#!/bin/sh
# Print de map met projects/ en rag_config.json: dezelfde keuze als
# src-tauri/src/storage.rs maakt. De iCloud-map zodra de desktop-app de data
# daarheen verhuisd heeft, anders de repo.
ICLOUD="$HOME/Library/Mobile Documents/iCloud~com~ragcreator~app/Documents/medical_rag_project"
if [ -f "$ICLOUD/rag_config.json" ]; then
    echo "$ICLOUD"
else
    echo "$(cd "$(dirname "$0")/.." && pwd)/medical_rag_project"
fi
