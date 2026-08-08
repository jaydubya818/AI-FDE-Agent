# AI-FDE

AI-FDE is a stateful operating system for Forward Deployed Engineers.

It helps one human FDE understand how a customer actually operates, redesign one workflow around the right mix of people, deterministic software, and AI, and produce an implementation-ready plan backed by evidence and economics.

AI-FDE is not a chatbot. Documents are evidence. The Company Operating Model, or Business Twin, is the durable representation of the organization. Every accepted fact, relationship, rule, exception, and workflow decision is traceable to evidence.

The first product is an internal FDE Operator Cockpit. Its first proof uses a synthetic Acme Manufacturing accounts-payable workflow. It turns enterprise context into a verified operating model, a current-state workflow, a target-state workflow, a quantified business case, and engineering specifications. Coding-agent execution and production operations are later phases.

The long-term goal is to let one human FDE transform and maintain many customer environments without proportional growth in engineering headcount, while humans remain accountable for material customer and business risk.

## Current working slice

The repository implements the smallest complete, trustworthy lifecycle for the synthetic Acme Manufacturing accounts-payable workflow:

```text
Create engagement
  -> preserve text or Markdown evidence
  -> process a persistent extraction job
  -> review exact-provenance candidate claims
  -> accept or reject with a human decision
  -> query the verified Company Operating Model
  -> resolve a blocking contradiction with an audited decision
  -> construct and approve a current-state workflow
  -> review Human / Software / AI allocations
  -> approve a separate target-state workflow
  -> calculate and approve a deterministic economic case
  -> generate a versioned implementation specification
```

The Acme extractor is deliberately deterministic and fixture-backed. It proves the operating path, provenance, contradiction handling, persistent jobs, model transition, stage gates, staleness, economics, and specification dependencies without presenting a demo parser as production AI capability.

This is an internal-alpha vertical slice, not a design-partner release. The current workflow representation is intentionally minimal, the economics module provides one deterministic base formula rather than sensitivity analysis, and the implementation packet is a single versioned Markdown specification rather than the full export set.

## Run locally

Prerequisites are Docker Desktop, Python 3.13, `uv`, Node.js 20.9 or newer, and `pnpm`.

```bash
make setup
make infrastructure
make migrate
make seed
make dev
```

Open [http://localhost:3000](http://localhost:3000). The API is available at [http://localhost:8000/api/health](http://localhost:8000/api/health). `make seed` is idempotent for the local Acme fixture.

Run the quality gates with:

```bash
make test
make lint
make acceptance
pnpm build
```

The local identity, synthetic classification, supported `.md`/`.txt` formats, deterministic extractor boundary, and calculated-versus-synthetic economic labels are visible in the cockpit. Sanitized customer data, production authentication, broader parsing and model extraction, sensitivity analysis, retention/export/deletion, and coding-agent execution are not yet implemented.

See the [documentation index](docs/README.md) for the product and architecture sources of truth.
