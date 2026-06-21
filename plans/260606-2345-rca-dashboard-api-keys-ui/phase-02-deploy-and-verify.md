---
phase: 2
title: "Deploy and Verify"
status: completed
priority: P1
effort: "10m"
dependencies: [1]
---

# Phase 2: Deploy and Verify

## Overview

Build Docker image, push to registry, rollout K8s deployment, verify API Keys page works.

## Deployment Steps

### Step 1: Build and Push

```bash
cd D:/KLTN/MyRCA/trace_rca_algo/rca-dashboard
npm run build
docker build -t asdads6495/myrca-rca-dashboard:auth .
docker push asdads6495/myrca-rca-dashboard:auth
```

### Step 2: K8s Rollout

```bash
kubectl rollout restart deployment/rca-dashboard -n rca
kubectl rollout status deployment/rca-dashboard -n rca --timeout=120s
```

### Step 3: Verify

Open http://34.226.226.116.nip.io:30880/api-keys

## Success Criteria

- [ ] Build succeeds
- [ ] Docker image pushed
- [ ] K8s rollout complete
- [ ] API Keys page loads (no "Coming Soon")
- [ ] Can add/view/delete API keys
- [ ] Keys persist after page refresh
