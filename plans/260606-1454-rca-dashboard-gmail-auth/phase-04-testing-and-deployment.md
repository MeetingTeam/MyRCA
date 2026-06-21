---
phase: 4
title: "Testing and Deployment"
status: completed
priority: P2
effort: "2h"
dependencies: [3]
---

# Phase 4: Testing and Deployment

## Overview

Test auth flow end-to-end, update Docker images, deploy to K8s with secrets.

## Requirements

- Functional: All auth flows work in containerized environment
- Non-functional: No secrets in images, proper K8s secret management

## Architecture

```
Deployment Flow:

1. Build Docker images with auth code
2. Create K8s secrets for GOOGLE_CLIENT_ID, JWT_SECRET
3. Update Helm/K8s manifests to inject secrets
4. Deploy and verify
```

## Related Code Files

- Modify: `trace_rca_service/Dockerfile`
- Modify: `rca-dashboard/Dockerfile`
- Create: `opensource/trace-rca-service/auth-secrets.yaml`
- Modify: K8s deployment manifests (if any)

## Implementation Steps

### Step 1: Test Locally

```bash
# Terminal 1: Backend
cd trace_rca_algo/trace_rca_service
export GOOGLE_CLIENT_ID=xxx
export JWT_SECRET=test-secret-32-characters-min
python main.py

# Terminal 2: Frontend
cd trace_rca_algo/rca-dashboard
echo "VITE_GOOGLE_CLIENT_ID=xxx" > .env.development
echo "VITE_API_URL=http://localhost:8082" >> .env.development
npm run dev

# Test flow:
# 1. Open http://localhost:5173
# 2. Should redirect to /login
# 3. Click "Sign in with Google"
# 4. Should redirect to / with user info
# 5. Check API calls have Authorization header
```

### Step 2: Update Backend Dockerfile

No changes needed — Python picks up env vars at runtime.

### Step 3: Update Frontend Dockerfile

Build-time env vars for Vite:
```dockerfile
# rca-dashboard/Dockerfile
FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
ARG VITE_GOOGLE_CLIENT_ID
ARG VITE_API_URL
ENV VITE_GOOGLE_CLIENT_ID=$VITE_GOOGLE_CLIENT_ID
ENV VITE_API_URL=$VITE_API_URL
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
```

### Step 4: Create K8s Secrets

```yaml
# opensource/trace-rca-service/auth-secrets.yaml
apiVersion: v1
kind: Secret
metadata:
  name: rca-auth-secrets
  namespace: default
type: Opaque
stringData:
  GOOGLE_CLIENT_ID: "xxx.apps.googleusercontent.com"
  JWT_SECRET: "your-production-secret-32-bytes"
```

Apply:
```bash
kubectl apply -f opensource/trace-rca-service/auth-secrets.yaml
```

### Step 5: Update Deployment to Use Secrets

```yaml
# In deployment.yaml
spec:
  containers:
    - name: trace-rca-service
      envFrom:
        - secretRef:
            name: rca-auth-secrets
```

### Step 6: Build and Push Images (Docker Hub)
<!-- Updated: Validation Session 1 - Docker Hub confirmed -->

```bash
# Login to Docker Hub
docker login

# Backend
docker build -t <dockerhub-username>/trace-rca-service:auth trace_rca_algo/trace_rca_service

# Frontend (with build args)
docker build \
  --build-arg VITE_GOOGLE_CLIENT_ID=xxx \
  --build-arg VITE_API_URL=/api \
  -t <dockerhub-username>/rca-dashboard:auth \
  trace_rca_algo/rca-dashboard

docker push <dockerhub-username>/trace-rca-service:auth
docker push <dockerhub-username>/rca-dashboard:auth
```

### Step 7: Deploy and Verify

```bash
# Update deployments (replace <dockerhub-username> with actual username)
kubectl set image deployment/trace-rca-service \
  trace-rca-service=<dockerhub-username>/trace-rca-service:auth

kubectl set image deployment/rca-dashboard \
  rca-dashboard=<dockerhub-username>/rca-dashboard:auth

# Verify pods
kubectl get pods -w

# Test auth
curl -X POST https://your-domain/api/auth/google \
  -H "Content-Type: application/json" \
  -d '{"id_token": "test"}'
# Should return 401 (invalid token) not 500
```

### Step 8: Verify Production

**Important:** Access via `http://34.226.226.116.nip.io:30880` (not bare IP) — Google OAuth requires valid TLD.

- [ ] Navigate to `http://34.226.226.116.nip.io:30880`
- [ ] Redirects to /login
- [ ] Google Sign-In works
- [ ] Protected routes accessible after login
- [ ] Logout works
- [ ] Refresh preserves auth state

## Success Criteria

- [x] Local e2e auth flow works
- [x] Docker images build with auth code
- [x] K8s secrets created
- [x] Deployed services use secrets
- [x] Production auth flow verified

## Risk Assessment

| Risk | Mitigation |
|------|------------|
| Secret exposure in logs | Check deployment logs for secrets |
| Wrong redirect URI | Verify Google Console config |
| CORS issues | Check FastAPI CORS settings |

## Rollback Plan

If auth breaks production:
1. Revert to previous image tags
2. Remove auth middleware temporarily
3. Investigate in staging

## Post-Deployment

- Monitor for 401 errors (expired tokens)
- Add metrics for login success/failure rate
- Consider refresh token flow for long sessions
