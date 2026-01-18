from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

from app.config import get_settings

API_KEY_HEADER = APIKeyHeader(name="x-dgs-dev-key", auto_error=False)


def verify_admin_key(api_key: str | None = Security(API_KEY_HEADER)) -> str:
  """Validate that the request provides the correct integration dev key."""
  settings = get_settings()

  if not api_key:
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing admin key header")

  if api_key != settings.dev_key:
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin key")

  return api_key
