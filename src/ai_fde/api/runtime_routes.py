from __future__ import annotations

from contextlib import suppress
from typing import Any

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

from ai_fde.config import get_settings
from ai_fde.modules.runtime.readiness import evaluate_readiness

router = APIRouter(tags=["runtime"])


def _runtime_identity() -> dict[str, Any]:
    settings = get_settings()
    content_digest: str | None = None
    if settings.deployment_qualification_record is not None:
        with suppress(ValueError):
            content_digest = settings.verified_deployment_qualification().content_digest
    return {
        "service": "ai-fde-api",
        "environment": settings.env,
        "release_revision": settings.release_revision,
        "deployment_id": settings.deployment_id,
        "deployment_validation_id": settings.deployment_validation_id,
        "deployment_qualification_record_version_id": (
            settings.deployment_qualification_record_version_id
        ),
        "deployment_qualification_content_digest": content_digest,
        "qualification_mode": settings.deployment_qualification_mode,
        "sanitized_data_enabled": settings.sanitized_data_enabled,
    }


@router.get("/live")
def live() -> dict[str, Any]:
    return {"status": "live", **_runtime_identity()}


@router.get("/health")
def legacy_health() -> dict[str, Any]:
    """Backward-compatible liveness alias; dependency readiness is `/ready`."""

    return live()


@router.get("/version")
def version() -> dict[str, Any]:
    return _runtime_identity()


@router.get("/ready")
def ready(request: Request) -> JSONResponse:
    settings = get_settings()
    report = evaluate_readiness(settings, request.app.state.evidence_store)
    payload: dict[str, Any] = {
        "status": "ready" if report.ready else "not_ready",
        **_runtime_identity(),
        "dependencies": report.dependencies,
    }
    return JSONResponse(
        payload,
        status_code=status.HTTP_200_OK
        if report.ready
        else status.HTTP_503_SERVICE_UNAVAILABLE,
        headers={"Cache-Control": "no-store"},
    )
