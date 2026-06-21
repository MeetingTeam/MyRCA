---
phase: 2
title: "Deploy"
status: completed
priority: P1
effort: "5m"
dependencies: [1]
---

# Phase 2: Deploy

## Overview

Rebuild Docker image, push to registry, and restart K8s deployment.

## Deployment Steps

### Step 1: Build Docker image

```bash
cd trace_rca_algo/trace_rca_service
docker build -t asdads6495/myrca-trace-rca-service:auth .
```

### Step 2: Push to Docker Hub

```bash
docker push asdads6495/myrca-trace-rca-service:auth
```

### Step 3: Restart K8s deployment

```bash
kubectl rollout restart deployment/trace-rca-service -n rca
kubectl rollout status deployment/trace-rca-service -n rca --timeout=120s
```

### Step 4: Verify deployment

```bash
# Check pod is running
kubectl get pods -n rca -l app=trace-rca-service

# Check logs for init message
kubectl logs -n rca deployment/trace-rca-service --tail=10
```

## Success Criteria

- [ ] Docker image built successfully
- [ ] Image pushed to asdads6495/myrca-trace-rca-service:auth
- [ ] Deployment rolled out successfully
- [ ] Pod status is Running
- [ ] Logs show "Incidents table initialized"
