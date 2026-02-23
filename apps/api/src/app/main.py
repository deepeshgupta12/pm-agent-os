from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.api.health import router as health_router

app = FastAPI(title="PM Agent OS API", version="0.0.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list(),
    allow_credentials=True,  # required for HttpOnly cookie auth
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)