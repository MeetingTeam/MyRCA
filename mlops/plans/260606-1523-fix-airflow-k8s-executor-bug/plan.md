---
title: "Fix Airflow KubernetesExecutor State Bug"
description: "Patch kubernetes_executor_utils.py to fix pod success state tracking"
status: completed
priority: P1
branch: "main"
tags: [airflow, bugfix, kubernetes]
blockedBy: []
blocks: []
created: "2026-06-06T08:24:03.857Z"
createdBy: "ck:plan"
source: skill
completedAt: "2026-06-06T09:20:00Z"
---

# Fix Airflow KubernetesExecutor State Bug

## Overview

**Problem:** Airflow KubernetesExecutor has a bug where pod "Succeeded" events result in `state=None` instead of `TaskInstanceState.SUCCESS`. Tasks remain stuck in "queued" state even after pods complete successfully.

**Root Cause:** `kubernetes_executor_utils.py` in Airflow core:
```python
elif status == "Succeeded":
    self.watcher_queue.put((pod_name, namespace, None, ...))  # BUG: None instead of SUCCESS
```

**Key Finding:** The bug is in Airflow CORE (not the provider package). For Airflow 2.x, the executor code comes from core Airflow, not from `apache-airflow-providers-cncf-kubernetes`. The fix (PR #42624) was merged to `main` but never backported to Airflow 2.x.

**Fix Applied:** Custom patch script that modifies `kubernetes_executor_utils.py` at Docker build time to replace `None` with `TaskInstanceState.SUCCESS`.

**Reference:** [GitHub Issue #41436](https://github.com/apache/airflow/issues/41436), [PR #42624](https://github.com/apache/airflow/pull/42624)

## Phases

| Phase | Name | Status | Effort |
|-------|------|--------|--------|
| 1 | [Update Requirements](./phase-01-update-requirements.md) | Completed | 5m |
| 2 | [Rebuild Airflow Image](./phase-02-rebuild-airflow-image.md) | Completed | 10m |
| 3 | [Deploy and Verify](./phase-03-deploy-and-verify.md) | Completed | 15m |

## Files Modified

| File | Change |
|------|--------|
| `mlops/Dockerfile.airflow` | Added patch step for executor bug |
| `mlops/patches/fix_k8s_executor_succeeded_state.py` | New patch script |

## Verification

Before patch:
```
Changing state of (..., None, ...) to None
```

After patch:
```
Changing state of (..., <TaskInstanceState.SUCCESS: 'success'>, ...) to success
```

## Risk Assessment

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| Patch fails on future Airflow versions | Medium | Pin Airflow version; upgrade to 3.x when stable |
| Image build fails | Low | Test locally before push |
| Deployment fails | Low | Rollback via `kubectl rollout undo` |
