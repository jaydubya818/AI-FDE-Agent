from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ai_fde.adapters.storage import EvidenceStore
from ai_fde.config import Settings, get_settings
from ai_fde.db import operator_session
from ai_fde.models import Operator


def get_session(settings: Annotated[Settings, Depends(get_settings)]) -> Iterator[Session]:
    with operator_session(settings.operator_id) as session:
        yield session


def get_operator(
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Operator:
    operator = session.get(Operator, settings.operator_id)
    if operator is None:
        raise HTTPException(status_code=500, detail="The configured operator is not initialized.")
    return operator


def get_evidence_store(request: Request) -> EvidenceStore:
    store: EvidenceStore = request.app.state.evidence_store
    return store


SessionDependency = Annotated[Session, Depends(get_session)]
OperatorDependency = Annotated[Operator, Depends(get_operator)]
EvidenceStoreDependency = Annotated[EvidenceStore, Depends(get_evidence_store)]
