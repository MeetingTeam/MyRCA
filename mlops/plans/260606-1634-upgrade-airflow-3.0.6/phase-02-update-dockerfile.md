---
phase: 2
title: "Update Dockerfile"
status: completed
priority: P1
effort: "10m"
dependencies: [1]
---

# Phase 2: Update Dockerfile

## Overview

Update Dockerfile.airflow to use Airflow 3.0.6 base image and remove custom patches (no longer needed).

**Status**: COMPLETED - Dockerfile.airflow updated to use apache/airflow:3.0.6-python3.12. Custom patches removed. Verified locally with docker build.

## Related Code Files

- Modify: `mlops/Dockerfile.airflow`
- Modify: `mlops/airflow-requirements.txt`
- Delete: `mlops/patches/` (no longer needed)

## Implementation Steps

1. **Update `Dockerfile.airflow`**:
   ```dockerfile
   # Use Airflow 3.0.6 stable image
   FROM apache/airflow:3.0.6-python3.12

   WORKDIR /opt/airflow

   COPY airflow-requirements.txt .
   RUN pip install --no-cache-dir -r airflow-requirements.txt

   # No patch needed - 3.0.6 has native fix for #41436
   
   COPY --chown=airflow:root ./dags /opt/airflow/dags
   ```

2. **Update `airflow-requirements.txt`**:
   ```
   apache-airflow-providers-cncf-kubernetes>=10.0.0
   apache-airflow-providers-amazon>=9.0.0
   kubernetes
   mlflow-skinny
   ```

3. **Build test image locally**:
   ```bash
   cd D:/KLTN/MyRCA/mlops
   docker build -t asdads6495/my-airflow:3.0.6-test -f Dockerfile.airflow .
   ```

4. **Verify Airflow version in image**:
   ```bash
   docker run --rm asdads6495/my-airflow:3.0.6-test airflow version
   # Expected: 3.0.6
   ```

## Success Criteria

- [ ] Dockerfile updated to use `apache/airflow:3.0.6-python3.12`
- [ ] Requirements updated for 3.0 compatibility
- [ ] Patches directory removed
- [ ] Test image builds successfully
- [ ] `airflow version` returns 3.0.6
