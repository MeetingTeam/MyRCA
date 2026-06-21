---
title: "Fix incident root_cause serialization"
description: "JSON serialize root_cause dict before inserting to ClickHouse String column"
status: completed
priority: P1
branch: "main"
tags: [bugfix, clickhouse]
blockedBy: []
blocks: []
created: "2026-06-06T09:58:59.701Z"
createdBy: "ck:plan"
source: skill
---

# Fix incident root_cause serialization

## Overview

**Problem:** Incidents fail to save with error `'dict' object has no attribute 'encode'`. The `root_cause` field is a dict (`{"service": "...", "confidence": 0.85}`) but ClickHouse expects a String.

**Solution:** JSON serialize `root_cause` on save, parse on read.

## Root Cause

```python
# save_incident() line 124
stage2.get("root_cause", ""),  # ← dict passed to String column
```

`llm_result["root_cause"]` = `{"service": "svc-name", "confidence": 0.85}` (dict, not string)

## Phases

| Phase | Name | Status | Effort |
|-------|------|--------|--------|
| 1 | [Implement](./phase-01-implement.md) | Completed | 5m |
| 2 | [Deploy](./phase-02-deploy.md) | Completed | 5m |
| 3 | [Verify](./phase-03-verify.md) | Completed | 5m |

## Files to Modify

| File | Change |
|------|--------|
| `trace_rca_algo/trace_rca_service/incident_store.py` | JSON serialize root_cause on save (L124), parse on read (L160) |

## Dependencies

None
