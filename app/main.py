from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from app.ai.orchestrator import OrchestrationError
from app.api.routes import admin, auth, configuration, data_transfer, fenster, jobs, lessons, media, notifications, onboarding, purgatory, push, research, resources, sections, tasks, tutor, users, worker, writing
from app.config import get_settings
from app.core.exceptions import global_exception_handler, http_exception_handler, orchestration_exception_handler, request_validation_exception_handler
from app.core.json import DecimalJSONResponse
from app.core.lifespan import lifespan
from app.core.middleware import RequestLoggingMiddleware, SecurityHeadersMiddleware

settings = get_settings()

app = FastAPI(default_response_class=DecimalJSONResponse, lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

app.add_middleware(CORSMiddleware, allow_origins=settings.allowed_origins, allow_credentials=True, allow_methods=["GET", "POST", "PATCH", "OPTIONS"], allow_headers=["content-type", "authorization"], expose_headers=["content-length"])


# Add exception handlers
app.add_exception_handler(Exception, global_exception_handler)
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(OrchestrationError, orchestration_exception_handler)
app.add_exception_handler(RequestValidationError, request_validation_exception_handler)

# Add middleware
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(SecurityHeadersMiddleware)


@app.get("/health", include_in_schema=False)
async def health_check() -> dict[str, str]:
  """Return a simple health status."""
  return {"status": "ok", "version": "0.1.0"}


app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(users.router, prefix="/api/user", tags=["users"])
app.include_router(onboarding.router, prefix="/api", tags=["onboarding"])
app.include_router(purgatory.router, prefix="/api", tags=["purgatory"])
app.include_router(admin.router, prefix="/admin", tags=["admin"])
app.include_router(configuration.router, prefix="/admin", tags=["admin"])
app.include_router(data_transfer.router, prefix="/admin", tags=["admin"])
app.include_router(sections.router, prefix="/v1/lessons", tags=["sections"])
app.include_router(lessons.router, prefix="/v1/lessons", tags=["lessons"])
app.include_router(jobs.router, prefix="/v1/jobs", tags=["jobs"])
app.include_router(research.router, prefix="/v1/research", tags=["research"])
app.include_router(writing.router, prefix="/v1/writing", tags=["writing"])
app.include_router(resources.router, prefix="/resource", tags=["resources"])
app.include_router(notifications.router, prefix="/v1/notifications", tags=["notifications"])
app.include_router(push.router, prefix="/v1/push", tags=["push"])
app.include_router(media.router, prefix="/media", tags=["media"])
app.include_router(tasks.router, prefix="/internal", tags=["tasks"])
app.include_router(worker.router, prefix="/worker", tags=["worker"])
app.include_router(fenster.router, prefix="/api/v1/fenster", tags=["fenster"])
app.include_router(tutor.router, prefix="/v1/tutor", tags=["tutor"])
