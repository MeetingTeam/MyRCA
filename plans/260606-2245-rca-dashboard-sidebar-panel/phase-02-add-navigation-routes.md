---
phase: 2
title: "Add Navigation Routes"
status: completed
priority: P1
effort: "30m"
dependencies: [1]
---

# Phase 2: Add Navigation Routes

## Overview

Add routes for each sidebar menu item. Dashboard uses existing components; others get placeholder pages.

## Requirements

- Dashboard route: existing IncidentList/IncidentDetail
- Placeholder pages for: Users, Projects, API Keys
- Grafana page with external links to Loki, ClickHouse, Tempo dashboards

## Related Code Files

- Create: `src/components/placeholder-page.jsx`
- Create: `src/components/grafana-links.jsx`
- Modify: `src/App.jsx` (add routes)

## Implementation Steps

### Step 1: Create Placeholder Page Component

Create `src/components/placeholder-page.jsx`:

```jsx
import { Construction } from 'lucide-react'

export default function PlaceholderPage({ title, description }) {
  return (
    <div className="flex flex-col items-center justify-center min-h-[60vh] text-center">
      <Construction size={64} className="text-gray-600 mb-4" />
      <h1 className="text-2xl font-bold text-gray-300 mb-2">{title}</h1>
      <p className="text-gray-500 max-w-md">{description}</p>
      <span className="mt-4 px-3 py-1 bg-yellow-900/30 text-yellow-500 rounded-full text-sm">
        Coming Soon
      </span>
    </div>
  )
}
```

### Step 2: Create Grafana Links Page

Create `src/components/grafana-links.jsx`:

```jsx
import { ExternalLink, Database, FileText, Activity } from 'lucide-react'

const GRAFANA_BASE_URL = import.meta.env.VITE_GRAFANA_URL || 'http://grafana.local'

const dashboards = [
  {
    id: 'loki',
    name: 'Loki Logs',
    description: 'Application logs and error tracking',
    icon: FileText,
    path: '/d/loki-logs',
  },
  {
    id: 'clickhouse',
    name: 'ClickHouse Metrics',
    description: 'Database performance and query analytics',
    icon: Database,
    path: '/d/clickhouse-metrics',
  },
  {
    id: 'tempo',
    name: 'Tempo Traces',
    description: 'Distributed tracing and latency analysis',
    icon: Activity,
    path: '/d/tempo-traces',
  },
]

export default function GrafanaLinks() {
  return (
    <div>
      <h1 className="text-2xl font-bold mb-6">Grafana Dashboards</h1>
      <p className="text-gray-400 mb-8">
        Access observability dashboards for logs, metrics, and traces.
      </p>
      
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {dashboards.map(dashboard => (
          <a
            key={dashboard.id}
            href={`${GRAFANA_BASE_URL}${dashboard.path}`}
            target="_blank"
            rel="noopener noreferrer"
            className="bg-dark-800 border border-gray-700 rounded-lg p-6 hover:border-blue-500 hover:bg-dark-700 transition group"
          >
            <div className="flex items-center gap-3 mb-3">
              <dashboard.icon size={24} className="text-blue-400" />
              <h2 className="text-lg font-semibold">{dashboard.name}</h2>
              <ExternalLink size={16} className="text-gray-500 group-hover:text-blue-400 ml-auto" />
            </div>
            <p className="text-sm text-gray-400">{dashboard.description}</p>
          </a>
        ))}
      </div>
    </div>
  )
}
```

### Step 3: Add Routes to App.jsx

Update Routes in Dashboard component:

```jsx
import PlaceholderPage from './components/placeholder-page'
import GrafanaLinks from './components/grafana-links'

// Inside Dashboard component's Routes:
<Routes>
  {/* Dashboard - existing */}
  <Route path="/" element={<IncidentList />} />
  <Route path="/incidents/:id" element={<IncidentDetail />} />
  
  {/* Roles & Users - placeholder */}
  <Route path="/users" element={
    <PlaceholderPage 
      title="Roles & Users" 
      description="Manage user roles and permissions for RBAC access control."
    />
  } />
  
  {/* Projects - placeholder */}
  <Route path="/projects" element={
    <PlaceholderPage 
      title="Projects" 
      description="Organize and manage multiple applications and their configurations."
    />
  } />
  
  {/* Grafana - external links */}
  <Route path="/grafana" element={<GrafanaLinks />} />
  
  {/* API Keys - placeholder */}
  <Route path="/api-keys" element={
    <PlaceholderPage 
      title="API Keys" 
      description="Configure API keys for LLM reasoning models (Claude, GPT, etc.)."
    />
  } />
</Routes>
```

### Step 4: Add Environment Variable

Add to `.env.example`:
```
VITE_GRAFANA_URL=http://grafana.monitoring.svc.cluster.local:3000
```

## Success Criteria

- [ ] All 5 routes work correctly
- [ ] Dashboard shows incident list (existing functionality)
- [ ] Placeholder pages display for Users, Projects, API Keys
- [ ] Grafana page shows 3 dashboard links (Loki, ClickHouse, Tempo)
- [ ] External links open in new tab
