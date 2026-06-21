---
phase: 1
title: "Implement Sidebar Layout"
status: completed
priority: P1
effort: "30m"
dependencies: []
---

# Phase 1: Implement Sidebar Layout

## Overview

Create the sidebar component and refactor App.jsx to use a two-column layout with collapsible sidebar.

## Requirements

- Collapsible sidebar (toggle button)
- Fixed width when expanded (~240px), icon-only when collapsed (~64px)
- Dark theme matching existing dashboard
- Menu items with icons and labels
- Active state indicator for current route

## Architecture

```
┌──────────────────────────────────────────────┐
│ Header (existing nav bar)                    │
├─────────┬────────────────────────────────────┤
│         │                                    │
│ Sidebar │  Main Content Area                 │
│  (new)  │  (existing routes)                 │
│         │                                    │
│         │                                    │
└─────────┴────────────────────────────────────┘
```

## Related Code Files

- Create: `src/components/sidebar.jsx`
- Modify: `src/App.jsx`

## Implementation Steps

### Step 1: Create Sidebar Component

Create `src/components/sidebar.jsx`:

```jsx
import { NavLink } from 'react-router-dom'
import { 
  LayoutDashboard, 
  Users, 
  FolderKanban, 
  BarChart3, 
  Key,
  ChevronLeft,
  ChevronRight
} from 'lucide-react'

const menuItems = [
  { path: '/', icon: LayoutDashboard, label: 'Dashboard' },
  { path: '/users', icon: Users, label: 'Roles & Users' },
  { path: '/projects', icon: FolderKanban, label: 'Projects' },
  { path: '/grafana', icon: BarChart3, label: 'Grafana' },
  { path: '/api-keys', icon: Key, label: 'API Keys' },
]

export default function Sidebar({ collapsed, onToggle }) {
  return (
    <aside className={`bg-dark-800 border-r border-gray-700 flex flex-col transition-all duration-300 ${
      collapsed ? 'w-16' : 'w-60'
    }`}>
      {/* Toggle button */}
      <button onClick={onToggle} className="p-4 hover:bg-dark-700">
        {collapsed ? <ChevronRight /> : <ChevronLeft />}
      </button>
      
      {/* Menu items */}
      <nav className="flex-1 py-4">
        {menuItems.map(item => (
          <NavLink
            key={item.path}
            to={item.path}
            className={({ isActive }) => `
              flex items-center gap-3 px-4 py-3 
              ${isActive ? 'bg-blue-600/20 text-blue-400 border-r-2 border-blue-400' : 'text-gray-400 hover:bg-dark-700 hover:text-white'}
            `}
          >
            <item.icon size={20} />
            {!collapsed && <span>{item.label}</span>}
          </NavLink>
        ))}
      </nav>
    </aside>
  )
}
```

### Step 2: Install lucide-react

```bash
cd trace_rca_algo/rca-dashboard
npm install lucide-react
```

### Step 3: Refactor App.jsx Layout

Update `Dashboard` component in App.jsx to include sidebar:

```jsx
function Dashboard() {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  // ... existing state ...

  return (
    <AppFilterContext.Provider value={...}>
      <div className="min-h-screen flex flex-col">
        {/* Header */}
        <nav className="bg-dark-800 border-b border-gray-700 px-6 py-3">
          {/* ... existing header ... */}
        </nav>

        {/* Body with sidebar */}
        <div className="flex flex-1">
          <Sidebar 
            collapsed={sidebarCollapsed} 
            onToggle={() => setSidebarCollapsed(!sidebarCollapsed)} 
          />
          <main className="flex-1 p-6 overflow-auto">
            <Routes>
              {/* ... existing routes ... */}
            </Routes>
          </main>
        </div>
      </div>
    </AppFilterContext.Provider>
  )
}
```

## Success Criteria

- [ ] Sidebar component created with all 5 menu items
- [ ] Sidebar toggles between expanded/collapsed
- [ ] Active route highlighted
- [ ] Layout responsive and matches dark theme
- [ ] lucide-react icons render correctly
