# FDE Operator Onboarding Checklist

## Before access

- [ ] Confirm the operator is an internal FDE and has completed customer-data handling training.
- [ ] Add the operator's verified email to the environment-specific Auth0 allowlist.
- [ ] Agree whether the engagement is `synthetic` or `sanitized`; never upload production data
      unless the signed design-partner go/no-go record is **GO**.
- [ ] For sanitized data, record the approved retention deadline, export owner, deletion owner, and
      incident contact before evidence ingestion.
- [ ] Confirm the operator has no need for database, object-storage, or cloud-console access.

## First session

- [ ] Sign in through the approved AI-FDE URL and confirm the displayed operator identity.
- [ ] Verify keyboard focus is visible and “Skip to main content” works.
- [ ] Sign out once, confirm the cockpit becomes unauthenticated, then sign in again.
- [ ] Open only the assigned engagement; report any unexpected engagement immediately.

## First engagement

- [ ] Create the engagement with one measurable primary outcome.
- [ ] Name the one primary workflow being analyzed; do not combine unrelated processes.
- [ ] Set its retention deadline before adding sanitized evidence.
- [ ] Ingest only bounded PDF, DOCX, CSV, EML, PNG/JPEG, Markdown, or text evidence from an
      approved source.
- [ ] Confirm each evidence asset is processed and retains its exact source provenance.
- [ ] Treat extracted claims as candidates; accept, reject, or defer each claim deliberately.
- [ ] Resolve contradictions explicitly; never rewrite history to make evidence appear consistent.
- [ ] Review and approve current-state workflow, Human / Software / AI allocation, target-state
      workflow, deterministic sensitivity economics, and the complete implementation packet in
      that order.
- [ ] Verify economic inputs are labeled measured, calculated, estimated, synthetic, or simulated.
- [ ] Review the low/base/high transforms and confirm their ordering is credible for this workflow.

## Handoff and closure

- [ ] Download a current export and record its archive hash before handoff or deletion.
- [ ] Confirm the export opens and includes the manifest, structured model, readable documents, and
      original evidence expected for the engagement.
- [ ] Use permanent deletion only with the engagement owner, exact-name confirmation, and current
      export. Store the content-free deletion receipt outside the deleted engagement if required.
- [ ] Report incorrect access, missing provenance, unexplained model changes, evidence in logs, or
      a failed deletion as a release-blocking incident.

An operator is onboarded only after completing the first-session checks in the intended
environment and walking one synthetic Acme workflow with a product owner or experienced FDE.
