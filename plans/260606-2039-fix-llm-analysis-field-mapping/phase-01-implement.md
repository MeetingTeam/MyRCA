---
phase: 1
title: "Implement"
status: complete
priority: P1
effort: "5m"
dependencies: []
---

# Phase 1: Implement

## Overview

Fix field mapping in `save_incident()` and `_row_to_incident()` to correctly save/read LLM analysis data.

## Related Code Files

- Modify: `trace_rca_algo/trace_rca_service/incident_store.py`

## Implementation Steps

### Step 1: Fix save_incident() - Line 126

**Before:**
```python
stage2.get("analysis_summary", ""),
```

**After:**
```python
json.dumps(stage2.get("analysis", [])),
```

### Step 2: Fix _row_to_incident() - Line 162

**Before:**
```python
"analysis_summary": data["analysis_summary"],
```

**After:**
```python
"analysis": json.loads(data["analysis_summary"]) if data["analysis_summary"] else [],
```

## Success Criteria

- [ ] `save_incident()` serializes `analysis` list to JSON string
- [ ] `_row_to_incident()` parses `analysis_summary` back to list
- [ ] No syntax errors
