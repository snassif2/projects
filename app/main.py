"""
app/main.py
FastAPI application factory.
Mangum wraps the app for AWS Lambda + API Gateway.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mangum import Mangum

from app.config import get_settings
from app.routers import analysis

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="VozLab Voice Analysis API",
        description=(
            "Voice screening / triage API. "
            "Accepts audio uploads, extracts acoustic features, "
            "and returns a health score with clinical indicators."
        ),
        version="2.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # ── CORS ──────────────────────────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        # credentials=True requires explicit origins — keep False when origins=["*"]
        allow_credentials=settings.cors_origins != ["*"],
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "Authorization"],
    )

    # ── Routers ───────────────────────────────────────────────────────────────
    app.include_router(analysis.router, tags=["analysis"])

    # ── Health / root ─────────────────────────────────────────────────────────
    @app.get("/health", tags=["ops"])
    def health() -> dict:
        return {"status": "healthy", "service": "VozLab Voice Analysis API"}

    @app.get("/", tags=["ops"])
    def root() -> dict:
        return {"message": "VozLab Voice Analysis API v2"}

    logger.info(
        "App created: cors_origins=%s max_duration=%ds",
        settings.cors_origins,
        settings.max_duration_seconds,
    )
    return app


app = create_app()

# Mangum adapter — entry point for AWS Lambda + API Gateway
# This is the value you set as the Lambda handler: "app.main.handler"
handler = Mangum(app, lifespan="off")
