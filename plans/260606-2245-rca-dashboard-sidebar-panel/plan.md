---
title: "RCA Dashboard Sidebar Panel"
description: "Add collapsible sidebar navigation panel with menu items for Dashboard, Role/User, Project, Grafana, and API Key"
status: completed
priority: P1
branch: "main"
tags: [frontend, ui, dashboard]
blockedBy: []
blocks: []
created: "2026-06-06T15:45:35.078Z"
createdBy: "ck:plan"
source: skill
---

# RCA Dashboard Sidebar Panel

## Overview

Add a collapsible sidebar panel to the RCA Dashboard with navigation menu items. This plan implements:
- **Full implementation:** Dashboard (incidents view) - UI + existing backend
- **UI only (backend later):** Role/User, Project, Grafana links, API Key

## Reference

![Sidebar Reference](d:\KLTN\pics\rca-feature-add.png)

## Menu Items

| Item | Icon | Description | Implementation |
|------|------|-------------|----------------|
| Dashboard | `LayoutDashboard` | View error incidents | Full (existing) |
| Roles & Users | `Users` | RBAC management | UI placeholder |
| Projects | `FolderKanban` | Multi-app management | UI placeholder |
| Grafana | `BarChart3` | External dashboard links | UI + external links |
| API Keys | `Key` | Model selection | UI placeholder |

## Phases

| Phase | Name | Status | Effort |
|-------|------|--------|--------|
| 1 | [Implement Sidebar Layout](./phase-01-implement-sidebar-layout.md) | Completed | 30m |
| 2 | [Add Navigation Routes](./phase-02-add-navigation-routes.md) | Completed | 30m |
| 3 | [Polish UI](./phase-03-polish-ui.md) | Completed | 20m |
| 4 | [Deploy and Verify](./phase-04-deploy-and-verify.md) | Completed | 10m |

## Files to Modify

| File | Change |
|------|--------|
| `src/App.jsx` | Refactor layout to include sidebar |
| `src/components/sidebar.jsx` | Create new sidebar component |
| `src/components/placeholder-page.jsx` | Create placeholder for future features |
| `tailwind.config.js` | Add sidebar width variables if needed |

## Dependencies

None - this is a frontend-only change using existing backend APIs.

## Out of Scope

- Backend for Role/User RBAC
- Backend for Project management
- Backend for API Key storage
- Grafana integration (just external links)
