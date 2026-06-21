---
phase: 0
title: "Fix ClickHouse API Integration"
status: completed
priority: P0
effort: "1h"
dependencies: []
---

# Phase 0: Fix ClickHouse API Integration

## Overview

Fix signature mismatch between `api.py` and `incident_store.py` that causes "Failed to fetch incidents" error.

## Bug Root Cause

The `incident_store.py` was refactored to use its own ClickHouse client via `_get_clickhouse()`, but `api.py` still passes the old `db_con` parameter.

**Current (broken):**
```python
# api.py line 35
return incident_store.list_applications(db_con)  # ← db_con not needed!

# api.py line 48
return incident_store.list_incidents(db_con, app_id=app_id, ...)  # ← db_con becomes app_id!

# api.py line 57
result = incident_store.get_incident(db_con, incident_id, ...)  # ← db_con becomes incident_id!
```

**Expected signatures in incident_store.py:**
```python
def list_applications() -> list[str]
def list_incidents(app_id: str = None, app_ids: list[str] = None, limit: int = 100)
def get_incident(incident_id: str, app_id: str = None)
```

## Related Code Files

- Modify: `trace_rca_algo/trace_rca_service/api.py`
- Reference: `trace_rca_algo/trace_rca_service/incident_store.py`

## Implementation Steps

### Step 1: Update api.py

Remove `db_con` from all `incident_store` function calls:

```python
# BEFORE (broken):
@app.get("/api/applications")
def list_applications():
    return incident_store.list_applications(db_con)

@app.get("/api/incidents")
def list_incidents(...):
    ...
    return incident_store.list_incidents(db_con, app_id=app_id, app_ids=app_ids_list, limit=limit)

@app.get("/api/incidents/{incident_id}")
def get_incident(incident_id: str, app_id: Optional[str] = Query(None)):
    result = incident_store.get_incident(db_con, incident_id, app_id=app_id)
    ...

# AFTER (fixed):
@app.get("/api/applications")
def list_applications():
    return incident_store.list_applications()

@app.get("/api/incidents")
def list_incidents(...):
    ...
    return incident_store.list_incidents(app_id=app_id, app_ids=app_ids_list, limit=limit)

@app.get("/api/incidents/{incident_id}")
def get_incident(incident_id: str, app_id: Optional[str] = Query(None)):
    result = incident_store.get_incident(incident_id, app_id=app_id)
    ...
```

### Step 2: Remove Dead Code

Remove unused `db_con` and `set_db_con()`:

```python
# DELETE these lines from api.py:
# db_con = None
#
# def set_db_con(con):
#     global db_con
#     db_con = con
```

### Step 3: Test Locally

```bash
cd trace_rca_algo/trace_rca_service
export CLICKHOUSE_HOST=localhost  # or your ClickHouse address
python -c "
from api import app
from fastapi.testclient import TestClient
client = TestClient(app)
print(client.get('/api/healthcheck').json())
print(client.get('/api/applications').json())
print(client.get('/api/incidents?limit=5').json())
"
```

### Step 4: Rebuild and Deploy

```bash
# Build new image
docker build -t your-registry/trace-rca-service:fix-api trace_rca_algo/trace_rca_service

# Push and deploy
docker push your-registry/trace-rca-service:fix-api
kubectl set image deployment/trace-rca-service trace-rca-service=your-registry/trace-rca-service:fix-api

# Verify
kubectl rollout status deployment/trace-rca-service
curl http://34.226.226.116:30880/api/healthcheck
curl http://34.226.226.116:30880/api/incidents?limit=3
```

## Success Criteria

- [x] `api.py` updated — no `db_con` in incident_store calls
- [x] `/api/healthcheck` returns `{"status": "ok"}`
- [x] `/api/applications` returns list (may be empty)
- [x] `/api/incidents` returns list (may be empty)
- [x] Dashboard at http://34.226.226.116:30880/ loads without error

## Risk Assessment

| Risk | Mitigation |
|------|------------|
| ClickHouse unreachable | Check CLICKHOUSE_HOST env var in K8s deployment |
| Empty results | Verify incidents table has data |

## Verification Commands

```bash
# Check ClickHouse connection from pod
kubectl exec -it deployment/trace-rca-service -- python -c "
from incident_store import _get_clickhouse
client = _get_clickhouse()
print(client.execute('SELECT count() FROM incidents'))
"
```
