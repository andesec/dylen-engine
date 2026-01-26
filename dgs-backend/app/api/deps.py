from fastapi import Depends, Header, HTTPException, Security, status
from fastapi.security import APIKeyHeader

from app.config import Settings, get_settings

API_KEY_HEADER = APIKeyHeader(name="x-dgs-dev-key", auto_error=False)


def verify_admin_key(api_key: str | None = Security(API_KEY_HEADER)) -> str:
  """Validate that the request provides the correct integration dev key."""
  settings = get_settings()

  if not api_key:
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing admin key header")

  if api_key != settings.dev_key:
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin key")

  return api_key


def require_dev_key(  # noqa: B008
  x_dgs_dev_key: str = Header(..., alias="X-DGS-Dev-Key"),
  settings: Settings = Depends(get_settings),  # noqa: B008
) -> None:
  """
  Enforce presence of the restricted dev key.

  NOTE: The 'X-DGS-Dev-Key' header is intentionally excluded from CORS allowed headers
  in main.py. This ensures that browsers cannot send this header in cross-origin requests,
  restricting its use to secure server-to-server or non-browser clients (e.g. curl, internal tools).
  """
  if x_dgs_dev_key != settings.dev_key:
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid dev key.")
