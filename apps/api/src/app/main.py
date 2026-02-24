from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings

from app.api.health import router as health_router
from app.api.auth import router as auth_router
from app.api.workspaces import router as workspaces_router
from app.api.agents import router as agents_router
from app.api.runs import router as runs_router
from app.api.artifacts import router as artifacts_router
from app.api.evidence import router as evidence_router
from app.api.export import router as export_router
from app.api.retrieval import router as retrieval_router

app = FastAPI(title="PM Agent OS API", version="0.0.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(workspaces_router)
app.include_router(agents_router)
app.include_router(runs_router)
app.include_router(artifacts_router)
app.include_router(evidence_router)
app.include_router(export_router)
app.include_router(retrieval_router)