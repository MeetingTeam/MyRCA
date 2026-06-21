---
title: "Upgrade Airflow 2.10.4 to 3.0.6"
description: "Major version upgrade to fix KubernetesExecutor state tracking and get native fixes"
status: in-progress
priority: P1
branch: "main"
tags: [airflow, upgrade, kubernetes]
blockedBy: []
blocks: []
created: "2026-06-06T09:36:22.388Z"
createdBy: "ck:plan"
source: skill
---

# Upgrade Airflow 2.10.4 to 3.0.6

## Overview

**Goal:** Upgrade from Airflow 2.10.4 to 3.0.6 to get native fix for KubernetesExecutor state tracking bug (GitHub #41436, #42991).

**Why 3.0.6?**
- Latest stable 3.0.x release (proven production-ready)
- Contains native fixes for state tracking bugs
- No need for custom patches
- Python 3.12 support

**Key Breaking Changes:**
| Change | Migration |
|--------|-----------|
| Config: `[kubernetes]` → `[kubernetes_executor]` | Update Helm values |
| KubernetesExecutor in provider package | Install `apache-airflow-providers-cncf-kubernetes>=10.x` |
| Some imports moved to `airflow.sdk` | Update DAG imports |
| `execution_date` context var removed | Use `logical_date` instead |
| SubDAGs removed | Use TaskGroups (not used in our DAGs) |

**Image:** `apache/airflow:3.0.6-python3.12`

## Phases

| Phase | Name | Status | Effort |
|-------|------|--------|--------|
| 1 | [Prepare](./phase-01-prepare.md) | Skip | 15m |
| 2 | [Update-Dockerfile](./phase-02-update-dockerfile.md) | Completed | 10m |
| 3 | [Update-DAGs](./phase-03-update-dags.md) | Completed | 20m |
| 4 | [Update-Helm-Config](./phase-04-update-helm-config.md) | In-Progress | 15m |
| 5 | [Deploy-Test](./phase-05-deploy-test.md) | In-Progress | 20m |
| 6 | [Verify-Fix](./phase-06-verify-fix.md) | Pending | 10m |

## Files to Modify

| File | Change |
|------|--------|
| `mlops/Dockerfile.airflow` | Update base image, remove patch |
| `mlops/airflow-requirements.txt` | Update dependencies |
| `mlops/dags/*.py` | Update imports if needed |
| Helm values | Update `[kubernetes]` → `[kubernetes_executor]` |

## Breaking Changes Discovered

During implementation:
- **`schedule_interval` → `schedule`**: Parameter renamed in DAG definitions. All 4 DAGs updated.
- **`days_ago` removed**: Use `pendulum.today('UTC').add(days=-N)` instead. All DAGs updated.

## Risk Assessment

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| Breaking changes in 3.0 | Medium | Thorough testing before prod |
| DAG import errors | Low | Review all imports |
| Helm config incompatible | Low | Follow migration guide |

## Rollback

```bash
kubectl rollout undo deployment/airflow-scheduler -n airflow
kubectl rollout undo deployment/airflow-webserver -n airflow
```

## Validation Log

### Verification Results (2026-06-06)
- Claims checked: 5
- Verified: 2 | Warnings: 3 | Failed: 0
- Tier: Full (6 phases)

| Check | Status | Action |
|-------|--------|--------|
| Airflow 3.0.6 image | ✓ VERIFIED | Docker pull succeeded |
| No deprecated context vars | ✓ VERIFIED | No `execution_date` usage |
| `days_ago` deprecated | ⚠ WARNING | **Decision:** Replace with pendulum |
| Worker image repo mismatch | ⚠ WARNING | **Decision:** Use `asdads6495/` |
| Duplicate config sections | ⚠ WARNING | **Decision:** Remove `[kubernetes]` |

### User Decisions
1. **Deprecated imports:** Replace `days_ago` with `pendulum.today('UTC').add(days=-N)`
2. **Image repository:** Use `asdads6495/my-airflow` (update Helm config)
3. **Config cleanup:** Remove old `[kubernetes]` section, keep only `[kubernetes_executor]`
4. **Database migration:** Clear old runs for fresh start (avoid state conflicts)
