import os

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

app = FastAPI()

resource = Resource.create({
    "service.name": "pci-demo-payment-app"
})

provider = TracerProvider(resource=resource)

exporter = OTLPSpanExporter(
    endpoint=os.getenv(
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "http://otel-gateway:4317"
    ),
    insecure=True
)

provider.add_span_processor(
    BatchSpanProcessor(exporter)
)

trace.set_tracer_provider(provider)

tracer = trace.get_tracer("pci-demo")

TEST_PAN = "4111111111111111"
TEST_PAN_SPACES = "4111 1111 1111 1111"


@app.get("/")
def root():
    return {
        "status": "ok",
        "service": "pci-demo-payment-app"
    }


@app.get("/payment")
def payment():
    with tracer.start_as_current_span("process-payment") as span:
        span.set_attribute("customer.id", "customer-123")
        span.set_attribute("payment.amount", 42.50)

        span.set_attribute(
            "payment.card.number",
            TEST_PAN
        )

        span.set_attribute(
            "payment.message",
            f"Payment with card {TEST_PAN}"
        )

        span.set_attribute(
            "payment.message.spaces",
            f"Payment with card {TEST_PAN_SPACES}"
        )

    return {
        "status": "processed"
    }