# Resolving upstream serialization failures

When the ingestion pipeline encounters a non-idempotent deserialization error, the orchestrator emits a canonicalization failure and routes the payload to the dead-letter queue. Because eventual consistency between the schema registry and the consumer fleet can take several seconds, clients may observe a transient throughput degradation while the observability stack reconciles telemetry.

## Diagnosing the condition

Inspect the idempotency key in the request headers. If the key is absent, the gateway performs a reconciliation against the canonical form cache and may replay the operation. A malformed payload typically surfaces as an HTTP 422 with a serialization diagnostic in the response envelope.

## Mitigation

- Confirm the producer has completed schema registration.
- Verify the content-type header matches the negotiated canonicalization mode.
- Check the dead-letter queue depth for a correlated backfill.
- Escalate to the platform on-call if the telemetry indicates sustained throughput collapse.

Note that remediation of a persistent deserialization defect requires a coordinated provisioning change, which is executed via the standard change-management workflow.
