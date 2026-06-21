---
title: "RCA Dashboard ClickHouse Fix + Gmail Authentication"
description: "Fix ClickHouse API integration bug and add Google OAuth2 login"
status: completed
priority: P1
branch: "main"
tags: [bugfix, clickhouse, auth, oauth2, google]
blockedBy: []
blocks: []
created: "2026-06-06T07:56:30.882Z"
createdBy: "ck:plan"
source: skill
---

# RCA Dashboard ClickHouse Fix + Gmail Authentication

## Context

**Problem 1 (BLOCKING):** Dashboard shows "Failed to fetch incidents" because `api.py` passes `db_con` to `incident_store` functions that no longer accept it (signature mismatch after ClickHouse migration).

**Problem 2:** RCA dashboard endpoints are publicly accessible. Need authentication.

**Goal:** Fix ClickHouse integration bug, then implement Gmail login.

**Stack:**
- Backend: FastAPI (Python) at `trace_rca_algo/trace_rca_service/`
- Frontend: React + Vite at `trace_rca_algo/rca-dashboard/`
- Deployment: Docker + K8s (NodePort 30880)

## Bug Analysis

```
api.py calls:                           incident_store.py expects:
─────────────────────────────────────   ─────────────────────────────────────
list_applications(db_con)               list_applications()  ← NO params!
list_incidents(db_con, app_id=...)      list_incidents(app_id=None, ...)
get_incident(db_con, incident_id, ...)  get_incident(incident_id, app_id=None)

Result: db_con passed as positional arg → TypeError or wrong query
```

## Phases

| Phase | Name | Status | Effort |
|-------|------|--------|--------|
| 0 | [Fix ClickHouse API Integration](./phase-00-fix-clickhouse-api-integration.md) | Completed | 1h |
| 1 | [Research OAuth2 and Google Identity](./phase-01-research-oauth2-and-google-identity.md) | Completed | 2h |
| 2 | [Backend Auth Setup](./phase-02-backend-auth-setup.md) | Completed | 4h |
| 3 | [Frontend Login Integration](./phase-03-frontend-login-integration.md) | Completed | 3h |
| 4 | [Testing and Deployment](./phase-04-testing-and-deployment.md) | Completed | 2h |

## Files to Modify

| File | Change |
|------|--------|
| `trace_rca_service/api.py` | **FIX:** Remove db_con from incident_store calls |
| `trace_rca_service/api.py` | Add auth middleware, login/logout endpoints |
| `trace_rca_service/auth.py` | **NEW** - Google token verification, JWT creation |
| `trace_rca_service/requirements.txt` | Add google-auth, PyJWT |
| `rca-dashboard/src/api.js` | Add auth header, token refresh |
| `rca-dashboard/src/auth-context.jsx` | **NEW** - Auth state management |
| `rca-dashboard/src/components/login-page.jsx` | **NEW** - Login UI |
| `rca-dashboard/src/App.jsx` | Add AuthProvider, protected routes |
| `rca-dashboard/package.json` | Add @react-oauth/google |

## Architecture (After Fix)

```
┌─────────────────────────────────────────────────────────────────┐
│  Dashboard (React)                                              │
│       │                                                         │
│       ▼                                                         │
│  GET /api/incidents                                             │
│       │                                                         │
│       ▼                                                         │
│  api.py → incident_store.list_incidents()                       │
│       │              │                                          │
│       │              └── _get_clickhouse() (internal client)    │
│       │                        │                                │
│       ▼                        ▼                                │
│  JSON response ◄── ClickHouse (K8s cluster)                    │
└─────────────────────────────────────────────────────────────────┘
```

## Dependencies

- ClickHouse cluster must be accessible from trace-rca-service pod
- Google Cloud Console: OAuth2 Client ID (for Phase 1+)

## Risk Assessment

| Risk | Mitigation |
|------|------------|
| ClickHouse connection fail | Check env vars, K8s service DNS |
| Token theft via XSS | CSP headers, sanitize inputs |

## Notes

- Phase 0 is **critical** — dashboard is currently broken
- Rebuild and redeploy Docker image after Phase 0 to fix production

---

## Validation Log

### Session 1 — 2026-06-06
**Trigger:** User requested plan verification
**Questions asked:** 4

#### Verification Results
- **Tier:** Full (5 phases)
- **Claims checked:** 11
- **Verified:** 11 | **Failed:** 0 | **Unverified:** 0
- Bug confirmed: `api.py:35,48,57` passes `db_con` to functions that don't accept it

#### Questions & Answers

1. **[Architecture]** JWT tokens will be stored in localStorage. This is simple but vulnerable to XSS. Do you want to use httpOnly cookies instead for better security?
   - Options: localStorage (Recommended) | httpOnly cookies | sessionStorage
   - **Answer:** localStorage (Recommended)
   - **Rationale:** Simple SPA approach, faster to implement. Add CSP headers for XSS mitigation.

2. **[Security]** How long should the session JWT token be valid before requiring re-login?
   - Options: 24 hours (Recommended) | 7 days | 1 hour + refresh token
   - **Answer:** 24 hours (Recommended)
   - **Rationale:** Balance between security and UX. Users re-login daily.

3. **[Scope]** Do you have a Google Cloud project with OAuth2 credentials ready?
   - Options: Need setup instructions | Already have credentials
   - **Answer:** Need setup instructions
   - **Rationale:** Phase 1 must include step-by-step Google Cloud Console setup.

4. **[Deployment]** What is your Docker image registry?
   - Options: Amazon ECR | Docker Hub | Self-hosted
   - **Answer:** Docker Hub
   - **Rationale:** Update deployment commands to use Docker Hub.

#### Confirmed Decisions
- Token storage: localStorage with CSP headers
- Token expiry: 24 hours (JWT_EXPIRE_HOURS=24)
- Google OAuth: Include full setup instructions in Phase 1
- Docker: Use Docker Hub for image registry

#### Impact on Phases
- Phase 1: Ensure Google Cloud Console setup instructions are complete
- Phase 2: Confirm JWT_EXPIRE_HOURS=24 in auth.py
- Phase 4: Update Docker commands to reference Docker Hub
