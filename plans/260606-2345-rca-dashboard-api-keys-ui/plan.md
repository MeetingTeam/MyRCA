---
title: "RCA Dashboard API Keys UI"
description: "Frontend-only UI for managing LLM API keys with localStorage persistence"
status: completed
priority: P1
branch: "main"
tags: [frontend, ui, api-keys]
blockedBy: []
blocks: []
created: "2026-06-06T16:42:59.782Z"
createdBy: "ck:plan"
source: skill
---

# RCA Dashboard API Keys UI

## Overview

Replace the placeholder API Keys page with a functional UI for managing LLM API keys. Frontend-only implementation with localStorage persistence (no backend).

## Features

| Feature | Description |
|---------|-------------|
| Add API Key | Form to add keys for Claude, OpenAI, Google AI |
| List Keys | Show configured providers with masked keys |
| Delete Key | Remove configured keys |
| Select Model | Choose active LLM model for RCA reasoning |
| Persistence | localStorage (no backend required) |

## Supported Providers

| Provider | Models |
|----------|--------|
| Anthropic | **Claude Sonnet 4.6** (default), Claude Opus 4.5, Claude 3.5 Sonnet |
| OpenAI | GPT-4o, GPT-4 Turbo, o1-preview |
| Google | Gemini 2.0 Flash, Gemini Pro |

**Default Active Model:** `anthropic:claude-sonnet-4-6`

## Phases

| Phase | Name | Status | Effort |
|-------|------|--------|--------|
| 1 | [Implement API Keys Page](./phase-01-implement-api-keys-page.md) | Pending | 30m |
| 2 | [Deploy and Verify](./phase-02-deploy-and-verify.md) | Pending | 10m |

## Files to Modify

| File | Change |
|------|--------|
| `src/components/api-keys-page.jsx` | Create new component |
| `src/App.jsx` | Update route to use new component |

## Dependencies

None - frontend-only with localStorage persistence.
