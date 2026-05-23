#!/bin/bash
# setup-ollama-host.sh
#
# Run this ON YOUR OLLAMA HOST (the box hosting the Ollama daemon — typically
# a GPU box, not the k8s node). It configures ollama for the 4-model pool the
# demo ships by default, then warms each model into VRAM.
#
# What it changes:
#   /etc/systemd/system/ollama.service.d/override.conf with:
#     OLLAMA_HOST=0.0.0.0:11434       — listen on all interfaces (cluster access)
#     OLLAMA_MAX_LOADED_MODELS=4      — keep all 4 demo models hot
#     OLLAMA_NUM_PARALLEL=2           — 2 concurrent requests per model
#     OLLAMA_KEEP_ALIVE=30m           — don't evict idle models for 30 min
#
# VRAM budget (RTX 5090, 32GB):
#   qwen2.5:14b = 19GB, llama3.1:8b = 4GB, qwen2.5:7b = 4GB, qwen2.5:3b = 1GB
#   Total ~28GB with ~4GB headroom for context. Adjust the pool below for
#   smaller GPUs.
#
# Pulls any of the 4 demo models you don't already have. If you've configured
# OLLAMA_MODEL_WEIGHTS differently in .env / helm/values.yaml, edit MODELS
# below to match.
#
# Usage:
#   curl -sSLk https://raw.githubusercontent.com/stephenwagner-grafana/ai-o11y-demo-apps/main/tools/setup-ollama-host.sh | bash
# or:
#   bash tools/setup-ollama-host.sh
set -euo pipefail

MODELS=(qwen2.5:3b qwen2.5:7b llama3.1:8b qwen2.5:14b)

if ! command -v systemctl >/dev/null; then
  echo "systemctl not found — this script targets systemd hosts. Set the env vars by hand:"
  echo "  OLLAMA_HOST=0.0.0.0:11434 OLLAMA_MAX_LOADED_MODELS=4 OLLAMA_NUM_PARALLEL=2 OLLAMA_KEEP_ALIVE=30m ollama serve"
  exit 1
fi

echo "==> Writing /etc/systemd/system/ollama.service.d/override.conf"
sudo mkdir -p /etc/systemd/system/ollama.service.d
sudo tee /etc/systemd/system/ollama.service.d/override.conf >/dev/null <<'OVERRIDE'
[Service]
Environment="OLLAMA_HOST=0.0.0.0:11434"
Environment="OLLAMA_MAX_LOADED_MODELS=4"
Environment="OLLAMA_NUM_PARALLEL=2"
Environment="OLLAMA_KEEP_ALIVE=30m"
OVERRIDE

echo "==> Reloading + restarting ollama"
sudo systemctl daemon-reload
sudo systemctl restart ollama
sleep 3

echo "==> Pulling any missing models"
for m in "${MODELS[@]}"; do
  if ! curl -sS http://localhost:11434/api/tags | grep -q "\"$m\""; then
    echo "    pulling $m..."
    ollama pull "$m" || curl -sS http://localhost:11434/api/pull -d "{\"name\":\"$m\"}" >/dev/null
  else
    echo "    $m already pulled"
  fi
done

echo "==> Warming each model into VRAM"
for m in "${MODELS[@]}"; do
  printf "    warming %s... " "$m"
  if curl -sS http://localhost:11434/api/chat -d "{\"model\":\"$m\",\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}],\"stream\":false,\"keep_alive\":\"30m\"}" >/dev/null; then
    echo "ok"
  else
    echo "FAILED — check VRAM, this model may not fit alongside the others"
  fi
done

echo "==> Loaded in VRAM right now:"
curl -sS http://localhost:11434/api/ps | python3 -c "import json,sys; d=json.load(sys.stdin); print('\n'.join('    '+m['name'] for m in d.get('models',[])) or '    (none)')"

echo
echo "Done. From your k8s cluster, point OLLAMA_BASE_URL at this host:"
HOSTIP=$(hostname -I 2>/dev/null | awk '{print $1}')
echo "    OLLAMA_BASE_URL=http://${HOSTIP:-<this-host-ip>}:11434"
