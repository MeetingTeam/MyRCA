---
phase: 3
title: "Deploy and Verify"
status: completed
priority: P1
effort: "15m"
dependencies: [2]
---

# Phase 3: Deploy and Verify

## Overview

Deploy the updated Airflow image to K8s and verify the bug is fixed by running a test DAG.

## Implementation Steps

1. Update Airflow deployments to use new image:
   ```bash
   kubectl set image deployment/airflow-scheduler \
     scheduler=asdads6495/my-airflow:latest \
     scheduler-log-groomer=asdads6495/my-airflow:latest \
     -n airflow
   
   kubectl set image deployment/airflow-webserver \
     webserver=asdads6495/my-airflow:latest \
     -n airflow
   ```

2. Wait for rollouts:
   ```bash
   kubectl rollout status deployment/airflow-scheduler -n airflow --timeout=180s
   kubectl rollout status deployment/airflow-webserver -n airflow --timeout=180s
   ```

3. Verify provider version in running pod:
   ```bash
   kubectl exec -n airflow deployment/airflow-scheduler -c scheduler -- \
     pip show apache-airflow-providers-cncf-kubernetes | grep Version
   ```

4. Trigger test DAG and verify task completes:
   ```bash
   kubectl exec -n airflow deployment/airflow-scheduler -c scheduler -- \
     airflow dags trigger training_pipeline -r "test-k8s-fix"
   ```

5. Monitor task state (should transition from queued → running → success):
   ```bash
   kubectl exec -n airflow deployment/airflow-scheduler -c scheduler -- \
     airflow tasks states-for-dag-run training_pipeline "test-k8s-fix"
   ```

6. Check scheduler logs for correct state handling:
   ```bash
   kubectl logs -n airflow deployment/airflow-scheduler -c scheduler --tail=50 | \
     grep -E "(drift_detection|Succeeded|state)"
   ```

## Success Criteria

- [ ] Airflow deployments rolled out successfully
- [ ] Provider version ≥10.1.0 in running pods
- [ ] Test DAG task transitions to `success` state (not stuck in `queued`)
- [ ] Scheduler logs show proper state handling after pod completion

## Rollback

If issues occur:
```bash
kubectl rollout undo deployment/airflow-scheduler -n airflow
kubectl rollout undo deployment/airflow-webserver -n airflow
```
