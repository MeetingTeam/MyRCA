---
title: "Remove Projects Panel"
description: "Remove unused Projects panel from RCA Dashboard per YAGNI principle"
status: completed
priority: P1
branch: "main"
tags: [frontend, cleanup]
blockedBy: []
blocks: []
created: "2026-06-06T17:33:07.508Z"
createdBy: "ck:plan"
source: skill
---

# Remove Projects Panel

## Overview

Remove the Projects panel from RCA Dashboard. The feature is redundant with existing app multi-select functionality and adds no real value as frontend-only localStorage wrapper.

## Rationale

- Applications multi-select already exists in sidebar
- Projects would just be "saved filter presets" without backend
- Follows YAGNI principle - remove unused/unnecessary features

## Phases

| Phase | Name | Status | Effort |
|-------|------|--------|--------|
| 1 | [Remove Projects UI](./phase-01-remove-projects-ui.md) | Completed | 10m |

## Files to Modify

| File | Change |
|------|--------|
| `src/components/sidebar.jsx` | Remove Projects menu item |
| `src/App.jsx` | Remove /projects route |

## Dependencies

None.
