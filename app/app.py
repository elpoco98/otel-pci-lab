"""Synthetic payment demo: independent traces for raw and sanitized exports."""
import os
import secrets
from contextlib import asynccontextmanager
from urllib.parse import urlencode

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

TEST_PAN = "4111111111111111"
GRAFANA_URL = os.getenv("GRAFANA_PUBLIC_URL", "http://localhost:3000").rstrip("/")
providers = {}


@asynccontextmanager
async def lifespan(app):
    for variant, endpoint in {
        "sanitized": os.getenv("PCI_OTLP_ENDPOINT", "http://pci-sanitizer-collector:4317"),
        "raw": os.getenv("RAW_OTLP_ENDPOINT", "http://otel-raw:4317"),
    }.items():
        provider = TracerProvider(resource=Resource.create({
            "service.name": "pci-demo-payment-app",
            "deployment.environment.name": "home-lab",
        }))
        provider.add_span_processor(BatchSpanProcessor(
            OTLPSpanExporter(endpoint=endpoint, insecure=True),
            schedule_delay_millis=500,
        ))
        providers[variant] = provider
    yield
    for provider in providers.values():
        provider.shutdown()
    providers.clear()


app = FastAPI(lifespan=lifespan)


def emit_payment(leak=False):
    # Letters only: correlation IDs must not resemble PAN candidates.
    run_id = "run-" + "".join(chr(97 + n) for b in secrets.token_bytes(12) for n in (b >> 4, b & 15))
    scenario = "leak" if leak else "payment"
    common = {"demo.run_id": run_id, "demo.scenario": scenario}
    attributes = {
        **common,
        "payment.status": "authorized",
        "payment.attempt_id": f"attempt_{TEST_PAN}" if leak else "attempt-123",
    }
    if not leak:
        attributes["payment.card.pan"] = TEST_PAN

    trace_ids = {}
    for variant, provider in providers.items():
        tracer = provider.get_tracer("pci-demo")
        # An empty context prevents HTTP instrumentation from joining the pair.
        with tracer.start_span("payment-demo", context=Context(), attributes=common) as root:
            trace_ids[variant] = format(root.get_span_context().trace_id, "032x")
            with tracer.start_span(
                "process-payment-leak" if leak else "process-payment",
                context=trace.set_span_in_context(root, Context()),
                attributes=attributes,
            ):
                pass
    return {"status": "processed", "scenario": scenario, "run_id": run_id, "trace_ids": trace_ids}


@app.get("/")
def root():
    return {"status": "ok", "service": "pci-demo-payment-app", "dashboard": GRAFANA_URL + "/d/pci-demo"}


@app.get("/payment")
def payment():
    return emit_payment()


@app.get("/payment-leak")
def payment_leak():
    return emit_payment(leak=True)


@app.get("/demo/payment")
def demo_payment():
    return demo_redirect(emit_payment())


@app.get("/demo/payment-leak")
def demo_payment_leak():
    return demo_redirect(emit_payment(leak=True))


def demo_redirect(result):
    params = urlencode({"var-run_id": result["run_id"], "from": "now-15m", "to": "now"})
    return RedirectResponse(GRAFANA_URL + "/d/pci-demo?" + params, status_code=303)
