"""OTel TracerProvider + MeterProvider setup.

The Sigil SDK emits OTel spans and metrics but does NOT create providers
itself — without providers configured, telemetry goes to the default
no-op and is silently lost. This module is called once at gateway
startup, BEFORE the Sigil client is instantiated.

Env vars consumed (per OTel exporter conventions):
    OTEL_EXPORTER_OTLP_ENDPOINT   (Grafana Cloud OTLP gateway, e.g. https://otlp-gateway-...grafana.net/otlp)
    OTEL_EXPORTER_OTLP_HEADERS    (Authorization=Basic <base64 of "<instance-id>:<glc_token>">)

Service identity comes from:
    SERVICE_NAME      (default: llm-gateway)
    SERVICE_NAMESPACE (default: ai-o11y-demo-apps)
    SERVICE_VERSION   (default: 0.1.0)
"""
from __future__ import annotations

import logging
import os

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

log = logging.getLogger(__name__)

_initialized = False
_tracer_provider: TracerProvider | None = None
_meter_provider: MeterProvider | None = None


def init_otel() -> tuple[TracerProvider, MeterProvider]:
    """Initialise global TracerProvider and MeterProvider.

    Idempotent — safe to call multiple times. Returns the providers so
    callers can shut them down on app teardown.
    """
    global _initialized, _tracer_provider, _meter_provider
    if _initialized:
        return _tracer_provider, _meter_provider  # type: ignore[return-value]

    resource = Resource.create({
        "service.name": os.getenv("SERVICE_NAME", "llm-gateway"),
        "service.namespace": os.getenv("SERVICE_NAMESPACE", "ai-o11y-demo-apps"),
        "service.version": os.getenv("SERVICE_VERSION", "0.1.0"),
    })

    tp = TracerProvider(resource=resource)
    tp.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(tp)

    mp = MeterProvider(
        resource=resource,
        metric_readers=[PeriodicExportingMetricReader(OTLPMetricExporter())],
    )
    metrics.set_meter_provider(mp)

    _tracer_provider = tp
    _meter_provider = mp
    _initialized = True

    log.info("OTel providers initialised (endpoint=%s)", os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "<unset>"))
    return tp, mp


def shutdown_otel() -> None:
    """Flush + shut down providers. Call on app teardown after Sigil client shutdown."""
    global _initialized
    if not _initialized:
        return
    try:
        if _tracer_provider is not None:
            _tracer_provider.shutdown()
        if _meter_provider is not None:
            _meter_provider.shutdown()
    finally:
        _initialized = False
