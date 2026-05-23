{{/*
Shared template helpers.

Component identity:
  - component slug (e.g. "neoncart-web") -> namespace, image, service name
  - one namespace per logical group (k6-loadgen, neoncart, support-bot,
    ai-o11y-postgres, llm-gateway)
*/}}

{{/* Map component slug -> namespace */}}
{{- define "aio11y.namespaceFor" -}}
{{- $c := . -}}
{{- if eq $c "loadgen" -}}k6-loadgen
{{- else if eq $c "postgres" -}}ai-o11y-postgres
{{- else if eq $c "gateway" -}}llm-gateway
{{- else if hasPrefix "neoncart-" $c -}}neoncart
{{- else if hasPrefix "sb-" $c -}}support-bot
{{- else -}}default
{{- end -}}
{{- end -}}

{{/* Image reference: <registry>/<component>:<tag> */}}
{{- define "aio11y.image" -}}
{{- $root := index . 0 -}}
{{- $component := index . 1 -}}
{{- printf "%s/%s:%s" $root.Values.global.image.registry $component $root.Values.global.image.tag -}}
{{- end -}}

{{/* Common labels on every resource */}}
{{- define "aio11y.labels" -}}
app.kubernetes.io/name: {{ . }}
app.kubernetes.io/part-of: ai-o11y-demo-apps
app.kubernetes.io/managed-by: Helm
{{- end -}}

{{/* Selector labels (subset of common labels — Deployment selector match) */}}
{{- define "aio11y.selectorLabels" -}}
app.kubernetes.io/name: {{ . }}
{{- end -}}

{{/*
Shared env block: OTel + Sigil + service identity.
Pass the component slug as the argument.

Usage in a Deployment:
  env:
  {{- include "aio11y.envOtelSigil" (list $ "nc-chatbot") | nindent 12 }}
*/}}
{{- define "aio11y.envOtelSigil" -}}
{{- $root := index . 0 -}}
{{- $component := index . 1 -}}
# Service identity. Both forms emitted so the gateway's manual OTel init
# (reads SERVICE_NAME) AND `opentelemetry-instrument` auto-instrument
# (reads OTEL_SERVICE_NAME + OTEL_RESOURCE_ATTRIBUTES) are happy.
- name: SERVICE_NAME
  value: {{ $component }}
- name: SERVICE_NAMESPACE
  value: {{ $root.Values.global.serviceNamespace }}
- name: SERVICE_VERSION
  value: {{ $root.Values.global.image.tag | quote }}
- name: OTEL_SERVICE_NAME
  value: {{ $component }}
- name: OTEL_RESOURCE_ATTRIBUTES
  value: "service.namespace={{ $root.Values.global.serviceNamespace }},service.version={{ $root.Values.global.image.tag }}"
- name: OTEL_EXPORTER_OTLP_ENDPOINT
  valueFrom:
    secretKeyRef:
      name: aio11y-otel
      key: endpoint
- name: OTEL_EXPORTER_OTLP_HEADERS
  valueFrom:
    secretKeyRef:
      name: aio11y-otel
      key: headers
# opentelemetry-instrument defaults to gRPC; we only install the HTTP
# exporter package, so force protocol=http/protobuf or autoinstrument
# crashes at startup with "otlp_proto_grpc not found".
- name: OTEL_EXPORTER_OTLP_PROTOCOL
  value: http/protobuf
# Disable exemplars on metrics. The default `trace_based` filter still
# generates an Exemplar struct on observable-gauge callbacks fired
# outside any trace (span_id=None, trace_id=None) — which the OTLP/HTTP
# proto encoder cannot serialize and throws EncodingException on,
# poisoning the whole metric batch. Loadgen + nc-web were both losing
# their entire metric export to this bug.
- name: OTEL_METRICS_EXEMPLAR_FILTER
  value: always_off
# Enable OTLP log export so application logs ship to Grafana Cloud Loki
# (or Alloy) via the same OTLP pipeline as traces + metrics. Default for
# opentelemetry-distro is "console" (stdout only), which means logs only
# reach Loki via cluster-level stdout scraping — without trace_id /
# span_id correlation in the Loki record.
- name: OTEL_LOGS_EXPORTER
  value: otlp
- name: OTEL_PYTHON_LOG_CORRELATION
  value: "true"
- name: SIGIL_ENDPOINT
  valueFrom:
    secretKeyRef:
      name: aio11y-sigil
      key: endpoint
- name: SIGIL_PROTOCOL
  valueFrom:
    secretKeyRef:
      name: aio11y-sigil
      key: protocol
- name: SIGIL_AUTH_MODE
  valueFrom:
    secretKeyRef:
      name: aio11y-sigil
      key: authMode
- name: SIGIL_AUTH_TENANT_ID
  valueFrom:
    secretKeyRef:
      name: aio11y-sigil
      key: tenantId
- name: SIGIL_AUTH_TOKEN
  valueFrom:
    secretKeyRef:
      name: aio11y-sigil
      key: token
{{- end -}}

{{/*
Postgres connection env vars (used by NC apps + seed Job).
*/}}
{{- define "aio11y.envPostgres" -}}
- name: POSTGRES_HOST
  value: postgres.ai-o11y-postgres.svc.cluster.local
- name: POSTGRES_PORT
  value: "5432"
- name: POSTGRES_DB
  valueFrom:
    secretKeyRef:
      name: aio11y-postgres
      key: database
- name: POSTGRES_USER
  valueFrom:
    secretKeyRef:
      name: aio11y-postgres
      key: user
- name: POSTGRES_PASSWORD
  valueFrom:
    secretKeyRef:
      name: aio11y-postgres
      key: password
{{- end -}}

{{/*
LLM Gateway URL env var (used by every specialist).
*/}}
{{- define "aio11y.envGatewayUrl" -}}
- name: GATEWAY_URL
  value: http://llm-gateway.llm-gateway.svc.cluster.local:8000
{{- end -}}
