---
phase: 2
title: "Rebuild Airflow Image"
status: completed
priority: P1
effort: "10m"
dependencies: [1]
---

# Phase 2: Rebuild Airflow Image

## Overview

Rebuild the custom Airflow image with the updated kubernetes provider and push to DockerHub.

## Related Code Files

- Read: `mlops/Dockerfile.airflow`
- Read: `mlops/airflow-requirements.txt`

## Implementation Steps

1. Build the new Airflow image:
   ```bash
   cd D:/KLTN/MyRCA/mlops
   docker build -t asdads6495/my-airflow:latest -f Dockerfile.airflow .
   ```

2. Verify the provider version in the new image:
   ```bash
   docker run --rm asdads6495/my-airflow:latest pip show apache-airflow-providers-cncf-kubernetes
   ```

3. Push to DockerHub:
   ```bash
   docker push asdads6495/my-airflow:latest
   ```

## Success Criteria

- [ ] Docker image built successfully
- [ ] Image contains `apache-airflow-providers-cncf-kubernetes>=10.1.0`
- [ ] Image pushed to `asdads6495/my-airflow:latest`
