---
title: "Fix ClickHouse Incidents Table Init"
description: "Add init_incidents_table() call to main.py startup to create table on service start"
status: completed
priority: P1
branch: "main"
tags: [bugfix, clickhouse]
blockedBy: []
blocks: []
created: "2026-06-06T09:30:04.465Z"
createdBy: "ck:plan"
source: skill
---

# Fix ClickHouse Incidents Table Init

## Overview

**Problem:** Dashboard shows "Error: Failed to fetch incidents" because `incidents` table doesn't exist in ClickHouse. The `init_incidents_table()` function exists but is never called.

**Solution:** Add `incident_store.init_incidents_table()` to `main.py` startup.

## Root Cause

```
Table default.incidents does not exist
```

The function `incident_store.init_incidents_table()` creates the table but is never invoked.

## Phases

| Phase | Name | Status | Effort |
|-------|------|--------|--------|
| 1 | [Implement](./phase-01-implement.md) | Completed | 5m |
| 2 | [Deploy](./phase-02-deploy.md) | Completed | 5m |
| 3 | [Verify](./phase-03-verify.md) | Completed | 5m |

## Files to Modify

| File | Change |
|------|--------|
| `trace_rca_algo/trace_rca_service/main.py` | Add `incident_store.init_incidents_table()` after imports |

## Dependencies

None
