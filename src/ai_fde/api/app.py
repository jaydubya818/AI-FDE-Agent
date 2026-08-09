from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ai_fde.adapters.storage import S3EvidenceStore
from ai_fde.api.routes import router
from ai_fde.config import get_settings
from ai_fde.db import ensure_local_operator


def create_app() -> FastAPI:
    settings = get_settings()
    store = S3EvidenceStore(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if settings.auth_mode == "development":
            ensure_local_operator(settings)
        store.ensure_bucket()
        app.state.evidence_store = store
        yield

    app = FastAPI(
        title="AI-FDE API",
        version="0.1.0",
        description="Evidence-backed operating model for Forward Deployed Engineers.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )
    app.include_router(router, prefix="/api")
    return app
