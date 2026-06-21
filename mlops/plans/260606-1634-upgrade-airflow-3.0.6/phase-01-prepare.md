---
phase: 1
title: "Prepare"
status: skip
priority: P1
effort: "15m"
dependencies: []
---

# Phase 1: Prepare

## Overview

Backup current state and verify prerequisites before upgrading.

**Status**: SKIP - User needs to run backup commands manually before proceeding with upgrade. This is a prerequisite that requires manual K8s operations and cannot be automated.

## Implementation Steps

1. **Backup current Airflow database**:
   ```bash
   kubectl exec -n airflow deployment/airflow-scheduler -c scheduler -- \
     airflow db export /tmp/airflow_backup.json
   kubectl cp airflow/airflow-scheduler-XXX:/tmp/airflow_backup.json ./backup/
   ```

2. **Document current DAG runs**:
   ```bash
   kubectl exec -n airflow deployment/airflow-scheduler -c scheduler -- \
     airflow dags list-runs -d training_pipeline --limit 10
   ```

3. **Verify Docker login**:
   ```bash
   docker login
   ```

4. **Check Kubernetes cluster version** (must be 1.26+):
   ```bash
   kubectl version --short
   ```

5. **Tag current image for rollback**:
   ```bash
   docker tag asdads6495/my-airflow:latest asdads6495/my-airflow:2.10.4-backup
   docker push asdads6495/my-airflow:2.10.4-backup
   ```

6. **Clear old DAG runs** (validation decision - fresh start):
   <!-- Updated: Validation Session 1 - Clear old runs to avoid state conflicts -->
   ```bash
   # After backup, clear task instances to avoid state conflicts
   kubectl exec -n airflow deployment/airflow-scheduler -c scheduler -- \
     airflow dags delete training_pipeline --yes
   kubectl exec -n airflow deployment/airflow-scheduler -c scheduler -- \
     airflow dags delete kb_building_dag --yes
   # Note: DAGs will be recreated from files after upgrade
   ```

## Success Criteria

- [ ] Database backup exported
- [ ] Current image tagged as backup
- [ ] K8s cluster version >= 1.26
- [ ] Docker login verified
- [ ] Old DAG runs cleared (fresh start)
