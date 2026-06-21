---
phase: 1
title: "Research OAuth2 and Google Identity"
status: completed
priority: P2
effort: "2h"
dependencies: []
---

# Phase 1: Research OAuth2 and Google Identity

## Overview

Research Google OAuth2 implementation patterns for FastAPI backend + React frontend. Set up Google Cloud credentials.

## Requirements

- Functional: Understand OAuth2 authorization code flow, ID token verification
- Non-functional: Secure credential storage, proper scopes

## Architecture

```
Google OAuth2 Flow (Implicit/ID Token for SPA):

1. User clicks "Sign in with Google"
2. Google login popup → user authenticates
3. Google returns ID Token (JWT) to frontend
4. Frontend sends ID Token to backend POST /api/auth/google
5. Backend verifies token with Google's public keys
6. Backend creates session JWT, returns to frontend
7. Frontend stores JWT, uses for subsequent API calls
```

## Related Code Files

- Reference: `trace_rca_service/api.py` (existing API structure)
- Reference: `rca-dashboard/src/api.js` (existing API client)

## Implementation Steps
<!-- Updated: Validation Session 1 - User needs detailed setup instructions -->

### Step 1: Google Cloud Console Setup (Detailed)

1. **Create/Select Project**
   - Go to [Google Cloud Console](https://console.cloud.google.com/)
   - Create new project or select existing
   - Note project ID

2. **Configure OAuth Consent Screen**
   *(No API enablement needed — Google Identity Services works with just OAuth credentials)*
   - Navigate: APIs & Services → OAuth consent screen
   - Select "External" (or "Internal" for G Suite)
   - Fill required fields:
     - App name: `MyRCA Dashboard`
     - User support email: your email
     - Developer contact: your email
   - Add scopes: `email`, `profile`, `openid`
   - Add test users (if in testing mode)

3. **Create OAuth2 Credentials**
   - Navigate: APIs & Services → Credentials
   - Click "Create Credentials" → "OAuth client ID"
   - Application type: **Web application**
   - Name: `MyRCA Dashboard Web Client`
   - **Authorized JavaScript origins:**
     ```
     http://localhost:5173
     http://localhost:8082
     http://34.226.226.116.nip.io:30880
     ```
     *(Note: Google OAuth rejects bare IP addresses. Use `nip.io` wildcard DNS service — `<IP>.nip.io` resolves to that IP)*
   - **Authorized redirect URIs:** (leave empty for implicit flow)
   - Click Create
   - **Copy Client ID** (looks like `xxx.apps.googleusercontent.com`): 309305824654-tr8sc9p0jjbmlmvsnv19kdun2n4hugjd.apps.googleusercontent.com

4. **Save Credentials**
   - Client ID → Use in frontend `VITE_GOOGLE_CLIENT_ID`
   - Client ID → Use in backend `GOOGLE_CLIENT_ID`
   - Client Secret → Not needed for ID token flow

### Step 2: Research Libraries

- Backend: `google-auth` for ID token verification
- Backend: `PyJWT` for session token creation
- Frontend: `@react-oauth/google` for Google Sign-In button

### Step 3: Security Considerations

- ID Token expires in 1 hour — verify `exp` claim
- Session JWT: 24h expiry (confirmed in validation)
- Store Google Client ID as env var `GOOGLE_CLIENT_ID`
- Store JWT secret as env var `JWT_SECRET`

### Step 4: Document Environment Variables

```bash
# Backend
GOOGLE_CLIENT_ID=309305824654-tr8sc9p0jjbmlmvsnv19kdun2n4hugjd.apps.googleusercontent.com
JWT_SECRET=<random-32-byte-string>
JWT_ALGORITHM=HS256
JWT_EXPIRE_HOURS=24

# Frontend
VITE_GOOGLE_CLIENT_ID=xxx.apps.googleusercontent.com
```

## Success Criteria

- [x] Google Cloud OAuth2 Client ID created
- [x] Authorized origins configured for dev and prod
- [x] Environment variables documented
- [x] Library versions confirmed compatible

## Risk Assessment

| Risk | Mitigation |
|------|------------|
| Client ID exposure | Client ID is public by design; only allows login |
| JWT secret leak | Use K8s secrets, never commit to git |

## Next Steps

→ Phase 2: Implement backend auth endpoints with verified research
