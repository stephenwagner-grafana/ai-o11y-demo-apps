#!/usr/bin/env bash
# Import dashboard JSON files in this directory to your Grafana via the HTTP API.
#
# Required env:
#   GRAFANA_URL          e.g. https://your-stack.grafana.net
#   GRAFANA_API_TOKEN    Grafana Cloud service-account token (glsa_...)
#
# Optional env:
#   PROM_DS_UID              UID of the Prometheus datasource to bind to ${DS_PROMETHEUS}.
#                            Defaults to "grafanacloud-prom".
#   GRAFANA_STACK_NAMESPACE  K8s-style namespace for the v2 dashboards API
#                            (e.g. "stacks-1372178"). If unset, auto-discovered
#                            from /api/frontend/settings.
#
# Two dashboard schemas are supported per file, auto-detected:
#   - v2 (apiVersion: dashboard.grafana.app/v2) — PUT to the K8s-style v2 API
#     at /apis/dashboard.grafana.app/v2/namespaces/<ns>/dashboards/<name>.
#     PUT is upsert (201 on create, 200 on update). Server-managed metadata
#     (resourceVersion, generation, timestamps, createdBy/updatedBy) is stripped
#     before send.
#   - v1 (legacy or portable export with __inputs) — POST to /api/dashboards/import
#     when __inputs is present, else /api/dashboards/db.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

: "${GRAFANA_URL:?GRAFANA_URL is required, e.g. https://your-stack.grafana.net}"
: "${GRAFANA_API_TOKEN:?GRAFANA_API_TOKEN is required (glsa_... service-account token)}"
PROM_DS_UID="${PROM_DS_UID:-grafanacloud-prom}"
GRAFANA_STACK_NAMESPACE="${GRAFANA_STACK_NAMESPACE:-}"

shopt -s nullglob
JSON_FILES=("$SCRIPT_DIR"/*.json)
if [[ ${#JSON_FILES[@]} -eq 0 ]]; then
  echo "No dashboard JSON files found in $SCRIPT_DIR."
  echo "Use the Grafana Assistant prompt (use-cases-prompt.md) instead, or export"
  echo "your existing dashboard JSON into this directory before re-running."
  exit 0
fi

# Auto-discover the K8s-style namespace from /api/frontend/settings if not set.
if [[ -z "$GRAFANA_STACK_NAMESPACE" ]]; then
  GRAFANA_STACK_NAMESPACE=$(python3 - <<PYEOF
import json, os, sys, urllib.request, urllib.error
url = os.environ["GRAFANA_URL"].rstrip("/") + "/api/frontend/settings"
req = urllib.request.Request(url, headers={"Authorization": "Bearer " + os.environ["GRAFANA_API_TOKEN"]})
try:
    with urllib.request.urlopen(req) as resp:
        ns = json.loads(resp.read().decode()).get("namespace")
        if ns:
            print(ns)
            sys.exit(0)
except urllib.error.HTTPError as e:
    sys.stderr.write(f"namespace discovery failed: HTTP {e.code}\n")
sys.exit(1)
PYEOF
)
  if [[ -z "$GRAFANA_STACK_NAMESPACE" ]]; then
    echo "Could not auto-discover GRAFANA_STACK_NAMESPACE. Set it explicitly (e.g. stacks-<stack_id>) and re-run."
    exit 1
  fi
fi
echo "Namespace: $GRAFANA_STACK_NAMESPACE"

for fp in "${JSON_FILES[@]}"; do
  name=$(basename "$fp" .json)
  echo "Importing $name..."
  result=$(PROM_DS_UID="$PROM_DS_UID" \
    GRAFANA_URL="$GRAFANA_URL" \
    GRAFANA_API_TOKEN="$GRAFANA_API_TOKEN" \
    GRAFANA_STACK_NAMESPACE="$GRAFANA_STACK_NAMESPACE" \
    FP="$fp" python3 <<'PYEOF'
import json, os, sys, urllib.request, urllib.error

fp = os.environ["FP"]
url = os.environ["GRAFANA_URL"].rstrip("/")
token = os.environ["GRAFANA_API_TOKEN"]
prom_uid = os.environ["PROM_DS_UID"]
ns = os.environ["GRAFANA_STACK_NAMESPACE"]

with open(fp) as f:
    d = json.load(f)

api_version = d.get("apiVersion", "")
is_v2 = api_version.startswith("dashboard.grafana.app/")

if is_v2:
    # K8s-style v2 dashboard. Strip server-managed metadata so the PUT is
    # accepted on a fresh stack (where these refer to nothing) and idempotent
    # on a known stack. Set the namespace to the target stack.
    md = d.setdefault("metadata", {})
    res_name = md.get("name")
    if not res_name:
        sys.stderr.write("  ERROR: v2 dashboard missing metadata.name\n")
        sys.exit(1)
    for k in ("resourceVersion", "generation", "creationTimestamp"):
        md.pop(k, None)
    ann = md.get("annotations") or {}
    for k in ("grafana.app/createdBy", "grafana.app/updatedBy",
              "grafana.app/updatedTimestamp", "grafana.app/saved-from-ui"):
        ann.pop(k, None)
    md["annotations"] = ann
    md["namespace"] = ns

    endpoint = f"/apis/dashboard.grafana.app/v2/namespaces/{ns}/dashboards/{res_name}"
    req = urllib.request.Request(
        url + endpoint,
        data=json.dumps(d).encode(),
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
        method="PUT",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            status = resp.status
            out = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        sys.stderr.write(f"  HTTP {e.code}: {e.read().decode()[:400]}\n")
        sys.exit(1)
    action = "created" if status == 201 else "updated"
    uid = out.get("metadata", {}).get("uid", "?")
    title = out.get("spec", {}).get("title", "")
    print(f"  -> v2 {action}  uid={uid}  title={title!r}")
    sys.exit(0)

# --- v1 path (legacy / portable export) ---
d.pop("id", None)
d.pop("version", None)

inputs = d.get("__inputs") or []
if inputs:
    resolved = []
    for inp in inputs:
        if inp.get("type") == "datasource" and inp.get("pluginId") == "prometheus":
            resolved.append({"name": inp["name"], "type": "datasource",
                             "pluginId": "prometheus", "value": prom_uid})
        else:
            resolved.append({"name": inp["name"], "type": inp.get("type", "datasource"),
                             "pluginId": inp.get("pluginId", ""), "value": ""})
    body = {"dashboard": d, "overwrite": True, "inputs": resolved}
    endpoint = "/api/dashboards/import"
else:
    body = {"dashboard": d, "overwrite": True, "message": "Imported by dashboards/import.sh"}
    endpoint = "/api/dashboards/db"

req = urllib.request.Request(
    url + endpoint, data=json.dumps(body).encode(),
    headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
    method="POST",
)
try:
    with urllib.request.urlopen(req) as resp:
        out = json.loads(resp.read().decode())
except urllib.error.HTTPError as e:
    sys.stderr.write(f"  HTTP {e.code}: {e.read().decode()[:400]}\n")
    sys.exit(1)
uid = out.get("uid") or out.get("importedUid") or "?"
slug = out.get("slug") or out.get("importedUrl") or out.get("url") or "OK"
print(f"  -> v1 uid={uid}  {slug}")
PYEOF
  )
  echo "$result"
done

echo
echo "Done. Open your Grafana to see the imported dashboards."
