# ADR 0014: Use Amazon Bedrock for Production Claim Extraction

**Status:** Proposed
**Date:** 2026-08-11

## Context

The deterministic Acme extractor proves orchestration but cannot process a real sanitized
engagement. Production extraction must return schema-valid candidate claims, preserve exact
provenance, treat evidence as untrusted, avoid cross-customer state, and remain replaceable. It
must never write verified Company Operating Model state directly.

## Decision

Use Amazon Bedrock's Converse API as the first production extraction provider, with a supported
Anthropic Claude model selected by a version-pinned configuration after evaluation. Use Bedrock
structured outputs with a strict JSON schema for candidate claims. Keep the provider behind an
`ExtractionProvider` adapter so the domain contract does not depend on Bedrock response types.

Send one bounded, explicitly delimited evidence segment per request. The model may propose claim
fields and source offsets; AI-FDE reconstructs the evidence quote from the stored segment, verifies
the offsets and hash, validates every field, and rejects the entire result if provenance cannot be
reproduced exactly. All outputs remain candidate claims pending human review.

Persist provider, model/inference-profile ID, prompt version, schema version, input evidence hash,
token counts, bounded result code, and latency. Do not persist or log provider prompts or raw
responses outside the engagement's governed evidence/extraction record. Bedrock model invocation
logging is disabled. Requests use the worker's ECS task role and the deployment's selected region.

Before enablement, the selected model must pass a fixed evaluation suite for exact offsets, no-
claim documents, contradictions, prompt injection inside evidence, malformed input, schema
refusal, retry/idempotency, latency, and cost. If structured output is unsupported or validation
fails, extraction fails closed; the synthetic fixture extractor is never a production fallback.

## Consequences

- AWS workload identity and the deployment data boundary are reused.
- Structured output removes a class of JSON parsing failures but does not make model assertions
  true or deterministic.
- Exact provenance is enforced by application code rather than model-generated quotations or
  provider citation features.
- The exact Claude model can change only through an evaluation-backed configuration release; prior
  extraction runs remain reproducible by recorded version metadata.

## Alternatives

- Direct Anthropic or OpenAI APIs may offer faster access to new model features but add another
  credential, processor, network path, and provider-specific compliance review.
- Self-hosting a model is premature for the volume, team size, and evaluation maturity of V1.
- Rule-only extraction remains useful for deterministic fixtures but does not meet real-engagement
  coverage.

## References

- [Bedrock structured outputs](https://docs.aws.amazon.com/bedrock/latest/userguide/structured-output.html)
- [Bedrock Converse API](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_Converse.html)
