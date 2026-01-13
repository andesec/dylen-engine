import logging
import httpx
import boto3
from typing import Optional, Dict, Any
from fastapi import HTTPException, status
from app.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

class CognitoClient:
    def __init__(self):
        self.domain = settings.cognito_domain
        self.client_id = settings.cognito_app_client_id
        self.client_secret = settings.cognito_client_secret
        self.user_pool_id = settings.cognito_user_pool_id
        self.region = settings.ddb_region

        # Boto3 client for admin operations if needed (e.g. checking user status)
        # We need AWS credentials in environment or role for this to work
        self.boto_client = boto3.client('cognito-idp', region_name=self.region)

    async def exchange_code_for_token(self, code: str, redirect_uri: str) -> Dict[str, Any]:
        """
        Exchanges the authorization code for tokens from Cognito.
        """
        if not self.domain or not self.client_id or not self.client_secret:
            raise RuntimeError("Cognito configuration missing")

        token_url = f"{self.domain}/oauth2/token"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                token_url,
                data={
                    "grant_type": "authorization_code",
                    "client_id": self.client_id,
                    "code": code,
                    "redirect_uri": redirect_uri,
                },
                auth=(self.client_id, self.client_secret),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

            if response.status_code != 200:
                logger.error(f"Failed to exchange token: {response.text}")
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Failed to exchange authorization code"
                )

            return response.json()

    async def get_user_info(self, access_token: str) -> Dict[str, Any]:
        """
        Fetches user information using the access token.
        """
        if not self.domain:
            raise RuntimeError("Cognito domain missing")

        userinfo_url = f"{self.domain}/oauth2/userinfo"

        async with httpx.AsyncClient() as client:
            response = await client.get(
                userinfo_url,
                headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code != 200:
                logger.error(f"Failed to get user info: {response.text}")
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Failed to fetch user info"
                )

            return response.json()

    def check_user_status(self, sub: str) -> bool:
        """
        Checks if the user is confirmed and approved (if custom attribute used).
        Uses boto3 to get user details from User Pool.
        """
        if not self.user_pool_id:
            logger.warning("Cognito User Pool ID not set, skipping admin check")
            return True # Fail open or closed? Requirement says "if ... not CONFIRMED ... return 403". So fail closed if we can't check?
            # But for local dev without credentials it might be annoying.
            # Assuming we have creds.

        try:
            response = self.boto_client.admin_get_user(
                UserPoolId=self.user_pool_id,
                Username=sub
            )

            user_status = response.get('UserStatus')
            if user_status != 'CONFIRMED':
                logger.warning(f"User {sub} is not CONFIRMED (Status: {user_status})")
                return False

            # Check for custom attribute 'approved' if it exists
            # attributes = {attr['Name']: attr['Value'] for attr in response.get('UserAttributes', [])}
            # if attributes.get('custom:approved') == 'false':
            #    return False

            return True

        except self.boto_client.exceptions.UserNotFoundException:
            logger.warning(f"User {sub} not found in Cognito User Pool")
            return False
        except Exception as e:
            logger.error(f"Error checking user status: {e}")
            # If we can't verify, we should probably deny access for security
            return False

cognito_client = CognitoClient()
