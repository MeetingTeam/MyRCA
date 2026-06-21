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

Build Docker image, push to registry, rollout K8s deployment, verify Roles & Users page works.

## Deployment Steps

### Step 1: Build and Push

```bash
cd D:/KLTN/MyRCA/trace_rca_algo/rca-dashboard
npm run build
docker build \
  --build-arg VITE_GOOGLE_CLIENT_ID=309305824654-tr8sc9p0jjbmlmvsnv19kdun2n4hugjd.apps.googleusercontent.com \
  -t asdads6495/myrca-rca-dashboard:auth .
docker push asdads6495/myrca-rca-dashboard:auth
```

### Step 2: K8s Rollout

```bash
kubectl rollout restart deployment/rca-dashboard -n rca
kubectl rollout status deployment/rca-dashboard -n rca --timeout=120s
```

### Step 3: Verify

Open http://34.226.226.116.nip.io:30880/users

## Success Criteria

- [ ] Build succeeds
- [ ] Docker image pushed
- [ ] K8s rollout complete
- [ ] Roles & Users page loads (no "Coming Soon")
- [ ] Can add/view/edit/delete users
- [ ] Users persist after page refresh
- [ ] Current user shows with "You" badge
