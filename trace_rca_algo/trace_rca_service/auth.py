"""Google OAuth2 verification and JWT session management."""

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from google.oauth2 import id_token
from google.auth.transport import requests

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
JWT_SECRET = os.getenv("JWT_SECRET", "")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRE_HOURS = int(os.getenv("JWT_EXPIRE_HOURS", "24"))

if not JWT_SECRET:
    raise RuntimeError("JWT_SECRET environment variable must be set")


class AuthError(Exception):
    """Authentication error with status code."""

    def __init__(self, message: str, status_code: int = 401):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def verify_google_token(token: str) -> dict:
    """Verify Google ID token and return user info."""
    if not GOOGLE_CLIENT_ID:
        raise AuthError("GOOGLE_CLIENT_ID not configured", 500)

    try:
        idinfo = id_token.verify_oauth2_token(
            token, requests.Request(), GOOGLE_CLIENT_ID
        )

        if idinfo["iss"] not in ["accounts.google.com", "https://accounts.google.com"]:
            raise AuthError("Invalid token issuer")

        return {
            "email": idinfo["email"],
            "name": idinfo.get("name", ""),
            "picture": idinfo.get("picture", ""),
            "sub": idinfo["sub"],
        }
    except ValueError as e:
        raise AuthError(f"Invalid Google token: {e}")


def create_session_token(user: dict) -> str:
    """Create JWT session token for authenticated user."""
    payload = {
        "sub": user["email"],
        "email": user["email"],
        "name": user.get("name", ""),
        "picture": user.get("picture", ""),
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRE_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_session_token(token: str) -> dict:
    """Verify JWT session token and return user info."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return {
            "email": payload["email"],
            "name": payload.get("name", ""),
            "picture": payload.get("picture", ""),
        }
    except jwt.ExpiredSignatureError:
        raise AuthError("Token expired")
    except jwt.InvalidTokenError as e:
        raise AuthError(f"Invalid token: {e}")


def get_current_user(authorization: Optional[str]) -> dict:
    """Extract and verify user from Authorization header."""
    if not authorization:
        raise AuthError("Missing Authorization header")

    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise AuthError("Invalid Authorization format. Expected: Bearer <token>")

    return verify_session_token(parts[1])
