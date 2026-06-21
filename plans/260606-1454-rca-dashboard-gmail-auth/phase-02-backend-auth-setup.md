---
phase: 2
title: "Backend Auth Setup"
status: completed
priority: P1
effort: "4h"
dependencies: [1]
---

# Phase 2: Backend Auth Setup

## Overview

Implement Google OAuth2 token verification and JWT session management in FastAPI backend.

## Requirements

- Functional: Verify Google ID tokens, issue session JWTs, protect API endpoints
- Non-functional: <100ms auth overhead, secure token handling

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  api.py                                                        │
│  ├── /api/auth/google   [POST]  ← Verify Google token, return JWT│
│  ├── /api/auth/me       [GET]   ← Return current user info      │
│  ├── /api/healthcheck   [GET]   ← Public (no auth)              │
│  └── /api/*             [*]     ← Protected (require JWT)       │
│                                                                  │
│  auth.py                                                        │
│  ├── verify_google_token(id_token) → user_info                  │
│  ├── create_session_jwt(user_info) → jwt_string                 │
│  ├── verify_session_jwt(jwt_string) → user_info                 │
│  └── get_current_user(request) → user_info (FastAPI Depends)   │
└─────────────────────────────────────────────────────────────────┘
```

## Related Code Files

- Modify: `trace_rca_service/api.py`
- Create: `trace_rca_service/auth.py`
- Modify: `trace_rca_service/requirements.txt`
- Reference: `trace_rca_service/main.py` (uvicorn startup)

## Implementation Steps

### Step 1: Add Dependencies

Update `requirements.txt`:
```
google-auth>=2.0.0
PyJWT>=2.8.0
```

### Step 2: Create auth.py Module

```python
"""Google OAuth2 + JWT session auth for RCA API."""

import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
from fastapi import HTTPException, Request, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

log = logging.getLogger("trace-rca-service")

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret-change-in-prod")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRE_HOURS = int(os.getenv("JWT_EXPIRE_HOURS", "24"))

security = HTTPBearer(auto_error=False)


def verify_google_token(token: str) -> dict:
    """Verify Google ID token and return user info."""
    try:
        idinfo = id_token.verify_oauth2_token(
            token, google_requests.Request(), GOOGLE_CLIENT_ID
        )
        return {
            "email": idinfo["email"],
            "name": idinfo.get("name", ""),
            "picture": idinfo.get("picture", ""),
            "sub": idinfo["sub"],  # Google user ID
        }
    except ValueError as e:
        log.warning(f"Invalid Google token: {e}")
        raise HTTPException(status_code=401, detail="Invalid Google token")


def create_session_jwt(user_info: dict) -> str:
    """Create session JWT from verified user info."""
    payload = {
        "sub": user_info["email"],
        "name": user_info.get("name", ""),
        "picture": user_info.get("picture", ""),
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRE_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_session_jwt(token: str) -> dict:
    """Verify session JWT and return user info."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return {
            "email": payload["sub"],
            "name": payload.get("name", ""),
            "picture": payload.get("picture", ""),
        }
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> dict:
    """FastAPI dependency for protected routes."""
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return verify_session_jwt(credentials.credentials)
```

### Step 3: Update api.py

Add auth endpoints and middleware:

```python
from pydantic import BaseModel
import auth

class GoogleLoginRequest(BaseModel):
    id_token: str

@app.post("/api/auth/google")
def google_login(req: GoogleLoginRequest):
    """Exchange Google ID token for session JWT."""
    user_info = auth.verify_google_token(req.id_token)
    session_token = auth.create_session_jwt(user_info)
    return {
        "access_token": session_token,
        "token_type": "bearer",
        "user": {
            "email": user_info["email"],
            "name": user_info.get("name"),
            "picture": user_info.get("picture"),
        },
    }

@app.get("/api/auth/me")
def get_me(user: dict = Depends(auth.get_current_user)):
    """Get current authenticated user."""
    return user

# Protect existing endpoints
@app.get("/api/applications")
def list_applications(user: dict = Depends(auth.get_current_user)):
    return incident_store.list_applications(db_con)

@app.get("/api/incidents")
def list_incidents(
    user: dict = Depends(auth.get_current_user),
    app_id: Optional[str] = Query(None),
    app_ids: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
):
    # ... existing logic
```

### Step 4: Test Locally

```bash
# Set env vars
export GOOGLE_CLIENT_ID=your-client-id
export JWT_SECRET=test-secret-32-chars-min

# Test auth endpoint
curl -X POST http://localhost:8082/api/auth/google \
  -H "Content-Type: application/json" \
  -d '{"id_token": "..."}'
```

## Success Criteria

- [x] `auth.py` created with Google token verification
- [x] `/api/auth/google` endpoint exchanges token for JWT
- [x] `/api/auth/me` returns current user
- [x] Protected endpoints require valid JWT
- [x] Healthcheck remains public

## Risk Assessment

| Risk | Mitigation |
|------|------------|
| JWT secret in code | Use env vars, K8s secrets |
| Token replay | Short expiry, consider refresh tokens |

## Security Considerations

- JWT_SECRET must be at least 32 bytes for HS256
- Never log tokens or user passwords
- Set CORS origins explicitly in production
