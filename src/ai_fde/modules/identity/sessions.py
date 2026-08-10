from __future__ import annotations

import hashlib
import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from ai_fde.db import SessionFactory
from ai_fde.models import OIDCLoginAttempt, Operator, OperatorSession
from ai_fde.modules.identity.oidc import OIDCIdentity


class InvalidLoginAttemptError(ValueError):
    """The OIDC callback state is missing, expired, consumed, or unknown."""


class OperatorEnrollmentDeniedError(PermissionError):
    """The verified identity is not allowed to become an AI-FDE operator."""


@dataclass(frozen=True)
class LoginAttempt:
    state: str
    nonce: str
    code_verifier: str
    redirect_uri: str
    return_to: str


def create_login_attempt(
    session: Session,
    *,
    redirect_uri: str,
    return_to: str,
    ttl_seconds: int,
    now: datetime | None = None,
) -> LoginAttempt:
    timestamp = now or datetime.now(UTC)
    session.execute(delete(OIDCLoginAttempt).where(OIDCLoginAttempt.expires_at <= timestamp))
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    code_verifier = secrets.token_urlsafe(64)
    session.add(
        OIDCLoginAttempt(
            state_digest=digest_secret(state),
            nonce=nonce,
            code_verifier=code_verifier,
            redirect_uri=redirect_uri,
            return_to=return_to,
            expires_at=timestamp + timedelta(seconds=ttl_seconds),
        )
    )
    return LoginAttempt(
        state=state,
        nonce=nonce,
        code_verifier=code_verifier,
        redirect_uri=redirect_uri,
        return_to=return_to,
    )


def consume_login_attempt(
    session: Session,
    state: str,
    *,
    now: datetime | None = None,
) -> LoginAttempt:
    timestamp = now or datetime.now(UTC)
    attempt = session.scalar(
        select(OIDCLoginAttempt)
        .where(OIDCLoginAttempt.state_digest == digest_secret(state))
        .with_for_update()
    )
    if attempt is None or attempt.expires_at <= timestamp:
        raise InvalidLoginAttemptError("The login attempt is invalid or expired.")
    consumed = LoginAttempt(
        state=state,
        nonce=attempt.nonce,
        code_verifier=attempt.code_verifier,
        redirect_uri=attempt.redirect_uri,
        return_to=attempt.return_to,
    )
    session.delete(attempt)
    return consumed


def enroll_operator(
    session: Session,
    identity: OIDCIdentity,
    *,
    allowed_emails: list[str],
    now: datetime | None = None,
) -> Operator:
    normalized_email = identity.email.strip().casefold()
    allowed = {email.strip().casefold() for email in allowed_emails}
    if not identity.email_verified or normalized_email not in allowed:
        raise OperatorEnrollmentDeniedError("This identity is not an approved AI-FDE operator.")
    external_subject = f"{identity.issuer}|{identity.subject}"
    if len(external_subject) > 255:
        raise OperatorEnrollmentDeniedError("The provider identity key is too long.")
    display_name = identity.display_name.strip()[:255] or normalized_email[:255]
    timestamp = now or datetime.now(UTC)
    operator_id = session.scalar(
        insert(Operator)
        .values(
            external_subject=external_subject,
            display_name=display_name,
            is_active=True,
            created_at=timestamp,
            updated_at=timestamp,
        )
        .on_conflict_do_update(
            index_elements=[Operator.external_subject],
            set_={"display_name": display_name, "updated_at": timestamp},
            where=Operator.is_active.is_(True),
        )
        .returning(Operator.id)
    )
    if operator_id is None:
        existing = session.scalar(
            select(Operator).where(Operator.external_subject == external_subject)
        )
        if existing is not None and not existing.is_active:
            raise OperatorEnrollmentDeniedError("This AI-FDE operator is inactive.")
        raise RuntimeError("The operator enrollment did not return an identity.")
    operator = session.get_one(Operator, operator_id)
    if not operator.is_active:
        raise OperatorEnrollmentDeniedError("This AI-FDE operator is inactive.")
    return operator


def create_operator_session(
    session: Session,
    *,
    operator: Operator,
    ttl_seconds: int,
    now: datetime | None = None,
) -> str:
    timestamp = now or datetime.now(UTC)
    session.execute(
        delete(OperatorSession).where(
            (OperatorSession.expires_at <= timestamp) | (OperatorSession.revoked_at.is_not(None))
        )
    )
    token = secrets.token_urlsafe(48)
    session.add(
        OperatorSession(
            token_digest=digest_secret(token),
            operator_id=operator.id,
            authenticated_at=timestamp,
            expires_at=timestamp + timedelta(seconds=ttl_seconds),
        )
    )
    return token


def resolve_operator_session(
    session: Session,
    token: str,
    *,
    now: datetime | None = None,
) -> OperatorSession | None:
    if not 32 <= len(token) <= 256:
        return None
    timestamp = now or datetime.now(UTC)
    return session.scalar(
        select(OperatorSession)
        .join(Operator, Operator.id == OperatorSession.operator_id)
        .where(
            OperatorSession.token_digest == digest_secret(token),
            OperatorSession.expires_at > timestamp,
            OperatorSession.revoked_at.is_(None),
            Operator.is_active.is_(True),
        )
    )


def revoke_operator_session(
    session: Session,
    token: str,
    *,
    now: datetime | None = None,
) -> bool:
    operator_session = resolve_operator_session(session, token, now=now)
    if operator_session is None:
        return False
    operator_session.revoked_at = now or datetime.now(UTC)
    return True


def digest_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@contextmanager
def identity_session() -> Iterator[Session]:
    session = SessionFactory()
    try:
        with session.begin():
            yield session
    finally:
        session.close()
