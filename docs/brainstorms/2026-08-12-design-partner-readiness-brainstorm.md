---
date: 2026-08-12
topic: design-partner-readiness
---

# Design-Partner Readiness

## What We're Building

Close the gap between the synthetic accounts-payable alpha and a controlled design-partner
environment. The milestone adds production-capable evidence parsing and Bedrock extraction,
generalizes workflow naming and generation, completes economic scenarios and the implementation
artifact packet, establishes a dedicated worker identity, and makes sanitized-data access depend on
explicit deployment readiness.

The milestone does not add coding-agent execution or autonomous remediation. Those capabilities
remain post-V1 until the evidence-to-specification lifecycle has been exercised safely with a real
engagement.

## Why This Approach

Three approaches were considered. Building every deferred capability at once would mix customer-
data readiness with a new execution threat surface. Leaving the limitations documented would not
make the product usable with a design partner. The chosen approach closes the trust and product
gaps first, while keeping irreversible external actions behind explicit validation commands.

## Key Decisions

- Treat design-partner readiness as the next milestone; do not redefine the project around SellerFi.
- Keep deterministic Acme extraction only as a development/test fixture; production fails closed
  unless the configured Bedrock provider is available and schema-valid.
- Preserve exact provenance in application code; model-generated quotations are never trusted.
- Support bounded V1 formats without live connectors: TXT, Markdown, CSV, EML, PDF, DOCX, PNG,
  and JPEG.
- Make workflow labels engagement-specific instead of embedding Accounts Payable in generated
  product state.
- Add deterministic low/base/high scenarios rather than an open-ended simulation engine.
- Generate a coherent packet of version-pinned artifacts rather than one oversized Markdown file.
- Accept the dedicated worker identity, AWS deployment, and Bedrock extraction ADR directions;
  implementation and automated checks may proceed, but live Auth0/AWS validation requires real
  credentials and recorded evidence.
- Enable sanitized data only when production OIDC, worker identity, provider, and deployment gates
  are explicitly configured. Development identity remains synthetic-only.
- Continue to defer coding-agent execution and autonomous remediation.

## Open Questions

- The exact Bedrock model or inference-profile ID must be chosen from the deployment account after
  the extraction evaluation suite is run; it is configuration, not a hard-coded architectural
  decision.
- Live Auth0 tenant and AWS account validation remain external release gates because credentials are
  not stored in this repository.

## Next Steps

Proceed through the design-partner readiness implementation plan, shipping locally verifiable
product capabilities before credential-gated deployment validation.
