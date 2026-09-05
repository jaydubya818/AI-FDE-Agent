# Production Qualification Evidence Records

The readiness gate accepts only authenticated `fdlc.production-qualification-evidence/v2`
records. A SHA-256 digest detects drift but is not authority. Each v2 record is signed by the
independent evidence-issuer role with the Terraform-owned asymmetric AWS KMS key, then verified
online by the separate qualifier role. The deployer has neither `kms:Sign` nor `kms:Verify`.

## Trust boundary

Terraform outputs `evidence_issuer_role_arn` and `evidence_signing_key_arn`. Only the evidence
issuer may call `kms:Sign`; only the qualifier needs `kms:Verify`. The signed claims include the
exact issuer role, signing key, producer command, Git revision, deployment ID, completion time,
evidence type, and procedure-specific results. KMS uses `RSASSA_PSS_SHA_256` over the canonical
SHA-256 digest. There is no private key file and no application-defined signing algorithm.

The Auth0, deletion, rotation, and prior-worker revocation records are explicitly
`trusted-operator-kms-attestation`: the evidence-issuer operator is the attesting trust boundary,
not an autonomous verifier. That operator must run the named procedure and inspect its controlled
evidence before sealing the exact typed observations. The restore record is
`machine-verified-kms-attestation` because its command derives the claims directly from the two live
database snapshots. A caller cannot provide `passed`, `status`, `checks`, or a free-form result
list. Wrong issuer/key, an impossible observation, missing or additional fields, a different
release, stale evidence, digest drift, or signature drift fails closed. Compromise or misuse of the
evidence-issuer principal remains a trust-anchor compromise and is visible in KMS/CloudTrail.

## Exact envelope

```json
{
  "schema_version": "fdlc.production-qualification-evidence/v2",
  "record_id": "restore-2026-09-04-a",
  "evidence_type": "isolated-restore-rehearsal",
  "release_revision": "replace-with-exact-40-character-lowercase-git-sha",
  "deployment_id": "deploy-2026-09-04-a",
  "completed_at": "2026-09-04T20:00:00+00:00",
  "attestation_mode": "machine-verified-kms-attestation",
  "attestation_outcome": "checks-passed",
  "issuer": {
    "role_arn": "arn:aws:iam::000000000000:role/ai-fde-design-partner-evidence-issuer",
    "signing_key_arn": "arn:aws:kms:us-east-1:000000000000:key/replace-with-key-id",
    "signing_algorithm": "RSASSA_PSS_SHA_256",
    "producer": "scripts.verify_isolated_restore"
  },
  "results": {},
  "content_digest": "sha256:<64-lowercase-hex-characters>",
  "signature": "<bounded-base64-KMS-signature>"
}
```

`canonical_record_digest` removes only `content_digest` and `signature`, then serializes the other
claims as sorted, compact UTF-8 JSON. The detached KMS signature covers that digest. Production
qualification rejects the synthetic/development schema entirely.

## Mandatory result schemas

- Auth0 (`scripts.seal_auth0_observations`): credential-free HTTPS tenant/callback URLs; five
  distinct canonical request IDs; observed authorization method `S256`, response type `code`, and
  exact HTTP outcomes 303 (allowlisted callback), 403 (unallowlisted callback), 204 (logout), and
  401 (revoked-session check).
- Isolated restore (`scripts.verify_isolated_restore`): bounded distinct source/target identifiers,
  `database_role: ai_fde_app`, canonical audit/digest subject UUIDs, three exact SHA-256
  fingerprints, supported subject type, and literal-true isolation/durable-record/digest matches.
- Deletion (`scripts.seal_deletion_boundary_observations`): canonical deleted/control engagement and
  receipt UUIDs; counts of deleted object versions and delete markers; zero application rows,
  current objects, remaining object versions, and remaining delete markers; equal before/after
  control fingerprints; deletion time; and exact RDS/S3 retention days. The sealer derives
  `backup_expiry_at` from the RDS backup-retention observation because successful S3 deletion is a
  physical prefix purge.
- Rotation (`scripts.seal_runtime_secret_rotation_observations`): distinct exact runtime secret
  ARNs and previous/current version IDs; old-login denial SQLSTATE; observed `ai_fde_worker`
  `NOLOGIN` state; exact retired deployment login; and zero remaining prior-worker sessions. The
  sealer derives the current release-scoped login and completion time.
- Prior worker (`scripts.seal_prior_worker_revocation_observations`): a sorted bounded list of exact
  superseded role ARNs and prior release/deployment identities; retained-quarantined or
  deleted-after-TTL state; exact revocation-policy digest; literal proof that new assumptions are
  disabled and grants stripped; quarantine/cutoff/captured-session/live-probe timestamps; maximum
  STS session duration, captured session issue/expiry, propagation wait, and the exactly derived
  conservative session-expiry boundary; exact
  RDS, S3 prefix, KMS key, and Bedrock targets; and six literal `denied` captured-session outcomes.
  An empty list is mandatory on the first deployment. A deleted role is accepted only after the
  maximum session TTL plus propagation and completed denial probes; `GetRole` absence alone is not
  revocation proof. A probe must occur after propagation but strictly before the captured
  credential's actual expiry, which cannot exceed the role's maximum session duration.

Each schema is exact. Do not add notes, screenshots, tokens, cookies, prompts, database URLs, secret
values, customer evidence, or arbitrary `passed` fields. Store human-readable material separately
in the controlled evidence system.

## Produce and consume

The sealer derives and signs `attestation_mode` plus `attestation_outcome`; neither is accepted from
the observation file. The isolated restore command signs its machine-derived result directly when passed
`--evidence-issuer-role-arn` and `--evidence-signing-key-arn`. The other bounded sealers consume one
sanitized JSON object matching the exact observation schema above. They derive the passing summary
only after validation and write a new file with exclusive-create semantics:

```sh
PYTHONPATH=src uv run python -m scripts.seal_auth0_observations \
  --region us-east-1 \
  --record-id auth0-2026-09-04-a \
  --release-revision <sha> \
  --deployment-id <deployment-id> \
  --completed-at <rfc3339-time> \
  --issuer-role-arn <evidence-issuer-role-arn> \
  --signing-key-arn <evidence-signing-key-arn> \
  --observations <controlled-path>/auth0-observations.json \
  --output <controlled-path>/auth0.json
```

Use the equivalent deletion, rotation, or prior-worker sealer for those procedures. Run these
commands under the evidence-issuer role, never the deployer or qualifier. Do not describe these
four records as machine-verified; the named human/operator and KMS audit trail are their
provenance. Before sealing prior-worker observations, use the quarantine tool to re-read the exact
cutoff deny/trust/grant state and perform every probe with credentials captured before rotation.

Pass all five signed files plus the exact issuer/key ARNs to candidate readiness. Each summary has
twelve exact fields and retains the complete `signed_record` envelope, including typed
observations and signature. The runtime pins the exported RSA-3072 public key/fingerprint and
verifies each digest and signature offline; possession of qualifier `PutSecretValue` alone cannot
synthesize evidence. Candidate publishing rejects a complete qualification payload above the
Secrets Manager 64 KiB limit. Post-activation verification reads that exact immutable version and
independently proves the final live configuration.
