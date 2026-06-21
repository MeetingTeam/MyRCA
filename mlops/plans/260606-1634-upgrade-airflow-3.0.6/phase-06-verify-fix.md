---
phase: 6
title: "Verify Fix"
status: pending
priority: P1
effort: "10m"
dependencies: [5]
---

**Status**: PENDING - Blocked by Phase 5 deployment completion. User must verify after K8s deployment is live.

# Phase 6: Verify Fix

## Overview

Verify that the KubernetesExecutor state tracking bug is fixed in Airflow 3.0.6.

## Implementation Steps

1. **Trigger a test DAG run**:
   ```bash
   RUN_ID="test-3.0.6-$(date +%s)"
   kubectl exec -n airflow deployment/airflow-scheduler -c scheduler -- \
     airflow dags trigger training_pipeline -r "$RUN_ID"
   ```

2. **Monitor task state transitions**:
   ```bash
   # Wait 30 seconds for task to start
   kubectl exec -n airflow deployment/airflow-scheduler -c scheduler -- \
     airflow tasks states-for-dag-run training_pipeline "$RUN_ID"
   ```

3. **Check scheduler logs for state handling**:
   ```bash
   kubectl logs -n airflow deployment/airflow-scheduler -c scheduler --tail=100 | \
     grep -iE "(succeeded|success|state)"
   ```

4. **Verify NO state mismatch error**:
   ```bash
   # Should NOT see this error anymore:
   # "finished with state success, but the task instance's state attribute is queued"
   kubectl logs -n airflow deployment/airflow-scheduler -c scheduler --tail=200 | \
     grep -i "state attribute is queued"
   # Expected: No output (error no longer occurs)
   ```

5. **Verify task completes successfully**:
   ```bash
   # Task should transition: queued → running → success
   kubectl exec -n airflow deployment/airflow-scheduler -c scheduler -- \
     airflow tasks states-for-dag-run training_pipeline "$RUN_ID" | grep drift_detection
   # Expected: state = success (not up_for_retry or queued)
   ```

## Success Criteria

- [ ] Task pod completes with "Succeeded" status
- [ ] Scheduler logs show proper state transitions
- [ ] **No "state attribute is queued" error in logs**
- [ ] Task state properly transitions to `success`
- [ ] Downstream tasks trigger correctly

## Cleanup (if successful)

1. Remove old 2.10.4 patch files:
   ```bash
   rm -rf D:/KLTN/MyRCA/mlops/patches/
   ```

2. Update documentation in `docs/` to reflect Airflow 3.0.6
