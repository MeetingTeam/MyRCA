---
phase: 5
title: "Deploy and Test"
status: in-progress
priority: P1
effort: "20m"
dependencies: [4]
---

# Phase 5: Deploy and Test

## Overview

Build final image, push to registry, and deploy to K8s cluster.

**Status**: IN-PROGRESS - Docker image built and pushed (asdads6495/my-airflow:3.0.6 and :latest). User needs to:
- Run kubectl commands to update deployments with new image
- Restart deployments to pull new image
- Wait for rollouts to complete

## Implementation Steps

1. **Build and push final image**:
   ```bash
   cd D:/KLTN/MyRCA/mlops
   docker build -t asdads6495/my-airflow:3.0.6 -f Dockerfile.airflow .
   docker push asdads6495/my-airflow:3.0.6
   
   # Also tag as latest
   docker tag asdads6495/my-airflow:3.0.6 asdads6495/my-airflow:latest
   docker push asdads6495/my-airflow:latest
   ```

2. **Update deployments**:
   ```bash
   kubectl set image deployment/airflow-scheduler \
     scheduler=asdads6495/my-airflow:3.0.6 \
     scheduler-log-groomer=asdads6495/my-airflow:3.0.6 \
     -n airflow
   
   kubectl set image deployment/airflow-webserver \
     webserver=asdads6495/my-airflow:3.0.6 \
     -n airflow
   ```

3. **Restart deployments**:
   ```bash
   kubectl rollout restart deployment/airflow-scheduler -n airflow
   kubectl rollout restart deployment/airflow-webserver -n airflow
   ```

4. **Wait for rollouts**:
   ```bash
   kubectl rollout status deployment/airflow-scheduler -n airflow --timeout=180s
   kubectl rollout status deployment/airflow-webserver -n airflow --timeout=180s
   ```

5. **Verify Airflow version in running pods**:
   ```bash
   kubectl exec -n airflow deployment/airflow-scheduler -c scheduler -- airflow version
   # Expected: 3.0.6
   ```

6. **Check scheduler logs for errors**:
   ```bash
   kubectl logs -n airflow deployment/airflow-scheduler -c scheduler --tail=50
   ```

## Success Criteria

- [ ] Image built and pushed successfully
- [ ] Deployments rolled out without errors
- [ ] `airflow version` returns 3.0.6 in running pods
- [ ] No startup errors in scheduler logs
