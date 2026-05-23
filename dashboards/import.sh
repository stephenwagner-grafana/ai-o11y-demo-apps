#!/usr/bin/env bash
# Import dashboard JSON files in this directory to your Grafana via the HTTP API.
#
# Required env:
#   GRAFANA_URL          e.g. https://your-stack.grafana.net
#   GRAFANA_API_TOKEN    Grafana Cloud service-account token (glsa_...)
#
# Optional env:
#   PROM_DS_UID          UID of the Prometheus datasource to bind to ${DS_PROMETHEUS}.
#                        Defaults to "grafanacloud-prom" (the standard Grafana Cloud
#                        Prometheus datasource UID). Override if your stack uses a
#                        different UID.
#
# Each *.json file in this directory is POSTed to /api/dashboards/import (which
# resolves __inputs placeholders) when it has an `__inputs` block, falling back to
# /api/dashboards/db (raw upsert) otherwise. This handles both portable exports
# (with __inputs/__requires, e.g. use-cases.json) and direct snapshots.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

: "${GRAFANA_URL:?GRAFANA_URL is required, e.g. https://your-stack.grafana.net}"
: "${GRAFANA_API_TOKEN:?GRAFANA_API_TOKEN is required (glsa_... service-account token)}"
PROM_DS_UID="${PROM_DS_UID:-grafanacloud-prom}"

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
  # Detect whether this dashboard is a portable export (has __inputs) and pick
  # the right endpoint + envelope. Strip server-set fields (id, version) so the
  # import is idempotent.
  result=$(PROM_DS_UID="$PROM_DS_UID" GRAFANA_URL="$GRAFANA_URL" \
    GRAFANA_API_TOKEN="$GRAFANA_API_TOKEN" FP="$fp" python3 <<'PYEOF'
import json, os, sys, urllib.request, urllib.error

fp = os.environ["FP"]
url = os.environ["GRAFANA_URL"].rstrip("/")
token = os.environ["GRAFANA_API_TOKEN"]
prom_uid = os.environ["PROM_DS_UID"]

with open(fp) as f:
    d = json.load(f)

# Strip server-set fields so re-imports are clean upserts.
d.pop("id", None)
d.pop("version", None)

inputs = d.get("__inputs") or []
if inputs:
    # Portable export — use /api/dashboards/import with resolved inputs.
    resolved = []
    for inp in inputs:
        if inp.get("type") == "datasource" and inp.get("pluginId") == "prometheus":
            resolved.append({
                "name": inp["name"],
                "type": "datasource",
                "pluginId": "prometheus",
                "value": prom_uid,
            })
        else:
            # Pass through other inputs as-is — caller would need to extend
            # this script to bind Loki/Tempo/etc.
            resolved.append({
                "name": inp["name"],
                "type": inp.get("type", "datasource"),
                "pluginId": inp.get("pluginId", ""),
                "value": "",
            })
    body = {
        "dashboard": d,
        "overwrite": True,
        "inputs": resolved,
    }
    endpoint = "/api/dashboards/import"
else:
    body = {
        "dashboard": d,
        "overwrite": True,
        "message": "Imported by dashboards/import.sh",
    }
    endpoint = "/api/dashboards/db"

req = urllib.request.Request(
    url + endpoint,
    data=json.dumps(body).encode(),
    headers={
        "Authorization": "Bearer " + token,
        "Content-Type": "application/json",
    },
    method="POST",
)
try:
    with urllib.request.urlopen(req) as resp:
        out = json.loads(resp.read().decode())
except urllib.error.HTTPError as e:
    sys.stderr.write(f"  HTTP {e.code}: {e.read().decode()}\n")
    sys.exit(1)

uid = out.get("uid") or out.get("importedUid") or "?"
slug = out.get("slug") or out.get("importedUrl") or out.get("url") or "OK"
print(f"  -> uid={uid}  {slug}")
PYEOF
  )
  echo "$result"
done

echo
echo "Done. Open your Grafana to see the imported dashboards."
