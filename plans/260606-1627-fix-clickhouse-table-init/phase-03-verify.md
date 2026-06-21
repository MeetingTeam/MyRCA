---
phase: 3
title: "Verify"
status: completed
priority: P1
effort: "5m"
dependencies: [2]
---

# Phase 3: Verify

## Overview

Verify the fix by checking logs and testing API endpoints.

## Verification Steps

### Step 1: Check service logs

After deployment, verify the init message appears:
```bash
kubectl logs -n rca deployment/trace-rca-service --tail=20 | grep -i "incidents table"
```

Expected output:
```
[INFO] Incidents table initialized
```

### Step 2: Test API endpoints

```bash
# Test healthcheck
kubectl exec -n rca deployment/rca-dashboard -- wget -qO- http://trace-rca-service:8080/api/healthcheck

# Test applications endpoint (requires auth, so test via dashboard)
# Or test directly with a valid token
```

### Step 3: Verify via Dashboard

1. Open http://34.226.226.116.nip.io:30880
2. Login with Google
3. Dashboard should load without "Error: Failed to fetch incidents"
4. Apps filter should not show "Error loading apps"

## Success Criteria

- [ ] Log shows "Incidents table initialized" on startup
- [ ] `/api/healthcheck` returns `{"status":"ok"}`
- [ ] Dashboard loads without errors
- [ ] No "Table does not exist" errors in logs
