# loadgen — central K6 + Python orchestrator image.
#
# Two stages:
#   1. `k6src` — pull the K6 binary from the official grafana/k6 image.
#   2. final  — python:3.12-slim + Python deps + K6 binary copied in.
#
# Result: a single image that can `k6 run` synthetic scenarios and runs a
# FastAPI orchestrator that supervises those K6 processes.

FROM grafana/k6:0.54.0 AS k6src

FROM python:3.12-slim AS final

# K6 needs basic CA bundles + libs; python:slim has CA bundles already.
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates \
      curl \
      tini \
  && rm -rf /var/lib/apt/lists/*

# Bring in the K6 binary from the official image.
COPY --from=k6src /usr/bin/k6 /usr/local/bin/k6

WORKDIR /loadgen

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Orchestrator code + K6 scripts + example user pool
COPY orchestrator/ ./orchestrator/
COPY k6/           ./k6/
COPY config/       ./config/

ENV PYTHONUNBUFFERED=1 \
    PORT=8000 \
    LOADGEN_SCRIPTS_DIR=/loadgen/k6/scripts \
    USERS_CONFIG_PATH=/etc/loadgen/users.yaml \
    GATEWAY_URL=http://llm-gateway.llm-gateway.svc.cluster.local \
    LOADGEN_NC_BASE_URL=http://nc-web.neoncart.svc.cluster.local \
    LOADGEN_SB_BASE_URL=http://sb-web.support-bot.svc.cluster.local \
    LOADGEN_POLL_OPEN_INTERVAL_SEC=5

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=30s --retries=3 \
  CMD curl -fsS http://localhost:${PORT}/health || exit 1

# tini reaps zombie K6 processes if any exit unexpectedly.
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["opentelemetry-instrument", "uvicorn", "orchestrator.main:app", "--host", "0.0.0.0", "--port", "8000"]
