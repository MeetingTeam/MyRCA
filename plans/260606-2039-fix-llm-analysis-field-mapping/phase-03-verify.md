---
phase: 3
title: "Verify"
status: complete
priority: P1
effort: "5m"
dependencies: [2]
---

# Phase 3: Verify

## Overview

Inject anomaly and verify LLM analysis is saved and displayed in dashboard.

## Verification Steps

### Step 1: Check service logs

```bash
kubectl logs -n rca deployment/trace-rca-service --tail=20
```

Expected: No errors, "Saved incident" message

### Step 2: Inject test anomaly

Trigger RCA pipeline to generate new incident with LLM analysis.

### Step 3: Query ClickHouse

```bash
kubectl exec -n rca deployment/trace-rca-service -- python -c "
from clickhouse_driver import Client
import os
client = Client(host=os.getenv('CLICKHOUSE_HOST'), port=9000)
result = client.execute('SELECT analysis_summary FROM incidents ORDER BY created_at DESC LIMIT 1')
print(f'analysis_summary: {result[0][0][:100] if result[0][0] else \"EMPTY\"}')"
```

Expected: `analysis_summary` contains JSON array, NOT "EMPTY"

### Step 4: Check Dashboard

1. Open http://34.226.226.116.nip.io:30880
2. Click on an incident
3. Verify "LLM Analysis" section shows analysis data

## Success Criteria

- [ ] `analysis_summary` contains JSON in ClickHouse
- [ ] Dashboard shows "LLM Analysis" with service classifications
- [ ] No errors in service logs
