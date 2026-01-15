from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status, Request, Response
from fastapi.security import APIKeyHeader
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
import firebase_admin
from firebase_admin import auth as firebase_auth
from firebase_admin import credentials

from app.config import get_settings
from app.storage.database import get_db
from app.storage.user_repo import UserRepository
from app.storage.models import User

settings = get_settings()
logger = logging.getLogger(__name__)

# Initialize Firebase Admin
try:
    if settings.firebase_service_account_path:
        cred = credentials.Certificate(settings.firebase_service_account_path)
        firebase_admin.initialize_app(cred)
    elif settings.firebase_project_id:
        # Implicit setup (e.g. within GCP environment) or using project_id
        # Note: initialize_app() without credential will use Google Application Default Credentials
        # We can also pass project_id to options if needed.
        firebase_admin.initialize_app(options={'projectId': settings.firebase_project_id})
    else:
        # Attempt default initialization (e.g. works if GOOGLE_APPLICATION_CREDENTIALS is set)
        firebase_admin.initialize_app()
    logger.info("Firebase Admin initialized successfully.")
except ValueError:
    logger.warning("Firebase app already initialized.")
except Exception as e:
    logger.error(f"Failed to initialize Firebase Admin: {e}")

router = APIRouter(prefix="/api/auth", tags=["auth"])

class LoginRequest(BaseModel):
    id_token: str

class UserSchema(BaseModel):
    email: str
    full_name: str | None
    is_approved: bool

class LoginResponse(BaseModel):
    message: str
    user: UserSchema

async def get_current_user_from_cookie(
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> User:
    session_cookie = request.cookies.get("session")
    if not session_cookie:
        # Check for Dev Key as fallback for non-browser clients or dev
        dev_key = request.headers.get("X-DGS-Dev-Key")
        if dev_key and dev_key == settings.dev_key:
             # Return a mock admin user for dev key access?
             # Or we can just bypass auth checks in endpoints if dev key is present.
             # However, the requirement says "100% of API endpoints ... protected by get_current_active_user"
             # Let's handle dev key users specially.
             # Ideally we should have a user record for the system/dev.
             # For now, let's create a dummy user or just raise if not session.
             pass

        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    try:
        # Verify the session cookie. In this design, we are setting the cookie ourselves.
        # However, Firebase Auth has `create_session_cookie`.
        # "DGS generates a session cookie (or an encrypted internal JWT)"
        # Let's use Firebase Session Cookies as they are secure and easy to verify.

        decoded_claims = await run_in_threadpool(
            firebase_auth.verify_session_cookie, session_cookie, check_revoked=True
        )
        firebase_uid = decoded_claims["uid"]
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session")

    user_repo = UserRepository(db)
    user = await user_repo.get_by_firebase_uid(firebase_uid)
    if not user:
        # Should not happen if flow is correct, but safe to handle
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    return user

async def get_current_active_user(
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> User:
    # Check for Dev Key first
    dev_key = request.headers.get("X-DGS-Dev-Key")
    if dev_key and dev_key == settings.dev_key:
        # Return the persistent Dev Admin user from DB to ensure audit logs work (FK constraint).
        user_repo = UserRepository(db)
        dev_user = await user_repo.get_by_firebase_uid("dev-admin-uid")
        if not dev_user:
             dev_user = await user_repo.create_user(
                 firebase_uid="dev-admin-uid",
                 email="dev@local",
                 full_name="Dev Admin"
             )
             # Auto-approve dev user
             dev_user.is_approved = True
             db.add(dev_user)
             await db.commit()
             await db.refresh(dev_user)
        return dev_user

    user = await get_current_user_from_cookie(request, db)
    if not user.is_approved:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User not approved")
    return user

@router.post("/login", response_model=LoginResponse)
async def login(
    request: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db)
):
    id_token = request.id_token
    expires_in = 60 * 60 * 24 * 5 * 1000 # 5 days

    try:
        # Verify the ID token
        decoded_token = await run_in_threadpool(firebase_auth.verify_id_token, id_token)
        firebase_uid = decoded_token["uid"]
        email = decoded_token.get("email")
        name = decoded_token.get("name")

        # Create session cookie
        session_cookie = await run_in_threadpool(
             firebase_auth.create_session_cookie, id_token, expires_in=expires_in
        )

        # Check if user exists in DB, if not create
        user_repo = UserRepository(db)
        user = await user_repo.get_by_firebase_uid(firebase_uid)

        if not user:
            if not email:
                 raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email required")
            user = await user_repo.create_user(firebase_uid, email, name)

        # Set cookie
        response.set_cookie(
            key="session",
            value=session_cookie,
            httponly=True,
            secure=True, # Should be True in prod
            samesite="lax",
            max_age=60 * 60 * 24 * 5 # 5 days in seconds
        )

        return LoginResponse(
            message="Login successful",
            user=UserSchema(
                email=user.email,
                full_name=user.full_name,
                is_approved=user.is_approved
            )
        )

    except Exception as e:
        logger.error(f"Login failed: {e}")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication failed")

@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie("session")
    return {"message": "Logged out"}
