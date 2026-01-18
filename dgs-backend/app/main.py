from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.ai.orchestrator import OrchestrationError
from app.api.routes import admin, jobs, lessons, writing
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


# Add exception handlers
app.add_exception_handler(Exception, global_exception_handler)
app.add_exception_handler(OrchestrationError, orchestration_exception_handler)

# Add middleware
app.middleware("http")(log_requests)


@app.get("/health", include_in_schema=False)
async def health_check() -> dict[str, str]:
  """Return a simple health status."""
  return {"status": "ok", "version": "0.1.0"}


app.include_router(admin.router, prefix="/admin", tags=["admin"])
app.include_router(lessons.router, prefix="/v1/lessons", tags=["lessons"])
app.include_router(jobs.router, prefix="/v1/jobs", tags=["jobs"])
app.include_router(writing.router, prefix="/v1/writing", tags=["writing"])
