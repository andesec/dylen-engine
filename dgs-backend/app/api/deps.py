"""Dependencies for API routes."""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException, status
from app.config import Settings, get_settings


def _require_dev_key(  # noqa: B008
    x_dgs_dev_key: str = Header(..., alias="X-DGS-Dev-Key"),
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> None:
  if x_dgs_dev_key != settings.dev_key:
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid dev key.")
