"""OpenTelemetry tracing.

* ``OTEL_ENABLED=false`` (default): the OpenTelemetry API calls are no-ops.
* ``OTEL_EXPORTER=console``: print spans to stdout (local debugging).
* ``OTEL_EXPORTER=gcp``: export to Cloud Trace. Authentication uses the Cloud Run
  service account, so no keys are needed.
* ``OTEL_EXPORTER=otlp``: send spans over OTLP/HTTP to ``OTEL_OTLP_ENDPOINT``.

Replaces the original platform's SigNoz/OTLP-proxy setup.
"""

import logging

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

from app.config import Settings

logger = logging.getLogger(__name__)


def configure_observability(app: FastAPI, settings: Settings) -> None:
    if not settings.otel_enabled:
        return

    provider = TracerProvider(resource=Resource.create({"service.name": settings.app_name}))
    if settings.otel_exporter == "gcp":
        from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter

        exporter = CloudTraceSpanExporter(project_id=settings.gcp_project_id or None)
    elif settings.otel_exporter == "otlp":
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        exporter = OTLPSpanExporter(endpoint=settings.otel_otlp_endpoint)
    else:
        exporter = ConsoleSpanExporter()
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.instrument_app(app)
    logger.info("Tracing enabled (exporter=%s)", settings.otel_exporter)
