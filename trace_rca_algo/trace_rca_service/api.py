"""FastAPI REST endpoints for RCA incident dashboard."""

from typing import Optional
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

import incident_store

app = FastAPI(title="RCA Incident API", version="1.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Injected by main.py before server starts
db_con = None


def set_db_con(con):
    global db_con
    db_con = con


@app.get("/api/healthcheck")
def healthcheck():
    return {"status": "ok"}


@app.get("/api/applications")
def list_applications():
    """List all unique app_ids from incidents."""
    return incident_store.list_applications(db_con)


@app.get("/api/incidents")
def list_incidents(
    app_id: Optional[str] = Query(None, description="Filter by single app_id"),
    app_ids: Optional[str] = Query(None, description="Filter by multiple app_ids (comma-separated)"),
    limit: int = Query(100, ge=1, le=1000, description="Max incidents to return"),
):
    """List incidents with optional app filtering."""
    app_ids_list = None
    if app_ids:
        app_ids_list = [a.strip() for a in app_ids.split(",") if a.strip()]
    return incident_store.list_incidents(db_con, app_id=app_id, app_ids=app_ids_list, limit=limit)


@app.get("/api/incidents/{incident_id}")
def get_incident(
    incident_id: str,
    app_id: Optional[str] = Query(None, description="App ID hint for faster lookup"),
):
    """Get a single incident by ID. Provide app_id for faster lookup."""
    result = incident_store.get_incident(db_con, incident_id, app_id=app_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return result
