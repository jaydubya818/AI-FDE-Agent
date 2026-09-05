from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import datetime
from typing import Protocol, cast
from uuid import UUID

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from ai_fde.config import get_settings
from ai_fde.models import Operator
from ai_fde.modules.design_partner.service import (
    DesignPartnerQualificationError,
    DesignPartnerQualificationNotFoundError,
    provision_design_partner_qualification,
    transition_design_partner_qualification,
)
from ai_fde.modules.factory_engineer.retrieval import (
    provision_retrieval_service_identity,
    rotate_retrieval_grant,
)
from ai_fde.modules.identity.admin import (
    bind_worker_database_role,
    deactivate_worker_identity,
    grant_worker_engagement,
    provision_worker_identity,
)
from ai_fde.modules.identity.database import worker_database_user_for_release


class SecretsManagerClient(Protocol):
    def put_secret_value(
        self,
        *,
        SecretId: str,
        ClientRequestToken: str,
        SecretString: str,
        VersionStages: list[str],
    ) -> object: ...


def _aware_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Use an ISO-8601 timestamp with a timezone.") from exc
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("Use an ISO-8601 timestamp with a timezone.")
    return parsed


def _secret_arn(value: str) -> str:
    parts = value.split(":", 6)
    if (
        len(parts) != 7
        or parts[0] != "arn"
        or not parts[1].startswith("aws")
        or parts[2] != "secretsmanager"
        or not parts[3]
        or len(parts[4]) != 12
        or not parts[4].isdigit()
        or parts[5] != "secret"
        or not parts[6]
    ):
        raise argparse.ArgumentTypeError("Use an explicit AWS Secrets Manager secret ARN.")
    return value


def _deliver_retrieval_token(
    *,
    secret_arn: str,
    token: str,
    grant_id: UUID,
    client: SecretsManagerClient | None = None,
) -> None:
    region = secret_arn.split(":", 6)[3]
    resolved_client = client or cast(
        SecretsManagerClient,
        boto3.client("secretsmanager", region_name=region),
    )
    resolved_client.put_secret_value(
        SecretId=secret_arn,
        ClientRequestToken=grant_id.hex,
        SecretString=token,
        VersionStages=["AWSCURRENT"],
    )
    print(f"Stored replacement retrieval grant {grant_id} in AWS Secrets Manager.")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Explicit AI-FDE deployment administration")
    commands = parser.add_subparsers(dest="command", required=True)

    provision = commands.add_parser("provision-worker")
    provision.add_argument("--engagement-id", type=UUID)
    provision.add_argument("--display-name", default="AI-FDE Production Worker")

    grant = commands.add_parser("grant-worker")
    grant.add_argument("--engagement-id", required=True, type=UUID)

    commands.add_parser("deactivate-worker")

    partner = commands.add_parser("provision-design-partner")
    partner.add_argument("--engagement-id", required=True, type=UUID)
    partner.add_argument("--owner-operator-id", required=True, type=UUID)
    partner.add_argument("--partner-key", required=True)
    partner.add_argument("--organization", required=True)
    partner.add_argument("--data-source-key", required=True, action="append")
    partner.add_argument("--repository-ref", required=True, action="append")
    partner.add_argument("--workflow-class", required=True, action="append")
    partner.add_argument(
        "--data-classification",
        required=True,
        choices=["PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"],
    )
    partner.add_argument("--retention-days", required=True, type=int)
    partner.add_argument("--authorization-basis-ref", required=True)

    transition = commands.add_parser("transition-design-partner")
    transition.add_argument("--engagement-id", required=True, type=UUID)
    transition.add_argument("--owner-operator-id", required=True, type=UUID)
    transition.add_argument(
        "--status",
        choices=["ACTIVE", "SUSPENDED", "REVOKED"],
    )
    transition.add_argument(
        "--qualification-state",
        choices=["CONFIGURED", "IN_PROGRESS", "BLOCKED", "QUALIFIED"],
    )
    transition.add_argument("--authorization-basis-ref", required=True)

    retrieval = commands.add_parser(
        "rotate-package-retrieval-grant",
        help="Rotate one retrieval token directly into AWS Secrets Manager.",
    )
    retrieval.add_argument("--engagement-id", required=True, type=UUID)
    retrieval.add_argument("--owner-operator-id", required=True, type=UUID)
    retrieval.add_argument("--requester-identity", required=True)
    retrieval.add_argument("--requester-system", required=True)
    retrieval.add_argument("--expires-at", required=True, type=_aware_datetime)
    retrieval.add_argument("--target-secret-arn", required=True, type=_secret_arn)
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    settings = get_settings()
    if settings.env == "development":
        raise SystemExit("Deployment administration is not available in development.")

    engine = create_engine(
        settings.migration_database_url,
        pool_pre_ping=True,
        connect_args={"connect_timeout": settings.database_connect_timeout_seconds},
    )
    retrieval_token: str | None = None
    retrieval_grant_id: UUID | None = None
    retrieval_secret_arn: str | None = None
    with Session(engine) as session, session.begin():
        if args.command == "provision-design-partner":
            try:
                qualification = provision_design_partner_qualification(
                    session,
                    engagement_id=args.engagement_id,
                    partner_key=args.partner_key,
                    organization=args.organization,
                    authorized_data_source_keys=args.data_source_key,
                    authorized_repository_refs=args.repository_ref,
                    allowed_workflow_classes=args.workflow_class,
                    data_classification=args.data_classification,
                    retention_days=args.retention_days,
                    authorization_basis_ref=args.authorization_basis_ref,
                    configured_by_id=args.owner_operator_id,
                )
            except DesignPartnerQualificationError as exc:
                raise SystemExit(str(exc)) from exc
            print(
                f"Configured design partner {qualification.partner_key} "
                f"for engagement {qualification.engagement_id}."
            )
        elif args.command == "transition-design-partner":
            try:
                qualification = transition_design_partner_qualification(
                    session,
                    engagement_id=args.engagement_id,
                    status=args.status,
                    qualification_state=args.qualification_state,
                    authorization_basis_ref=args.authorization_basis_ref,
                    actor_id=args.owner_operator_id,
                )
            except (
                DesignPartnerQualificationError,
                DesignPartnerQualificationNotFoundError,
            ) as exc:
                raise SystemExit(str(exc)) from exc
            print(
                f"Design partner {qualification.partner_key} is "
                f"{qualification.status}/{qualification.qualification_state}."
            )
        elif args.command == "rotate-package-retrieval-grant":
            owner = session.get(Operator, args.owner_operator_id)
            if owner is None:
                raise SystemExit("The owner operator does not exist.")
            try:
                service_operator = provision_retrieval_service_identity(
                    session,
                    engagement_id=args.engagement_id,
                    created_by=owner,
                )
                issued = rotate_retrieval_grant(
                    session,
                    engagement_id=args.engagement_id,
                    service_operator=service_operator,
                    created_by=owner,
                    requester_identity=args.requester_identity,
                    requester_system=args.requester_system,
                    expires_at=args.expires_at,
                )
            except ValueError as exc:
                raise SystemExit(str(exc)) from exc
            retrieval_token = issued.token
            retrieval_grant_id = issued.grant.id
            retrieval_secret_arn = args.target_secret_arn
        else:
            worker_operator_id = settings.worker_operator_id
            if worker_operator_id is None:
                raise SystemExit("AI_FDE_WORKER_OPERATOR_ID is required.")
            if args.command in {"provision-worker", "grant-worker"}:
                worker = provision_worker_identity(
                    session,
                    operator_id=worker_operator_id,
                    environment=settings.env,
                    display_name=str(
                        getattr(args, "display_name", "AI-FDE Production Worker")
                    ),
                )
                engagement_id = getattr(args, "engagement_id", None)
                if engagement_id is None:
                    bind_worker_database_role(
                        session,
                        worker=worker,
                        database_role=worker_database_user_for_release(
                            settings.deployment_id, settings.release_revision
                        ),
                        release_revision=settings.release_revision,
                        deployment_id=settings.deployment_id,
                        deployment_validation_id=settings.deployment_validation_id,
                    )
                    print(f"Provisioned worker {worker.id} without engagement membership.")
                else:
                    if (
                        settings.env == "production"
                        and settings.worker_engagement_id != engagement_id
                    ):
                        raise SystemExit(
                            "The engagement must match AI_FDE_WORKER_ENGAGEMENT_ID."
                        )
                    membership = grant_worker_engagement(
                        session,
                        worker=worker,
                        engagement_id=engagement_id,
                    )
                    bind_worker_database_role(
                        session,
                        worker=worker,
                        database_role=worker_database_user_for_release(
                            settings.deployment_id, settings.release_revision
                        ),
                        engagement_id=engagement_id,
                        release_revision=settings.release_revision,
                        deployment_id=settings.deployment_id,
                        deployment_validation_id=settings.deployment_validation_id,
                    )
                    print(f"Provisioned worker {worker.id} with membership {membership.id}.")
            else:
                worker = deactivate_worker_identity(
                    session,
                    operator_id=worker_operator_id,
                )
                print(f"Deactivated worker {worker.id}.")
    if (
        retrieval_token is not None
        and retrieval_grant_id is not None
        and retrieval_secret_arn is not None
    ):
        try:
            _deliver_retrieval_token(
                secret_arn=retrieval_secret_arn,
                token=retrieval_token,
                grant_id=retrieval_grant_id,
            )
        except (BotoCoreError, ClientError) as exc:
            raise SystemExit(
                "Secret-manager delivery failed after grant rotation. Retrieval is "
                "fail-closed; rerun the command to rotate and deliver a replacement."
            ) from exc


if __name__ == "__main__":
    main()
