"""FastAPI REST endpoints for RCA incident dashboard."""

import os
from typing import Optional
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import auth
import incident_store

app = FastAPI(title="RCA Incident API", version="1.2.0")

CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*").split(",")


class GoogleLoginRequest(BaseModel):
    id_token: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


def get_current_user(authorization: Optional[str] = Header(None)) -> dict:
    """Dependency to get current authenticated user."""
    try:
        return auth.get_current_user(authorization)
    except auth.AuthError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/healthcheck")
def healthcheck():
    return {"status": "ok"}


@app.post("/api/auth/google", response_model=LoginResponse)
def google_login(request: GoogleLoginRequest):
    """Authenticate with Google ID token and return session JWT."""
    try:
        user_info = auth.verify_google_token(request.id_token)
        token = auth.create_session_token(user_info)
        return LoginResponse(
            access_token=token,
            user={
                "email": user_info["email"],
                "name": user_info["name"],
                "picture": user_info["picture"],
            },
        )
    except auth.AuthError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@app.get("/api/auth/me")
def get_me(user: dict = Depends(get_current_user)):
    """Get current authenticated user info."""
    return user


@app.get("/api/applications")
def list_applications(_: dict = Depends(get_current_user)):
    """List all unique app_ids from incidents."""
    return incident_store.list_applications()


@app.get("/api/incidents")
def list_incidents(
    app_id: Optional[str] = Query(None, description="Filter by single app_id"),
    app_ids: Optional[str] = Query(None, description="Filter by multiple app_ids (comma-separated)"),
    limit: int = Query(100, ge=1, le=1000, description="Max incidents to return"),
    _: dict = Depends(get_current_user),
):
    """List incidents with optional app filtering."""
    app_ids_list = None
    if app_ids:
        app_ids_list = [a.strip() for a in app_ids.split(",") if a.strip()]
    return incident_store.list_incidents(app_id=app_id, app_ids=app_ids_list, limit=limit)


@app.get("/api/incidents/{incident_id}")
def get_incident(
    incident_id: str,
    app_id: Optional[str] = Query(None, description="App ID hint for faster lookup"),
    _: dict = Depends(get_current_user),
):
    """Get a single incident by ID. Provide app_id for faster lookup."""
    result = incident_store.get_incident(incident_id, app_id=app_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return result
