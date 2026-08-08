# Standards and External Guidance

These sources inform the architecture. They do not replace product-specific threat modeling or legal review.

## AI Risk and Human Oversight

- [NIST AI Risk Management Framework resources](https://airc.nist.gov/) support explicit governance, mapping, measurement, and management of AI risk.
- [NIST Generative AI Profile](https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.600-1.pdf) extends the AI RMF for generative systems and informs evaluation, provenance, incident handling, and human oversight.
- [OWASP Agentic AI threats and mitigations](https://genai.owasp.org/resource/agentic-ai-threats-and-mitigations/) informs least privilege, bounded tool access, approval gates, and sandbox controls.

## Provenance

- [W3C PROV-O](https://www.w3.org/TR/prov-o/) defines stable concepts for entities, activities, agents, derivation, use, and responsibility. AI-FDE uses the concepts without requiring RDF in V1.

## Data Isolation

- [PostgreSQL row security policies](https://www.postgresql.org/docs/current/ddl-rowsecurity.html) support default-deny row access. AI-FDE pairs them with application authorization and isolation tests because table owners and privileged roles can bypass policies.

## Telemetry

- [OpenTelemetry semantic conventions](https://opentelemetry.io/docs/specs/semconv/) provide shared naming for traces, metrics, logs, and events.
- Generative AI conventions are still evolving. AI-FDE should pin the convention version it emits and keep sensitive prompt or evidence content opt-in.
