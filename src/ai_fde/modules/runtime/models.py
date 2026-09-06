from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    FetchedValue,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ai_fde.models import Base, TimestampMixin, UUIDPrimaryKeyMixin


class RuntimeHeartbeat(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Content-free process liveness and bounded queue metadata."""

    __tablename__ = "runtime_heartbeats"
    __table_args__ = (
        UniqueConstraint("service", "instance_id", name="runtime_heartbeat_identity"),
        CheckConstraint("status IN ('RUNNING', 'STOPPED')", name="valid_status"),
        CheckConstraint("queue_depth >= 0", name="nonnegative_queue_depth"),
        CheckConstraint(
            "(operator_id IS NULL AND engagement_id IS NULL) OR "
            "(operator_id IS NOT NULL AND engagement_id IS NOT NULL)",
            name="paired_worker_identity",
        ),
        CheckConstraint(
            "deployment_validation_id IS NULL OR "
            "deployment_validation_id ~ '^sha256:[0-9a-f]{64}$'",
            name="valid_deployment_validation_digest",
        ),
        Index(
            "ix_runtime_heartbeats_deployment_seen",
            "service",
            "operator_id",
            "engagement_id",
            "release_revision",
            "deployment_id",
            "deployment_validation_id",
            "last_seen_at",
        ),
    )

    service: Mapped[str] = mapped_column(String(40), nullable=False)
    instance_id: Mapped[str] = mapped_column(String(80), nullable=False)
    release_revision: Mapped[str] = mapped_column(String(40), nullable=False)
    deployment_id: Mapped[str] = mapped_column(String(120), nullable=False)
    deployment_validation_id: Mapped[str | None] = mapped_column(String(71))
    qualification_mode: Mapped[str] = mapped_column(String(40), nullable=False)
    operator_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("operators.id", ondelete="CASCADE"),
    )
    engagement_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("engagements.id", ondelete="CASCADE"),
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    queue_depth: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    oldest_queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_job_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_failure_code: Mapped[str | None] = mapped_column(String(120))
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("clock_timestamp()"),
        server_onupdate=FetchedValue(),
    )
