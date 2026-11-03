"""Sentry and OpenTelemetry stay off unless configured, and don't break requests when on."""

import io

import sentry_sdk
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import observability
from app.main import app

client = TestClient(app)


def test_off_by_default():
    obs = client.get("/health").json()["observability"]
    assert obs == {"sentry": False, "opentelemetry": False}


def test_sentry_turns_on_with_dsn(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN", "https://public@o0.ingest.sentry.io/0")
    try:
        assert observability.init_sentry() is True
        assert sentry_sdk.get_client().is_active()
    finally:
        sentry_sdk.get_client().close(timeout=0)
        sentry_sdk.init()  # reset to a disabled client


def test_otel_traces_requests(monkeypatch):
    from opentelemetry.exporter.otlp.proto.http import metric_exporter, trace_exporter
    from opentelemetry.sdk.metrics.export import ConsoleMetricExporter
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    spans = InMemorySpanExporter()
    monkeypatch.setattr(trace_exporter, "OTLPSpanExporter", lambda: spans)
    monkeypatch.setattr(
        metric_exporter, "OTLPMetricExporter", lambda: ConsoleMetricExporter(out=io.StringIO())
    )
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector.invalid")
    demo = FastAPI()

    @demo.get("/ping")
    def ping():
        return {"ok": True}

    @demo.get("/health")
    def health():
        return {"status": "ok"}

    assert observability.init_otel(demo) is True
    c = TestClient(demo)
    assert c.get("/ping").json() == {"ok": True}
    c.get("/health")

    from opentelemetry import trace

    trace.get_tracer_provider().force_flush()
    routes = {s.attributes.get("http.route") for s in spans.get_finished_spans()}
    assert "/ping" in routes
    assert "/health" not in routes  # health checks are excluded


def test_debug_error_hidden_unless_enabled(monkeypatch):
    assert client.get("/api/debug/error").status_code == 404
    monkeypatch.setenv("ENABLE_DEBUG_ENDPOINTS", "true")
    crashing = TestClient(app, raise_server_exceptions=False)
    assert crashing.get("/api/debug/error").status_code == 500
