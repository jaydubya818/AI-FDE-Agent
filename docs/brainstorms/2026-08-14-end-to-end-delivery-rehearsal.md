---
date: 2026-08-14
topic: end-to-end-delivery-rehearsal
---

# End-to-End Delivery Rehearsal

## What We're Building

Add one repeatable command that proves the synthetic Acme journey through the actual browser. The
rehearsal will create isolated PostgreSQL and MinIO resources, migrate and seed them, start the API,
worker, and web application, drive the human approval flow, verify the seven-artifact packet, and
remove every temporary resource afterward.

The repository will also gain a detailed test strategy, delivery plan, and operator demo runbook.
These documents will distinguish local proof from live Auth0, AWS, Bedrock, restore, deletion, and
sanitized-data release gates.

## Why This Approach

Three approaches were considered:

1. Keep the current manual checklist. This is simple but not repeatable and does not produce one
   pass/fail result.
2. Add an API-only demo driver. This is deterministic but misses browser wiring, user feedback,
   stage locks, and the real operator experience.
3. Add an isolated browser rehearsal on top of the existing acceptance suite. This reuses the
   product's current architecture and closes the most important verification gap.

The third approach is the smallest complete solution.

## Key Decisions

- Use only the visibly synthetic Acme fixture.
- Stop at the implementation-ready packet; coding-agent execution remains post-V1.
- Exercise human decisions through the cockpit, not by editing the database.
- Keep backend acceptance and isolation tests as the deeper invariant layer.
- Use dedicated ports, Docker volumes, and a trap-based cleanup path.
- Treat browser console errors, failed requests, incomplete stages, or missing artifacts as failures.
- Keep external production gates open unless they are validated against real services.

## Open Questions

None block implementation. Default ownership is the FDE/product owner for the demo and the
technical owner for rehearsal failures.

## Next Steps

Execute the repeatable end-to-end delivery rehearsal plan.
