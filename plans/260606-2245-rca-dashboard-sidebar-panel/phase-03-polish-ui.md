---
phase: 3
title: "Polish UI"
status: completed
priority: P2
effort: "20m"
dependencies: [1, 2]
---

# Phase 3: Polish UI

## Overview

Final polish: responsive behavior, transitions, tooltips for collapsed state, and move app filter from header to Dashboard page.

## Requirements

- Smooth collapse/expand animation
- Tooltips when sidebar collapsed (show label on hover)
- Move app filter chips from header to Dashboard page only
- Persist sidebar state in localStorage
- Mobile responsive (auto-collapse on small screens)

## Related Code Files

- Modify: `src/components/sidebar.jsx`
- Modify: `src/components/incident-list.jsx` (move app filter here)
- Modify: `src/App.jsx` (simplify header)

## Implementation Steps

### Step 1: Add Tooltips and Persist State

Update `src/components/sidebar.jsx`:

```jsx
import { useState, useEffect } from 'react'

export default function Sidebar({ collapsed, onToggle }) {
  // Persist state
  useEffect(() => {
    localStorage.setItem('sidebar-collapsed', collapsed)
  }, [collapsed])

  return (
    <aside className={`... transition-all duration-300 ease-in-out`}>
      {/* Menu items with tooltip */}
      {menuItems.map(item => (
        <NavLink
          key={item.path}
          to={item.path}
          title={collapsed ? item.label : undefined}  // Tooltip when collapsed
          className={...}
        >
          <item.icon size={20} className="flex-shrink-0" />
          <span className={`whitespace-nowrap overflow-hidden transition-all duration-300 ${
            collapsed ? 'w-0 opacity-0' : 'w-auto opacity-100'
          }`}>
            {item.label}
          </span>
        </NavLink>
      ))}
    </aside>
  )
}
```

### Step 2: Initialize Collapsed State from localStorage

In App.jsx:

```jsx
const [sidebarCollapsed, setSidebarCollapsed] = useState(() => {
  const saved = localStorage.getItem('sidebar-collapsed')
  return saved === 'true'
})
```

### Step 3: Move App Filter to IncidentList

Move the app filter chips from the header to `incident-list.jsx` so it only appears on the Dashboard page.

```jsx
// In incident-list.jsx, add at top:
<div className="bg-dark-800 rounded-lg border border-gray-700 p-4 mb-4">
  <div className="flex items-center gap-2 flex-wrap">
    <span className="text-xs text-gray-500 uppercase">Filter by App:</span>
    {/* ... existing app filter chips ... */}
  </div>
</div>
```

### Step 4: Simplify Header

Remove app filter from header, keep only:
- Logo/title
- User menu

### Step 5: Add Mobile Responsiveness

```jsx
// Auto-collapse on mobile
useEffect(() => {
  const handleResize = () => {
    if (window.innerWidth < 768) {
      setSidebarCollapsed(true)
    }
  }
  window.addEventListener('resize', handleResize)
  handleResize() // Check on mount
  return () => window.removeEventListener('resize', handleResize)
}, [])
```

## Success Criteria

- [ ] Sidebar state persists across page reloads
- [ ] Tooltips appear on hover when sidebar collapsed
- [ ] Smooth 300ms transition animation
- [ ] App filter moved to Dashboard page only
- [ ] Header simplified (logo + user menu only)
- [ ] Auto-collapse on mobile (< 768px)

## Testing

1. Toggle sidebar - should animate smoothly
2. Refresh page - sidebar state should persist
3. Hover collapsed menu items - tooltip should show
4. Navigate to Users/Projects - no app filter visible
5. Navigate to Dashboard - app filter visible
6. Resize to mobile width - sidebar auto-collapses
