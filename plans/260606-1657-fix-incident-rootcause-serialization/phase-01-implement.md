---
phase: 1
title: "Implement"
status: pending
priority: P1
effort: "5m"
dependencies: []
---

# Phase 1: Implement

## Overview

Fix `save_incident()` to JSON serialize `root_cause` dict, and `_row_to_incident()` to parse it back.

## Related Code Files

- Modify: `trace_rca_algo/trace_rca_service/incident_store.py`

## Implementation Steps

### Step 1: Fix save_incident() - Line 124

**Before:**
```python
stage2.get("root_cause", ""),
```

**After:**
```python
json.dumps(stage2.get("root_cause", {})) if isinstance(stage2.get("root_cause"), dict) else str(stage2.get("root_cause", "")),
```

### Step 2: Fix _row_to_incident() - Line 160

**Before:**
```python
"root_cause": data["root_cause"],
```

**After:**
```python
"root_cause": json.loads(data["root_cause"]) if data["root_cause"] else {},
```

## Success Criteria

- [ ] `save_incident()` JSON serializes root_cause dict
- [ ] `_row_to_incident()` parses root_cause back to dict
- [ ] No syntax errors in incident_store.py
