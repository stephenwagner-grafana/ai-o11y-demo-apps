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
- name: SERVICE_NAME
  value: {{ $component }}
- name: SERVICE_NAMESPACE
  value: {{ $root.Values.global.serviceNamespace }}
- name: SERVICE_VERSION
  value: {{ $root.Values.global.image.tag | quote }}
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
