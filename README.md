# OpenTelemetry PCI Telemetry Sanitization Lab

## Visual demo: Raw vs. PCI Sanitizer

Start with `docker compose up -d --build`, then open
**http://localhost:3000/d/pci-demo**. The dashboard is provisioned automatically.

1. Click **Zahlung starten**: Raw shows the synthetic PAN; PCI keeps the safe
   payment fields and removes `payment.card.pan`.
2. Click **Leak testen**: Raw shows the unsafe payment span; PCI drops it.
   This scenario deliberately uses `attempt_4111111111111111` to exercise the
   formerly missed underscore boundary.
3. Allow approximately 5–15 seconds for export, scraping and dashboard refresh.
   The links return to the dashboard filtered to the new `demo.run_id`.
4. Open the trace links below each column to inspect the actual stored spans.
   Set the Run-ID field to `.*` to show all demo runs in the selected time range.

Each demo action emits two independent traces with the same synthetic payment
attributes and `demo.run_id`, but different trace/span IDs. Each provider exports
only to its designated collector. This deliberate lab design prevents the two
copies from being merged in a single trace view. Both traces have a safe
`payment-demo` parent so that even the sanitized leak trace can be opened; only
the unsafe `process-payment-leak` child is dropped.

The orange dashboard counter comes from the Collector's actual filter metrics.
It counts **all filtered spans since Collector start**, not only the selected
run. Missing telemetry is not labeled as a successful drop. The green received
counter includes the safe parent spans. Collector metrics are scraped every
five seconds over the internal Docker network.

The sanitized service/container is named **`pci-sanitizer-collector`**, configured
by `collector/pci-sanitizer-collector.yaml`. Its application telemetry retains
`service.name = pci-demo-payment-app`; the raw service remains
`pci-demo-payment-app-raw`.

When upgrading a previously running checkout, remove the old gateway container
before starting the renamed service (it owns ports 4317/4318):

```bash
docker stop otel-pci-gateway
docker rm otel-pci-gateway
docker compose up -d --build
```

The existing `lgtm-data` volume is retained. Old traces remain visible in broader
time ranges; use the current run filter for the new demo.

Dashboard/provisioning sources are in `grafana/`. The action links assume a local
demo on `localhost:8000` and `localhost:3000`. For remote use, adjust the dashboard
links and set `GRAFANA_PUBLIC_URL` on the app. Exporter addresses can be overridden
with `PCI_OTLP_ENDPOINT` and `RAW_OTLP_ENDPOINT`.

## Overview

This repository provides a local proof-of-concept environment for testing how
OpenTelemetry telemetry can be sanitized before it is exported to a centralized
observability backend.

The lab is designed around a common enterprise scenario:

- applications may accidentally emit payment-card-related data,
- telemetry is forwarded through a centralized OpenTelemetry Collector gateway,
- the gateway applies strict sanitization and filtering policies,
- sanitized telemetry is exported to an observability backend,
- a parallel raw pipeline is used for comparison and validation.

The primary objective is to demonstrate a security boundary between:

```text
PCI-sensitive application telemetry
```

and:

```text
centralized operational observability
```

The sanitized pipeline follows a **default-deny strategy**. Only explicitly
approved telemetry attributes are exported. Any sensitive value detected in an
allowed field causes the affected telemetry record to be dropped.

> This repository is a technical lab and not a certification artifact.
> Running this configuration does not by itself make a system PCI DSS compliant
> or automatically remove a downstream system from PCI DSS scope.

---

# Architecture

The lab runs four main components:

```text
                           ┌─────────────────────────────┐
                           │   Demo Payment Application  │
                           │                             │
                           │  Python / FastAPI / OTel    │
                           └──────────────┬──────────────┘
                                          │
                              paired traces with distinct IDs
                                          │
                      ┌───────────────────┴───────────────────┐
                      │                                       │
                      v                                       v
          ┌─────────────────────────┐           ┌─────────────────────────┐
          │ PCI OTel Gateway        │           │ RAW OTel Collector      │
          │                         │           │                         │
          │ Default Deny            │           │ No security policies    │
          │ Allowlist               │           │ No redaction            │
          │ Content inspection      │           │ No filtering            │
          │ Redaction               │           │                         │
          │ Drop-on-detection       │           │ service.name rewritten  │
          └────────────┬────────────┘           └────────────┬────────────┘
                       │                                     │
                       │ sanitized telemetry                 │ raw telemetry
                       │                                     │
                       └──────────────────┬──────────────────┘
                                          │
                                          v
                           ┌─────────────────────────────┐
                           │ Grafana OpenTelemetry LGTM  │
                           │                             │
                           │ Grafana                     │
                           │ Tempo                       │
                           │ Loki                        │
                           │ Prometheus                  │
                           └─────────────────────────────┘
```

The raw collector exists only as a validation path.

It allows direct comparison between:

```text
RAW telemetry
```

and:

```text
SANITIZED telemetry
```

The raw collector must not be interpreted as a recommended production
architecture for PCI-related environments.

---

# Repository Structure

```text
otel-pci-lab/
│
├── README.md
├── docker-compose.yml
│
├── app/
│   ├── app.py
│   ├── Dockerfile
│   └── requirements.txt
│
├── collector/
│   ├── pci-sanitizer-collector.yaml
│   └── otel-collector-raw.yaml
│
└── grafana/
    ├── dashboards/
    │   └── pci-demo.json
    ├── provisioning/
    │   └── demo.yaml
    └── prometheus.yaml
```

## Components

### `app/`

Contains the demo payment application.

The application is intentionally instrumented to generate telemetry that may
contain synthetic sensitive payment-card data.

### `collector/pci-sanitizer-collector.yaml`

Contains the PCI-oriented sanitization pipeline.

This collector represents the security boundary before telemetry is exported to
the centralized observability platform.

### `collector/otel-collector-raw.yaml`

Contains the comparison collector.

No PCI filtering or sanitization is applied.

The collector rewrites the service name to:

```text
pci-demo-payment-app-raw
```

so that raw telemetry can be distinguished from sanitized telemetry in Grafana.

---

# PCI Data Categories

PCI DSS defines payment account data as Cardholder Data and Sensitive
Authentication Data.

The important categories for this lab are:

## Cardholder Data

- Primary Account Number (PAN)
- Cardholder Name
- Expiration Date
- Service Code

## Sensitive Authentication Data

- Full Track Data
- Card Verification Codes
- PIN
- PIN Block

Examples of card verification codes include names such as:

```text
CVV
CVV2
CVC
CVC2
CID
CAV2
CVN2
```

The application in this lab uses synthetic examples only.

Never use real cardholder or authentication data in this repository.

---

# Security Design Principles

The sanitized collector implements multiple defensive controls.

The design deliberately does not rely on a single regular expression or a
single redaction processor.

The security model is:

```text
prevent
   +
restrict
   +
inspect
   +
drop
```

---

# Stage 1 - Default-Deny Attribute Policy

The first control is an explicit schema allowlist.

The collector removes every telemetry attribute that is not explicitly
approved.

Conceptually:

```text
Incoming attributes
       |
       v
Is attribute explicitly approved?
       |
   +---+---+
   |       |
  NO      YES
   |       |
 DROP      v
       Continue inspection
```

The current trace allowlist contains fields such as:

```text
http.route
http.response.status_code
duration_ms
payment.status
payment.attempt_id
```

The current resource allowlist contains:

```text
service.name
deployment.environment.name
```

This means fields such as the following do not cross the boundary:

```text
payment.card.pan
payment.card.cvv
payment.card.pin
payment.card.pin_block
payment.card.track1
payment.card.track2
payment.cardholder.name
payment.card.expiration_date
payment.card.service_code
payment.message
customer.id
http.request.body
http.response.body
url.full
authorization
cookie
db.statement
exception.message
```

unless they are explicitly added to the approved schema.

The implementation uses the OpenTelemetry Transformation Language `keep_keys`
function.

The principle is:

```text
unknown field = denied
```

rather than:

```text
unknown field = allowed
```

---

# Stage 2 - Content Inspection and Redaction

Allowlisting attributes alone is not sufficient.

An approved field can still contain unsafe content.

Example:

```text
payment.attempt_id = "attempt_4111111111111111"
```

The key itself is approved, but its value contains a PAN.

For that reason, telemetry that survives the allowlist is inspected again by
the OpenTelemetry redaction processor.

The current policy checks for patterns such as:

## PAN-like values

Contiguous numeric values:

```text
4111111111111111
```

Formatted values:

```text
4111 1111 1111 1111
4111-1111-1111-1111
```

## Track Data

Examples:

```text
%B4111111111111111^CARDHOLDER/TEST^...
```

and:

```text
;4111111111111111=...
```

## Authentication Secrets

The lab additionally inspects values resembling:

```text
Bearer <token>
Basic <credentials>
```

This is not strictly limited to PCI data but protects the observability
boundary from common authentication-secret leakage.

---

# Stage 3 - Drop on Detection

The sanitized pipeline does not simply trust redaction.

If the redaction processor detects a sensitive pattern in a field that survived
the allowlist, the record is considered unsafe.

The redaction processor adds diagnostic metadata such as:

```text
redaction.masked.count
```

The subsequent filter processor checks this value.

If:

```text
redaction.masked.count > 0
```

the complete telemetry record is dropped.

Conceptually:

```text
Telemetry Record
       |
       v
Schema Allowlist
       |
       v
Content Inspection
       |
       v
Sensitive pattern detected?
       |
    +--+--+
    |     |
   YES    NO
    |     |
    v     v
  DROP   EXPORT
```

This implements a fail-closed behavior for unexpected sensitive content in
otherwise approved fields.

---

# Why Default Deny?

A blocklist-only model assumes that every dangerous field name or sensitive
data representation is already known.

For example:

```text
card_number
payment.pan
credit_card_number
cc_number
customer_message
request_payload
metadata
```

Applications can introduce arbitrary new fields over time.

A default-deny model reverses the assumption.

Instead of asking:

```text
"Is this field known to be dangerous?"
```

the policy asks:

```text
"Is this field explicitly approved for export?"
```

Only approved fields cross the observability boundary.

This significantly reduces the risk created by application changes,
instrumentation libraries, debugging attributes and free-form metadata.

---

# Why Free-Form Text Is Dangerous

Fields such as the following are difficult to secure reliably:

```text
message
exception.message
db.statement
url.full
http.request.body
http.response.body
request
response
metadata
```

A key named `message` may contain almost anything.

For example:

```text
Payment authorized
```

is harmless.

But the same field could contain:

```text
Payment authorized for PAN 4111111111111111
```

or:

```text
CVV=123
```

or an entire serialized request body.

For this reason, payment applications should prefer:

```text
structured events
```

over:

```text
unbounded free-form messages
```

Example:

```text
event.name = payment.authorization
payment.status = authorized
payment.attempt_id = attempt-123
```

is safer than:

```text
message = "Payment authorized for card 4111111111111111"
```

---

# Application-Side Controls

The OpenTelemetry Collector should not be the first or only security control.

Applications should avoid generating sensitive telemetry in the first place.

Recommended application-side rules include:

- never log PAN,
- never log CVV/CVC/CID,
- never log PIN or PIN blocks,
- never log full track data,
- do not automatically instrument complete payment request bodies,
- do not automatically instrument complete payment response bodies,
- do not record authorization headers,
- do not record cookies or session tokens,
- avoid arbitrary database statements,
- avoid uncontrolled exception messages,
- emit structured, documented events,
- export normalized error codes instead of raw payloads.

The collector should therefore be considered an additional security boundary,
not a replacement for secure application instrumentation.

---

# Raw Collector

The repository intentionally includes a second collector with no sanitization
policies.

Its purpose is validation only.

The raw collector receives the same telemetry as the sanitized collector.

It rewrites:

```text
service.name
```

to:

```text
pci-demo-payment-app-raw
```

and adds:

```text
pipeline.variant = raw
```

This makes the two pipelines distinguishable in Grafana.

The expected comparison is:

| Raw Pipeline                               | Sanitized Pipeline                  |
| ------------------------------------------ | ----------------------------------- |
| Sensitive attributes may be present        | Non-approved attributes are removed |
| PAN may be visible                         | PAN is not exported                 |
| Track data may be visible                  | Track data is not exported          |
| Free-form sensitive content may be visible | Unsafe content is rejected          |
| Leak test span exists                      | Leak test span is dropped           |

The raw pipeline must only be used with synthetic test data.

---

# Demo Endpoints

The application exposes two relevant endpoints.

## Normal Payment Telemetry

```text
GET /payment
```

This endpoint creates telemetry containing:

```text
payment.status = authorized
payment.attempt_id = attempt-123
payment.card.pan = 4111111111111111
```

Expected behavior:

### Raw pipeline

The PAN remains visible.

### Sanitized pipeline

`payment.card.pan` is removed by the default-deny policy.

The safe fields remain:

```text
payment.status
payment.attempt_id
```

---

## Leak Test

```text
GET /payment-leak
```

This endpoint intentionally places a synthetic PAN inside an approved field:

```text
payment.attempt_id = attempt_4111111111111111
```

This simulates a realistic failure mode where:

- the attribute name is approved,
- the application emits unexpected sensitive content.

Expected behavior:

### Raw pipeline

The span is exported.

### Sanitized pipeline

The value is detected by the redaction processor.

The processor records a non-zero:

```text
redaction.masked.count
```

and the filter processor drops the entire span.

The span must therefore not appear in the sanitized Tempo data.

---

# Collector Processing Order

Processor order is security-relevant.

The sanitized pipeline is executed in this order:

```text
OTLP Receiver
     |
     v
Memory Limiter
     |
     v
Default-Deny Allowlist
     |
     v
Content Inspection / Redaction
     |
     v
Drop-on-Detection Filter
     |
     v
Batch
     |
     v
OTLP Export
```

The order is deliberate.

## Allowlist First

Unexpected attributes are removed before further processing.

## Inspection Second

Remaining approved values are inspected for unexpected sensitive content.

## Filter Third

Any record where sensitive content was detected is discarded.

## Export Last

Only records that passed every stage leave the security boundary.

---

# Observability Backend

The backend uses the Grafana OpenTelemetry LGTM image.

It provides a local OpenTelemetry-compatible observability stack including:

- Grafana
- Tempo
- Loki
- Prometheus
- OpenTelemetry Collector components

Grafana is available at:

```text
http://localhost:3000
```

The demo application is available at:

```text
http://localhost:8000
```

---

# Running the Lab

## Prerequisites

Install:

- Docker Desktop
- Docker Compose
- Git

Verify:

```bash
docker --version
docker compose version
git --version
```

---

## Start the Environment

From the repository root:

```bash
docker compose up -d --build
```

Verify the containers:

```bash
docker ps
```

Expected containers:

```text
otel-pci-payment-app
pci-sanitizer-collector
otel-pci-raw
otel-pci-lgtm
```

---

# Generate Test Data

Generate a normal payment trace:

```text
http://localhost:8000/payment
```

Generate an intentional allowlist bypass test:

```text
http://localhost:8000/payment-leak
```

---

# Inspect Traces

Open Grafana:

```text
http://localhost:3000
```

Navigate to:

```text
Explore -> Tempo
```

The sanitized service is:

```text
pci-demo-payment-app
```

The raw comparison service is:

```text
pci-demo-payment-app-raw
```

---

# Expected Results

## `/payment`

### Raw

Expected attributes include:

```text
payment.status = authorized
payment.attempt_id = attempt-123
payment.card.pan = 4111111111111111
```

### Sanitized

Expected attributes include only the approved fields:

```text
payment.status = authorized
payment.attempt_id = attempt-123
```

The following must not exist:

```text
payment.card.pan
```

---

## `/payment-leak`

### Raw

Expected:

```text
process-payment-leak
```

exists and contains:

```text
payment.attempt_id = attempt_4111111111111111
```

### Sanitized

Expected:

```text
process-payment-leak
```

does not exist.

The entire span is dropped.

---

# Validation Checklist

The sanitized pipeline should satisfy all of the following lab tests:

- [ ] PAN attribute is removed.
- [ ] PAN embedded in an approved field is detected.
- [ ] PAN with spaces is detected.
- [ ] PAN with hyphens is detected.
- [ ] Track-like data is not exported.
- [ ] Non-approved attributes are removed.
- [ ] Safe approved attributes remain.
- [ ] A sensitive value in an approved field causes the record to be dropped.
- [ ] Raw and sanitized pipelines can be compared independently.
- [ ] No sensitive value is copied into diagnostic or security metadata.

---

# Production Considerations

This lab intentionally simplifies several production concerns.

A production implementation should also evaluate:

- collector high availability,
- TLS and mutual TLS,
- authentication between applications and collectors,
- network segmentation,
- configuration management,
- policy versioning,
- collector configuration review,
- collector access control,
- retry queues,
- persistent queues,
- dead-letter handling,
- memory buffering,
- sampling,
- log bodies,
- span events,
- metrics,
- exemplars,
- trace state and baggage,
- resource attributes,
- instrumentation library behavior,
- automatic HTTP capture,
- database instrumentation,
- exception instrumentation,
- collector self-telemetry.

Particular attention should be given to any location where unsanitized telemetry
may be persisted before sanitization.

Examples include:

```text
application log files
agent buffers
collector persistent queues
retry queues
dead-letter queues
message brokers
temporary files
debug exporters
packet captures
```

Any such location can become part of the security and compliance assessment.

---

# Application Observability vs. PCI Audit Logging

Operational observability and PCI security audit logging should be treated as
different architectural concerns.

## Operational Observability

Examples:

```text
payment.status = authorized
payment_latency_ms = 145
http.response.status_code = 200
```

These signals support:

- performance analysis,
- reliability,
- troubleshooting,
- application health,
- capacity planning.

With appropriate isolation and sanitization, such telemetry may be suitable for
a centralized operational observability platform.

## PCI Security Audit Logging

Examples:

```text
administrator login failed
privilege changed
audit logging disabled
security control modified
```

Security audit logs may be required for PCI security monitoring, retention and
investigation.

If the central observability platform becomes the authoritative system for
PCI-related security audit logging, alerting or security control operation, its
scope must be assessed separately.

A recommended architecture is therefore:

```text
PCI Security / Audit Logging
        |
        v
Dedicated in-scope security platform
```

and independently:

```text
Operational Telemetry
        |
        v
PCI sanitization boundary
        |
        v
Central observability platform
```

---

# Security Boundary

The key architectural principle demonstrated by this repository is:

```text
The centralized observability backend must never be trusted to perform the
primary PCI sanitization.
```

Sanitization must occur before telemetry crosses the intended PCI security
boundary.

The backend should only receive telemetry that has already passed the approved
export policy.

---

# Limitations

The current implementation has known limitations.

## Pattern Matching Is Not DLP

Regular expressions can detect many obvious values but are not equivalent to a
dedicated Data Loss Prevention system.

For example, PAN detection may eventually benefit from:

- card-number candidate detection,
- Luhn validation,
- issuer-range validation,
- structured payload inspection,
- dedicated DLP engines.

## Attribute Allowlisting Does Not Inspect Every OTel Field

OpenTelemetry signals contain data outside regular span attributes.

Examples include:

- span names,
- span events,
- log bodies,
- metric attributes,
- baggage,
- resource attributes,
- exception data.

A production policy must explicitly consider each relevant signal and field.

## Synthetic Data Only

All payment-card values in this repository are synthetic test values.

Never use real:

- PANs,
- cardholder data,
- CVVs,
- PINs,
- track data,
- authentication secrets.

---

# Compliance Disclaimer

This repository demonstrates technical telemetry-sanitization controls.

It does not provide:

- PCI DSS certification,
- a PCI scope determination,
- legal advice,
- compliance attestation,
- a Qualified Security Assessor opinion.

Whether a downstream observability platform is considered outside the Cardholder
Data Environment depends on the complete architecture, connectivity, security
functions, administrative access, data flows and applicable PCI DSS scoping
rules.

The OpenTelemetry redaction processor itself should also be considered one line
of defense rather than the sole compliance control.

---

# References

## PCI Security Standards Council

PCI DSS account data includes:

- PAN,
- cardholder name,
- expiration date,
- service code,
- full track data,
- card verification codes,
- PINs and PIN blocks.

See the PCI Security Standards Council documentation for authoritative
definitions and current requirements.

## OpenTelemetry Collector

Relevant OpenTelemetry Collector components used by this project include:

- Transform Processor
- Redaction Processor
- Filter Processor
- OTLP Receiver
- OTLP Exporter

The redaction processor supports fail-closed attribute allowlisting and
pattern-based value masking.

The filter processor supports dropping telemetry based on OpenTelemetry
Transformation Language conditions.

---

# Future Improvements

Potential extensions for this lab include:

- automated end-to-end leak tests,
- Luhn-based PAN validation,
- log-body sanitization tests,
- span-event sanitization,
- baggage sanitization,
- metric sanitization,
- CVV/CVC value-detection scenarios,
- Track 1 and Track 2 validation,
- secret scanning,
- dedicated DLP integration,
- CI security tests,
- configuration regression tests,
- policy-as-code validation,
- collector metrics for dropped records,
- separate security-event export,
- Kubernetes deployment examples,
- Elastic backend integration,
- mTLS between applications and collectors.

---

# License

Choose an appropriate open-source license for the repository.

For a small demonstration project, common options include:

```text
Apache-2.0
MIT
```

OpenTelemetry itself is licensed under Apache License 2.0.
