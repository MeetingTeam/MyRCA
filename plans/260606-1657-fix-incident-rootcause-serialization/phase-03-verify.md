---
phase: 3
title: "Verify"
status: pending
priority: P1
effort: "5m"
dependencies: [2]
---

# Phase 3: Verify

## Overview

Inject anomaly, verify incident saves and displays in dashboard.

## Verification Steps

### Step 1: Check service logs for errors

```bash
kubectl logs -n rca deployment/trace-rca-service --tail=30 | grep -i "error\|incident"
```

Expected: No `'dict' object has no attribute 'encode'` error

### Step 2: Inject test anomaly

Trigger RCA pipeline to generate new incident (via Kafka or existing test)

### Step 3: Verify incident saved

```bash
kubectl logs -n rca deployment/trace-rca-service --tail=20 | grep "Saved incident"
```

Expected: `Saved incident <uuid> to ClickHouse`

### Step 4: Check Dashboard

1. Open http://34.226.226.116.nip.io:30880
2. Login with Google
3. Dashboard should show incident (not "No incidents detected")

## Success Criteria

- [ ] No serialization errors in logs
- [ ] Log shows "Saved incident" message
- [ ] Dashboard displays incident
- [ ] Incident shows root_cause service name
