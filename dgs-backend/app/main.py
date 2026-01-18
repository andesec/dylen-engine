from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.ai.orchestrator import OrchestrationError
from app.api.routes import health, jobs, lessons, writing
from app.config import get_settings
from app.core.exceptions import global_exception_handler, orchestration_exception_handler
from app.core.json import DecimalJSONResponse
from app.core.lifespan import lifespan
from app.core.middleware import log_requests

settings = get_settings()

app = FastAPI(default_response_class=DecimalJSONResponse, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["content-type", "authorization", "x-dgs-dev-key"],
    expose_headers=["content-length"],
)

app.middleware("http")(log_requests)

app.add_exception_handler(Exception, global_exception_handler)
app.add_exception_handler(OrchestrationError, orchestration_exception_handler)

app.include_router(health.router)
app.include_router(lessons.router)
app.include_router(jobs.router)
app.include_router(writing.router)
