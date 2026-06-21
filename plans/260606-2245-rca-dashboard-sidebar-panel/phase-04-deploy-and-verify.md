---
phase: 4
title: "Deploy and Verify"
status: completed
priority: P1
effort: "10m"
dependencies: [3]
---

# Phase 4: Deploy and Verify

## Overview

Build Docker image, push to registry, rollout K8s deployment, and verify sidebar works in production.

## Deployment Steps

### Step 1: Build Docker Image

```bash
cd D:/KLTN/MyRCA/trace_rca_algo/rca-dashboard
npm run build
docker build -t asdads6495/myrca-rca-dashboard:auth .
```

### Step 2: Push to Docker Hub

```bash
docker push asdads6495/myrca-rca-dashboard:auth
```

### Step 3: Rollout K8s Deployment

```bash
kubectl rollout restart deployment/rca-dashboard -n rca
kubectl rollout status deployment/rca-dashboard -n rca --timeout=120s
```

### Step 4: Verify Deployment

```bash
kubectl get pods -n rca -l app=rca-dashboard
kubectl logs -n rca deployment/rca-dashboard --tail=10
```

## Verification Checklist

1. **Open Dashboard:** http://34.226.226.116.nip.io:30880
2. **Check Sidebar:**
   - [ ] Sidebar visible on left side
   - [ ] All 5 menu items present (Dashboard, Roles & Users, Projects, Grafana, API Keys)
   - [ ] Toggle collapse/expand works
   - [ ] Active route highlighted
3. **Test Navigation:**
   - [ ] Dashboard → shows incident list
   - [ ] Roles & Users → shows "Coming Soon" placeholder
   - [ ] Projects → shows "Coming Soon" placeholder
   - [ ] Grafana → shows 3 dashboard link cards
   - [ ] API Keys → shows "Coming Soon" placeholder
4. **Test Persistence:**
   - [ ] Collapse sidebar, refresh page → stays collapsed
   - [ ] Expand sidebar, refresh page → stays expanded

## Success Criteria

- [ ] Docker image built successfully
- [ ] Image pushed to asdads6495/myrca-rca-dashboard:auth
- [ ] K8s deployment rolled out
- [ ] Pod status is Running
- [ ] All verification checklist items pass
