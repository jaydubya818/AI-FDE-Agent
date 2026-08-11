# Sensitive Telemetry Audit

**Status:** Remediated for the current V1 application surface
**Audit date:** 2026-08-11

## Policy

Normal infrastructure logs may contain generated request IDs, HTTP methods, application-owned
route templates, response status, duration, job IDs, and bounded failure codes. They must not
contain raw URLs or query strings, request or response bodies, cookies, authorization headers,
OIDC codes or state, evidence text, filenames, review notes, provider prompts or responses,
exports, or exception messages derived from untrusted input.

Database audit events and outbox records are customer records, not normal telemetry. They may
contain product decision metadata when necessary for provenance. They remain engagement-scoped,
are covered by row isolation and export, and are removed by the engagement deletion workflow.

## Findings and remediation

### T-001 — OIDC query material in default access logs — High — Resolved

Uvicorn's default access logger records the raw request target. On the OIDC callback this includes
the authorization `code` and `state` query parameters. The API now disables Uvicorn access logs
and emits one application-owned access event containing only a generated request ID, method,
matched route template, status, and duration. A regression test submits a secret query, bearer
header, path value, and body and proves none appears in captured logs.

### T-002 — Worker exception and persisted error leakage — High — Resolved

The worker previously logged exception messages and tracebacks and persisted `str(exception)` to
job and evidence records. Provider and parser failures can include source content or response
material. Worker failures are now classified into bounded codes and safe operator messages. The
original exception text is neither logged nor persisted.

### T-003 — Customer records mistaken for telemetry — Medium — Controlled

Audit and outbox JSON are stored in PostgreSQL and exported with the engagement. They are not sent
to the runtime logger. New event payloads must be reviewed for data minimization and must not copy
raw evidence, secrets, exports, or provider responses.

### T-004 — Future extraction-provider observability — High — Release gate

Production extraction is not implemented. Before enabling it, provider request/response logging,
model invocation logging, tracing payload capture, and error-body logging must default off. Only
provider request IDs, configured model IDs, token counts, latency, bounded result codes, and schema
versions may enter normal telemetry.

## Verification

Run:

```bash
uv run pytest tests/unit/test_telemetry.py
rg -n "logger\.|logging\.|print\(" src apps scripts
```

For each deployment, inspect the platform's load balancer, reverse proxy, APM, exception capture,
object-storage access logging, database statement logging, and model-provider logging separately.
Application redaction cannot protect a secret already captured by an upstream service.
