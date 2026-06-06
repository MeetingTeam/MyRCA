---
title: "Add MLOps Panel"
description: "Add MLOps panel with external links to Evidently, Airflow, MLflow"
status: completed
priority: P1
branch: "main"
tags: [frontend, mlops]
blockedBy: []
blocks: []
created: "2026-06-06T17:39:58.293Z"
createdBy: "ck:plan"
source: skill
---

# Add MLOps Panel

## Overview

Add MLOps menu item to sidebar linking to a page with external tool links (Evidently, Airflow, MLflow). Follows existing Grafana Links pattern.

## External URLs

| Tool | URL |
|------|-----|
| Evidently | http://34.226.226.116:30800/ |
| Airflow | http://34.226.226.116:30380/ |
| MLflow | http://34.226.226.116:30002/ |

## Phases

| Phase | Name | Status | Effort |
|-------|------|--------|--------|
| 1 | [Implement MLOps Links](./phase-01-implement-mlops-links.md) | Completed | 10m |

## Files to Modify

| File | Change |
|------|--------|
| `src/components/mlops-links.jsx` | Create - MLOps links component |
| `src/components/sidebar.jsx` | Modify - Add MLOps menu item |
| `src/App.jsx` | Modify - Add /mlops route |

## Dependencies

None.
