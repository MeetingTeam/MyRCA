---
title: "Fix LLM analysis field mapping"
description: "Fix field name mismatch: llm_result uses 'analysis' but save_incident looks for 'analysis_summary'"
status: complete
priority: P1
branch: "main"
tags: [bugfix, clickhouse]
blockedBy: []
blocks: []
created: "2026-06-06T13:41:06.731Z"
createdBy: "ck:plan"
source: skill
---

# Fix LLM analysis field mapping

## Overview

**Problem:** Dashboard shows "No LLM analysis available" because `analysis_summary` is EMPTY in ClickHouse.

**Root Cause:** Field name mismatch
- `llm_result` returns: `{"analysis": [...], "propagation_chain": [...]}`
- `save_incident()` looks for: `stage2.get("analysis_summary", "")`

**Solution:** Map `analysis` → `analysis_summary` with JSON serialization.

## Evidence

```sql
SELECT analysis_summary FROM incidents LIMIT 3;
-- Returns: EMPTY, EMPTY, EMPTY
```

But `llm_result` contains:
```python
{"analysis": [{"service": "...", "classification": "INTRINSIC", "evidence": "..."}]}
```

## Phases

| Phase | Name | Status | Effort |
|-------|------|--------|--------|
| 1 | [Implement](./phase-01-implement.md) | Complete | 5m |
| 2 | [Deploy](./phase-02-deploy.md) | Complete | 5m |
| 3 | [Verify](./phase-03-verify.md) | Complete | 5m |

## Files to Modify

| File | Change |
|------|--------|
| `trace_rca_algo/trace_rca_service/incident_store.py` | Fix field mapping in save/read |

## Dependencies

None
