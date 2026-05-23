#!/usr/bin/env bash
# Import dashboard JSON files in this directory to your Grafana via the HTTP API.
#
# Required env:
#   GRAFANA_URL          e.g. https://your-stack.grafana.net
#   GRAFANA_API_TOKEN    Grafana Cloud service-account token (glsa_...)
#
# Currently the canonical way to create the use-case dashboard is to paste
# `use-cases-prompt.md` into Grafana Assistant — this script is the path
# for when JSON snapshots exist in this directory.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

: "${GRAFANA_URL:?GRAFANA_URL is required, e.g. https://your-stack.grafana.net}"
: "${GRAFANA_API_TOKEN:?GRAFANA_API_TOKEN is required (glsa_... service-account token)}"

shopt -s nullglob
JSON_FILES=("$SCRIPT_DIR"/*.json)
if [[ ${#JSON_FILES[@]} -eq 0 ]]; then
  echo "No dashboard JSON files found in $SCRIPT_DIR."
  echo "Use the Grafana Assistant prompt (use-cases-prompt.md) instead, or export"
  echo "your existing dashboard JSON into this directory before re-running."
  exit 0
fi

for fp in "${JSON_FILES[@]}"; do
  name=$(basename "$fp" .json)
  echo "Importing $name..."
  # Wrap the dashboard JSON in the {"dashboard": ..., "overwrite": true} envelope
  # expected by /api/dashboards/db.
  body=$(python3 -c "
import json, sys
d = json.load(open('$fp'))
# Strip server-set fields so the import is portable
d.pop('id', None)
print(json.dumps({'dashboard': d, 'overwrite': True, 'message': 'Imported by dashboards/import.sh'}))
")
  curl -fsS \
    -H "Authorization: Bearer ${GRAFANA_API_TOKEN}" \
    -H 'Content-Type: application/json' \
    -X POST \
    -d "$body" \
    "${GRAFANA_URL}/api/dashboards/db" \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(f\"  -> {d.get('url','OK')} (uid={d.get('uid','?')})\")"
done

echo
echo "Done. Open your Grafana to see the imported dashboards."
