import logging
from typing import Optional

from fastapi import Depends, Header, HTTPException, status, Request
from app.config import Settings, get_settings
from app.routers import auth
from app.storage.models import User

logger = logging.getLogger(__name__)

async def get_current_user_or_dev_key(
    request: Request,
    x_dgs_dev_key: Optional[str] = Header(None, alias="X-DGS-Dev-Key"),
    settings: Settings = Depends(get_settings),
) -> Optional[User]:
    """
    Dependency that allows access if:
    1. A valid X-DGS-Dev-Key is provided (returns None user).
    2. A valid Session Cookie is provided (returns User object).

    If neither is valid, raises 401.
    """

    # 1. Check Dev Key
    if x_dgs_dev_key and x_dgs_dev_key == settings.dev_key:
        return None

    # 2. Check Session Cookie via auth.get_current_user
    # We call it manually or use it as a sub-dependency if possible.
    # Since we are inside a dependency, we can't easily conditionally call another dependency
    # that raises HTTPException without catching it.

    # auth.get_current_user raises 401 if missing/invalid.
    # We want to catch that if Dev Key was missing.

    try:
        # We need to manually invoke the logic of get_current_user because calling it directly
        # as a function works, but we need to pass the parameters it expects.
        # It expects `request` and `dgs_session` (cookie).

        # Extract cookie manually
        dgs_session = request.cookies.get(auth.SESSION_COOKIE_NAME)
        if dgs_session:
            user = await auth.get_current_user(request, dgs_session)
            return user
    except HTTPException:
        # If token invalid, and no dev key, we fail.
        pass
    except Exception as e:
        logger.error(f"Auth check failed: {e}")

    # If we reached here, neither Dev Key nor User Session is valid.
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated. Provide valid Dev Key or Session Cookie."
    )
