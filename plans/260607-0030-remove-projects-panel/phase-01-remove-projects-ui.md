---
phase: 1
title: "Remove Projects UI"
status: completed
priority: P1
effort: "10m"
dependencies: []
---

# Phase 1: Remove Projects UI

## Overview

Remove Projects panel from sidebar navigation and routing.

## Related Code Files

- Modify: `src/components/sidebar.jsx`
- Modify: `src/App.jsx`

## Implementation Steps

### Step 1: Update sidebar.jsx

Remove Projects from menuItems array and FolderKanban import:

```jsx
// REMOVE this import:
// FolderKanban,

// REMOVE this menu item:
// { path: '/projects', icon: FolderKanban, label: 'Projects' },
```

### Step 2: Update App.jsx

Remove /projects route:

```jsx
// REMOVE this route:
// <Route path="/projects" element={
//   <PlaceholderPage
//     title="Projects"
//     description="Organize and manage multiple applications..."
//   />
// } />
```

### Step 3: Build and Deploy

```bash
cd D:/KLTN/MyRCA/trace_rca_algo/rca-dashboard
npm run build
docker build --build-arg VITE_GOOGLE_CLIENT_ID=309305824654-tr8sc9p0jjbmlmvsnv19kdun2n4hugjd.apps.googleusercontent.com -t asdads6495/myrca-rca-dashboard:auth .
docker push asdads6495/myrca-rca-dashboard:auth
kubectl rollout restart deployment/rca-dashboard -n rca
```

## Success Criteria

- [x] Projects removed from sidebar menu
- [x] /projects route removed
- [x] Build succeeds
- [x] Dashboard loads without Projects panel
- [x] Other features (Dashboard, Users, Grafana, API Keys) unaffected
