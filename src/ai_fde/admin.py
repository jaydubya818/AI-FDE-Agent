from __future__ import annotations

import argparse
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from ai_fde.config import get_settings
from ai_fde.modules.identity.admin import (
    deactivate_worker_identity,
    grant_worker_engagement,
    provision_worker_identity,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Explicit AI-FDE deployment administration")
    commands = parser.add_subparsers(dest="command", required=True)

    provision = commands.add_parser("provision-worker")
    provision.add_argument("--engagement-id", type=UUID)
    provision.add_argument("--display-name", default="AI-FDE Production Worker")

    grant = commands.add_parser("grant-worker")
    grant.add_argument("--engagement-id", required=True, type=UUID)

    commands.add_parser("deactivate-worker")
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    settings = get_settings()
    if settings.env == "development":
        raise SystemExit("Worker administration is not available in development.")
    if settings.worker_operator_id is None:
        raise SystemExit("AI_FDE_WORKER_OPERATOR_ID is required.")

    engine = create_engine(
        settings.migration_database_url,
        pool_pre_ping=True,
        connect_args={"connect_timeout": settings.database_connect_timeout_seconds},
    )
    with Session(engine) as session, session.begin():
        if args.command in {"provision-worker", "grant-worker"}:
            worker = provision_worker_identity(
                session,
                operator_id=settings.worker_operator_id,
                environment=settings.env,
                display_name=str(getattr(args, "display_name", "AI-FDE Production Worker")),
            )
            engagement_id = getattr(args, "engagement_id", None)
            if engagement_id is None:
                print(f"Provisioned worker {worker.id} without engagement membership.")
            else:
                membership = grant_worker_engagement(
                    session,
                    worker=worker,
                    engagement_id=engagement_id,
                )
                print(f"Provisioned worker {worker.id} with membership {membership.id}.")
        else:
            worker = deactivate_worker_identity(session, operator_id=settings.worker_operator_id)
            print(f"Deactivated worker {worker.id}.")


if __name__ == "__main__":
    main()
