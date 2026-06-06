---
phase: 1
title: "Implement MLOps Links"
status: completed
priority: P1
effort: "10m"
dependencies: []
---

# Phase 1: Implement MLOps Links

## Overview

Create MLOps links page following grafana-links.jsx pattern. Add menu item and route.

## Related Code Files

- Create: `src/components/mlops-links.jsx`
- Modify: `src/components/sidebar.jsx`
- Modify: `src/App.jsx`

## Implementation Steps

### Step 1: Create mlops-links.jsx

Follow grafana-links.jsx pattern with these tools:

```jsx
import { ExternalLink, BarChart2, Wind, FlaskConical } from 'lucide-react'

const tools = [
  {
    id: 'evidently',
    name: 'Evidently',
    description: 'ML model monitoring and data drift detection',
    icon: BarChart2,
    url: 'http://34.226.226.116:30800/',
  },
  {
    id: 'airflow',
    name: 'Airflow',
    description: 'Workflow orchestration and DAG management',
    icon: Wind,
    url: 'http://34.226.226.116:30380/',
  },
  {
    id: 'mlflow',
    name: 'MLflow',
    description: 'ML experiment tracking and model registry',
    icon: FlaskConical,
    url: 'http://34.226.226.116:30002/',
  },
]

export default function MlopsLinks() {
  return (
    <div>
      <h1 className="text-2xl font-bold mb-6">MLOps Tools</h1>
      <p className="text-gray-400 mb-8">
        Access MLOps tools for model monitoring, workflow orchestration, and experiment tracking.
      </p>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {tools.map(tool => (
          <a
            key={tool.id}
            href={tool.url}
            target="_blank"
            rel="noopener noreferrer"
            className="bg-dark-800 border border-gray-700 rounded-lg p-6 hover:border-blue-500 hover:bg-dark-700 transition group"
          >
            <div className="flex items-center gap-3 mb-3">
              <tool.icon size={24} className="text-blue-400" />
              <h2 className="text-lg font-semibold">{tool.name}</h2>
              <ExternalLink size={16} className="text-gray-500 group-hover:text-blue-400 ml-auto" />
            </div>
            <p className="text-sm text-gray-400">{tool.description}</p>
          </a>
        ))}
      </div>
    </div>
  )
}
```

### Step 2: Update sidebar.jsx

Add MLOps menu item with Cpu icon:

```jsx
// Add import:
import { Cpu } from 'lucide-react'

// Add to menuItems after Grafana:
{ path: '/mlops', icon: Cpu, label: 'MLOps' },
```

### Step 3: Update App.jsx

Add route:

```jsx
// Add import:
import MlopsLinks from './components/mlops-links'

// Add route after /grafana:
<Route path="/mlops" element={<MlopsLinks />} />
```

### Step 4: Build and Deploy

```bash
cd D:/KLTN/MyRCA/trace_rca_algo/rca-dashboard
npm run build
docker build --build-arg VITE_GOOGLE_CLIENT_ID=309305824654-tr8sc9p0jjbmlmvsnv19kdun2n4hugjd.apps.googleusercontent.com -t asdads6495/myrca-rca-dashboard:auth .
docker push asdads6495/myrca-rca-dashboard:auth
kubectl rollout restart deployment/rca-dashboard -n rca
```

## Success Criteria

- [x] MLOps links page created with 3 tool cards
- [x] MLOps menu item visible in sidebar
- [x] /mlops route works
- [x] External links open in new tabs
- [x] Build succeeds
- [x] Deployed to K8s
