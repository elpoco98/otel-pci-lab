from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

app = FastAPI()

resource = Resource.create({
    "service.name": "pci-demo-payment-app",
    "deployment.environment.name": "home-lab"
})

provider = TracerProvider(resource=resource)

# PCI / sanitized collector
pci_exporter = OTLPSpanExporter(
    endpoint="http://otel-gateway:4317",
    insecure=True
)

# RAW collector without policies
raw_exporter = OTLPSpanExporter(
    endpoint="http://otel-raw:4317",
    insecure=True
)

provider.add_span_processor(
    BatchSpanProcessor(pci_exporter)
)

provider.add_span_processor(
    BatchSpanProcessor(raw_exporter)
)

trace.set_tracer_provider(provider)

tracer = trace.get_tracer("pci-demo")

TEST_PAN = "4111111111111111"


@app.get("/")
def root():
    return {
        "status": "ok",
        "service": "pci-demo-payment-app"
    }


@app.get("/payment")
def payment():
    with tracer.start_as_current_span("process-payment") as span:
        span.set_attribute(
            "payment.status",
            "authorized"
        )

        span.set_attribute(
            "payment.attempt_id",
            "attempt-123"
        )

        # Absichtlich sensitive Daten für das Lab
        span.set_attribute(
            "payment.card.pan",
            TEST_PAN
        )

    return {
        "status": "processed"
    }


@app.get("/payment-leak")
def payment_leak():
    with tracer.start_as_current_span("process-payment-leak") as span:
        span.set_attribute(
            "payment.status",
            "authorized"
        )

        span.set_attribute(
            "payment.attempt_id",
            f"attempt-{TEST_PAN}"
        )

    return {
        "status": "processed",
        "test": "sensitive value placed in allowed field"
    }