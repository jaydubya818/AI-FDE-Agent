# Isolated Database Restore Drill

## Purpose and safety boundary

Prove that a release can recover durable PostgreSQL state within the pilot RPO/RTO without touching
production. The verification script is read-only: it compares one immutable audit event and either
one published deployment package digest or one implementation-artifact hash between the source and
an isolated restored database. It creates a digest-bound qualification record and refuses to
overwrite an existing output file.

The script does not create an RDS restore, change credentials, recover S3 objects, or delete the
temporary instance. Those are separately reviewed cloud operations. It refuses:

- identical source and target database hosts;
- target identifiers outside `ai-fde-restore-*`;
- source or target URLs that are not direct AWS RDS instance endpoints bound to their exact IDs;
- anything except the explicit `ISOLATED-RESTORE-DRILL` designation;
- PostgreSQL URLs without `sslmode=verify-full`;
- any database login other than non-superuser, non-`BYPASSRLS` `ai_fde_app`, or a proof table
  without active row security;
- URL files readable by group/other users; and
- mutable/non-published package evidence, invalid artifact hashes, missing durable rows, or any
  source/target fingerprint mismatch.

Never point an application service, worker, ALB, or Mission Control integration at the restore.
Never restore over the source. A restored target must have no route from public networks and no
security-group ingress except from the short-lived verifier host.

## Owners and objectives

- Cloud owner: RDS PITR, isolated network, target teardown.
- Security/DB owner: short-lived verifier access and URL files.
- Release owner: selects immutable proof rows, observes the drill, reviews the JSON.
- Objective: latest restorable time within 15 minutes and completed verification within 4 hours of
  declaring the drill.

If PITR is older than 15 minutes, the restore exceeds 4 hours, or any integrity check differs, stop
and mark the release NO-GO.

## Preconditions

- [ ] Sanitized data is disabled for the candidate release.
- [ ] Source RDS is private, encrypted, Multi-AZ, deletion-protected, and has at least 7 days of
      automated backup retention.
- [ ] `LatestRestorableTime` is recorded in UTC and is no more than 15 minutes old.
- [ ] The restore time is after creation of the selected immutable audit event and package/artifact.
- [ ] Source and target identifiers, account, region, subnet group, KMS key, and isolated security
      group are written into the change record.
- [ ] Target identifier matches `ai-fde-restore-<date-or-ticket>` and does not already exist.
- [ ] The isolated security group has no ALB, API, worker, public, or broad VPC ingress.
- [ ] A dedicated verifier operator is a member of the selected engagement. Verification uses the
      application database role so RLS remains active, not the RDS master/migration role.
- [ ] One immutable `audit_events.id` and either one published
      `factory_deployment_package_versions.id` or `implementation_artifacts.id` are recorded. Do not
      copy their customer-derived content into the ticket.
- [ ] The selected package/artifact SHA-256 digest is captured in the immutable pre-restore change
      record so the verifier does not treat the source database as its own integrity oracle.

## Restore procedure

1. Record the source state without changing it:

   ```sh
   aws rds describe-db-instances \
     --db-instance-identifier <source-id> \
     --query 'DBInstances[0].{Status:DBInstanceStatus,LatestRestorableTime:LatestRestorableTime,Encrypted:StorageEncrypted,MultiAZ:MultiAZ,Retention:BackupRetentionPeriod,DeletionProtection:DeletionProtection}'
   ```

2. From a reviewed cloud change, create a new point-in-time target. Supply the dedicated private
   subnet group, isolated verifier-only security group, and source KMS boundary. Do not reuse the
   application task security groups.

   ```sh
   aws rds restore-db-instance-to-point-in-time \
     --source-db-instance-identifier <source-id> \
     --target-db-instance-identifier <ai-fde-restore-date-ticket> \
     --restore-time <utc-time-after-known-records> \
     --db-subnet-group-name <private-restore-subnet-group> \
     --vpc-security-group-ids <isolated-verifier-only-sg> \
     --no-publicly-accessible \
     --no-deletion-protection \
     --tags Key=Purpose,Value=isolated-restore-drill Key=DeleteAfter,Value=<utc-deadline>
   ```

3. Wait for the target to become `available`. Independently verify its endpoint, encryption,
   private network, parameter group/TLS enforcement, restored time, and tags. If the target has any
   application traffic or broad ingress, stop and remove that access before continuing.

4. On the approved verifier host, securely materialize two one-line PostgreSQL application-role
   URLs in an ephemeral secret directory. The files must be regular files with mode `0600`; both
   URLs must include `sslmode=verify-full`. Do not put a database URL in shell history, process
   arguments, tickets, or the repository. The source and target files may use the same restored
   application-role credential, but their hosts must differ.

5. Run the read-only verifier. Choose exactly one digest subject flag.

   ```sh
   PYTHONPATH=src uv run python -m scripts.verify_isolated_restore \
     --source-database-url-file <secure/source-url> \
     --target-database-url-file <secure/target-url> \
     --source-identifier <source-id> \
     --target-identifier <ai-fde-restore-date-ticket> \
     --target-designation ISOLATED-RESTORE-DRILL \
     --operator-id <verifier-operator-uuid> \
     --engagement-id <known-engagement-uuid> \
     --audit-event-id <known-immutable-audit-event-uuid> \
     --package-version-id <known-published-package-version-uuid> \
     --expected-subject-digest <independently-recorded-sha256:digest> \
     --release-revision <40-character-lowercase-sha> \
     --deployment-id <deployment-record-id> \
     --record-id <restore-record-id> \
     --region <aws-region> \
     --evidence-issuer-role-arn <evidence-issuer-role-arn> \
     --evidence-signing-key-arn <evidence-signing-key-arn> \
     --output <controlled-evidence-dir>/restore-rehearsal.json
   ```

   To verify an implementation artifact instead, replace `--package-version-id` with
   `--artifact-id`. The artifact path recomputes SHA-256 over its restored content; the package path
   checks its stored canonical digest and the full immutable-row fingerprint. Both must equal the
   independently recorded pre-restore digest and compare the exact audit-row fingerprint.

6. Confirm the output has schema `fdlc.production-qualification-evidence/v2`, evidence type
   `isolated-restore-rehearsal`, the exact release revision/deployment ID and strict passing result
   fields, a matching `content_digest`, and a valid AWS KMS signature from the configured independent
   evidence-issuer role/key. Have the independent release owner compare the source/target
   identifiers and CloudTrail restore event with the JSON.

7. Separately exercise S3 recovery into an isolated drill bucket or encrypted verifier filesystem:
   select a version created before a deliberate delete marker, retrieve that exact version without
   writing the production key, recompute SHA-256, compare it with `evidence_assets.content_hash`,
   and delete the isolated copy under the approved secure-workstation procedure. Record only IDs,
   version ID, hashes, timestamps, and pass/fail. Do not copy evidence content into the record.

8. Feed the approved JSON path to the release readiness command as
   `--restore-rehearsal-record`. A record from another revision, deployment, type, status, or age
   window fails closed.

## Post-drill cleanup

- [ ] Remove verifier ingress before any teardown step.
- [ ] Revoke/expire the verifier database access and securely delete both local URL files.
- [ ] A second operator compares the exact target identifier with the change record, then deletes
      only that restored instance. The production source remains deletion-protected.
- [ ] Confirm the target is gone, the production instance remains `available`, and no application
      configuration references the target endpoint.
- [ ] Preserve the sanitized JSON, timing, AWS request/event identifiers, and reviewer decision;
      never preserve credentials or recovered content.

## Failure handling

Do not retry by weakening a guard. For a missing record, prove that the selected restore time is
after the record was created. For digest mismatch, treat the restore as an integrity incident. For
RLS visibility failure, validate the operator membership and restored database role without using
the owner role as substitute evidence. Create a new restore and new record only after the cause is
understood; an edited prior record is invalid because its digest changes.
