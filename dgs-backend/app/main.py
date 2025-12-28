from typing import Any, Dict, List, Optional

from fastapi import FastAPI
from pydantic import BaseModel

from app.schema.validate_lesson import validate_lesson

app = FastAPI()


class ValidationResponse(BaseModel):
    """Response model for lesson validation results."""

    ok: bool
    errors: List[str]


@app.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/lessons/validate", response_model=ValidationResponse)
async def validate_endpoint(payload: Dict[str, Any]) -> ValidationResponse:
    """Validate a lesson payload against schema + widget registry."""

    ok, errors, _model = validate_lesson(payload)
    return ValidationResponse(ok=ok, errors=errors)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
