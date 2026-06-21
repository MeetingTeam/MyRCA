---
phase: 4
title: "Update Helm Config"
status: in-progress
priority: P1
effort: "15m"
dependencies: [3]
---

# Phase 4: Update Helm Config

## Overview

Update Airflow Helm chart configuration for 3.0 compatibility. Key change: `[kubernetes]` → `[kubernetes_executor]`.

**Status**: IN-PROGRESS - No local values.yaml file found. User needs to run kubectl commands to update the K8s configmap with:
- Remove old `[kubernetes]` section
- Update `[kubernetes_executor]` with correct image repo (asdads6495)
- Update image tags to 3.0.6

<!-- Updated: Validation Session 1 - Remove [kubernetes] section, fix image repo to asdads6495 -->

## Implementation Steps

1. **Find current Helm values**:
   ```bash
   kubectl get cm airflow-config -n airflow -o yaml | grep -A 20 "\[kubernetes"
   ```

2. **REMOVE old `[kubernetes]` section** (validation decision):
   - Current config has BOTH sections - causes confusion
   - Airflow 3.0 only uses `[kubernetes_executor]`
   - Delete the entire `[kubernetes]` block

3. **Fix worker_container_repository** (validation decision):
   ```yaml
   # Current (WRONG): hungtran679/my-airflow
   # Correct: asdads6495/my-airflow
   ```

4. **Update config section names** in Helm values:
   ```yaml
   # Old (2.x)
   config:
     kubernetes:
       namespace: airflow
       worker_container_repository: asdads6495/my-airflow
       worker_container_tag: latest
       delete_worker_pods: true
   
   # New (3.0)
   config:
     kubernetes_executor:
       namespace: airflow
       worker_container_repository: asdads6495/my-airflow
       worker_container_tag: "3.0.6"
       delete_worker_pods: true
   ```

3. **Update image references** in Helm values:
   ```yaml
   images:
     airflow:
       repository: asdads6495/my-airflow
       tag: "3.0.6"
   ```

4. **Check for other deprecated configs**:
   ```yaml
   # Remove if present (deprecated in 3.0):
   # - celery_kubernetes_executor
   # - local_kubernetes_executor
   ```

## Helm Upgrade Command

```bash
helm upgrade airflow apache-airflow/airflow \
  -n airflow \
  -f values.yaml \
  --set images.airflow.repository=asdads6495/my-airflow \
  --set images.airflow.tag=3.0.6
```

## Success Criteria

- [ ] Config section renamed: `kubernetes` → `kubernetes_executor`
- [ ] Image tags updated to 3.0.6
- [ ] No deprecated executor configs
