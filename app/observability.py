"""Error tracking (Sentry) and traces/metrics (OpenTelemetry).

Both are off unless configured, so local runs and tests send nothing:

- Sentry:        set SENTRY_DSN (from your Sentry project's Client Keys page).
- OpenTelemetry: set the standard OTEL_EXPORTER_OTLP_ENDPOINT and
                 OTEL_EXPORTER_OTLP_HEADERS (Grafana Cloud gives you both on its
                 "OpenTelemetry" connection page). Data is sent over OTLP/HTTP,
                 so any OTLP backend works, not just Grafana.
"""

import os

from app import __version__

SERVICE_NAME = os.getenv("OTEL_SERVICE_NAME", "python-web-app")
ENVIRONMENT = os.getenv("APP_ENV", "production")
# Health checks run every few seconds; tracing them would only add noise.
EXCLUDED_URLS = "/health"


def init_sentry() -> bool:
    dsn = os.getenv("SENTRY_DSN")
    if not dsn:
        return False

    import sentry_sdk

    sentry_sdk.init(
        dsn=dsn,
        release=f"{SERVICE_NAME}@{__version__}",
        environment=ENVIRONMENT,
        # Share of requests sent as Sentry performance traces (0.0-1.0).
        traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.1")),
        send_default_pii=False,
    )
    return True


def init_otel(app) -> bool:
    if not os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
        return False

    from opentelemetry import metrics, trace
    from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    resource = Resource.create(
        {
            "service.name": SERVICE_NAME,
            "service.version": __version__,
            "deployment.environment": ENVIRONMENT,
        }
    )
    # Exporters read the endpoint and auth headers from the OTEL_* env vars.
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(tracer_provider)

    reader = PeriodicExportingMetricReader(OTLPMetricExporter(), export_interval_millis=60_000)
    metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=[reader]))

    # Traces every request and records request count/duration metrics.
    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=tracer_provider,
        meter_provider=metrics.get_meter_provider(),
        excluded_urls=EXCLUDED_URLS,
    )
    return True
