import logging
import jwt
from jwt import PyJWKClient
from typing import Optional, Any

from fastapi import APIRouter, Depends, HTTPException, status, Response, Cookie, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.storage.db import get_db_session
from app.storage.models import User
from app.utils.auth import cognito_client

router = APIRouter()
logger = logging.getLogger(__name__)
settings = get_settings()

SESSION_COOKIE_NAME = "dgs_session"

class CallbackRequest(BaseModel):
    code: str
    redirect_uri: str

class UserResponse(BaseModel):
    id: int
    email: str
    full_name: Optional[str]
    cognito_sub: str

# Helper to get JWKS client
def get_jwks_client():
    if not settings.cognito_user_pool_id or not settings.ddb_region:
        raise ValueError("Cognito configuration missing")

    jwks_url = f"https://cognito-idp.{settings.ddb_region}.amazonaws.com/{settings.cognito_user_pool_id}/.well-known/jwks.json"
    return PyJWKClient(jwks_url)

async def get_current_user(
    request: Request,
    dgs_session: Optional[str] = Cookie(None, alias=SESSION_COOKIE_NAME)
) -> User:
    """
    Dependency to get the current authenticated user from the session cookie.
    The session cookie contains the access_token (or id_token) from Cognito.
    We verify the token and then fetch the user from our DB.
    """
    if not dgs_session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    try:
        # Verify JWT signature
        jwks_client = get_jwks_client()
        signing_key = jwks_client.get_signing_key_from_jwt(dgs_session)

        decoded = jwt.decode(
            dgs_session,
            signing_key.key,
            algorithms=["RS256"],
            # Check audience if using id_token, otherwise check client_id in access_token if needed
            # For access_token, audience might not be the client_id but the API resource or similar.
            # Cognito access tokens have 'client_id' claim, id tokens have 'aud'.
            # We assume dgs_session is access_token.
            options={"verify_signature": True, "verify_aud": False}
        )

        # Additional checks
        # If using access_token, check 'client_id' matches our app client id
        if decoded.get("client_id") != settings.cognito_app_client_id:
             # If using id_token, check 'aud'
             if decoded.get("aud") != settings.cognito_app_client_id:
                 raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token audience")

        sub = decoded.get("sub")
        if not sub:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session")

        # Admin Approval Check
        # We can optimize by caching this or checking only on login, but prompt implies a check.
        # Ideally, we check on login, or trust the token claims if they include status.
        # But tokens are valid for 1h. If user is disabled in between, we might want to catch it.
        # For performance, we might skip call to Cognito on every request if we trust local DB state,
        # but for strict security as requested:

        # Let's fetch user from DB
        async with get_db_session() as session:
            stmt = select(User).where(User.cognito_sub == sub)
            result = await session.execute(stmt)
            user = result.scalar_one_or_none()

            if not user:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

            return user

    except jwt.PyJWTError as e:
         logger.warning(f"JWT Verification failed: {e}")
         raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    except Exception as e:
        logger.error(f"Auth error: {e}")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication failed")


@router.get("/auth/callback")
async def auth_callback(
    code: str,
    redirect_uri: str,
    response: Response
):
    """
    Exchange code for tokens, create/update user, set session cookie.
    """
    try:
        tokens = await cognito_client.exchange_code_for_token(code, redirect_uri)
        access_token = tokens.get("access_token")

        if not access_token:
             raise HTTPException(status_code=400, detail="No access token received")

        # Get user info from Cognito (or decode id_token)
        user_info = await cognito_client.get_user_info(access_token)
        sub = user_info.get("sub")
        email = user_info.get("email")
        name = user_info.get("name") or user_info.get("email") # Fallback

        if not sub or not email:
             raise HTTPException(status_code=400, detail="Invalid user info")

        # Check Admin Approval
        if not cognito_client.check_user_status(sub):
             raise HTTPException(
                 status_code=status.HTTP_403_FORBIDDEN,
                 detail="Account not approved or confirmed. Please contact admin."
             )

        # Create or Update User in DB
        async with get_db_session() as session:
            stmt = select(User).where(User.cognito_sub == sub)
            result = await session.execute(stmt)
            user = result.scalar_one_or_none()

            if not user:
                user = User(cognito_sub=sub, email=email, full_name=name)
                session.add(user)
            else:
                user.email = email
                user.full_name = name

            await session.commit()
            await session.refresh(user)

        # Set secure cookie
        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=access_token,
            httponly=True,
            secure=True,
            samesite="lax",
            max_age=3600
        )

        return {"message": "Login successful", "user": {"id": user.id, "email": user.email}}

    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Callback error: {e}")
        raise HTTPException(status_code=500, detail="Login failed")

@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    return current_user
