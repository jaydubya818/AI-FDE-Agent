# Clean-Environment Rehearsal

The rehearsal uses a separate Docker Compose project, PostgreSQL volume, MinIO volume, database,
bucket, and host ports. It never reuses the normal development database. The temporary resources
are removed at the end, including after a failure.

Run:

```bash
make rehearse
```

The default rehearsal ports are PostgreSQL `55433`, MinIO API `59010`, and MinIO console `59011`.
Override `AI_FDE_REHEARSAL_POSTGRES_PORT`, `AI_FDE_REHEARSAL_MINIO_API_PORT`, or
`AI_FDE_REHEARSAL_MINIO_CONSOLE_PORT` if one is occupied.

The gate passes only when a fresh dependency install, migration, schema-drift check, synthetic
seed, full Python suite, Ruff, mypy, ESLint, TypeScript check, and production web build all pass.
Afterward, follow the operator onboarding checklist against a running stack to visually rehearse
the golden workflow and all approval gates.

## Rehearsal record

| Field | Value |
| --- | --- |
| Date | 2026-08-11 |
| Commit | Pending final hardening commit |
| Host | Local macOS / Docker Desktop |
| Result | Passed |
| Exceptions | None recorded |

The recorded run created new PostgreSQL and MinIO volumes, applied all four migrations, seeded a
new Acme engagement, passed 27 Python tests, detected no schema drift, passed all static checks,
and produced the optimized Next.js build. The rehearsal project and its volumes were removed by
the scripted cleanup.
