---
phase: 1
title: "Implement"
status: completed
priority: P1
effort: "5m"
dependencies: []
---

# Phase 1: Implement

## Overview

Add `incident_store.init_incidents_table()` call to `main.py` startup to ensure the incidents table exists before the service starts processing.

## Related Code Files

- Modify: `trace_rca_algo/trace_rca_service/main.py`
- Reference: `trace_rca_algo/trace_rca_service/incident_store.py` (contains `init_incidents_table()`)

## Implementation Steps

### Step 1: Add init call to main.py

In `main.py`, inside the `main()` function, add the table initialization call **before** starting the Kafka consumer:

```python
def main():
    log.info("Starting RCA Service...")
    
    # Initialize incidents table in ClickHouse
    incident_store.init_incidents_table()
    
    # Setup Kafka consumer (existing code)
    consumer = Consumer({
        ...
    })
```

**Location:** After line 204 (`log.info("Starting RCA Service...")`)

### Step 2: Verify the function signature

The `init_incidents_table()` function (incident_store.py:47-72):
- Takes no parameters
- Uses internal `_get_clickhouse()` singleton
- Creates table with `IF NOT EXISTS` (safe to call multiple times)
- Logs "Incidents table initialized" on success

## Success Criteria

- [ ] `incident_store.init_incidents_table()` called in `main()` after startup log
- [ ] No import changes needed (`incident_store` already imported)
- [ ] Code compiles without errors
