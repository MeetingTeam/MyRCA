---
phase: 1
title: "Implement Roles Users Page"
status: completed
priority: P1
effort: "30m"
dependencies: []
---

# Phase 1: Implement Roles Users Page

## Overview

Create `roles-users-page.jsx` component with form to add/manage users and roles, stored in localStorage.

## Requirements

- Form to add user with email and role selection
- List of users with their assigned roles
- Edit role functionality
- Delete user functionality
- Current logged-in user shown with badge
- Dark theme matching existing dashboard

## Related Code Files

- Create: `src/components/roles-users-page.jsx`
- Modify: `src/App.jsx` (update route)

## Implementation Steps

### Step 1: Create Roles Users Page Component

Create `src/components/roles-users-page.jsx`:

```jsx
import { useState, useEffect } from 'react'
import { Users, Plus, Trash2, Shield, Edit2, X, Check } from 'lucide-react'
import { useAuth } from '../auth-context'

const ROLES = [
  { id: 'admin', name: 'Admin', description: 'Full access to all features', color: 'red' },
  { id: 'editor', name: 'Editor', description: 'Can view and modify incidents', color: 'yellow' },
  { id: 'viewer', name: 'Viewer', description: 'Read-only access', color: 'blue' },
]

export default function RolesUsersPage() {
  const { user: currentUser } = useAuth()
  const [users, setUsers] = useState([])
  const [showForm, setShowForm] = useState(false)
  const [formData, setFormData] = useState({ email: '', role: 'viewer' })
  const [editingUser, setEditingUser] = useState(null)

  // Default admin user
  const DEFAULT_ADMIN = { email: 'phunghung146@gmail.com', role: 'admin', name: 'Phung Hung' }

  // Load from localStorage, initialize with default admin if empty
  useEffect(() => {
    const saved = localStorage.getItem('rca-users')
    if (saved) {
      try {
        setUsers(JSON.parse(saved))
      } catch {
        localStorage.removeItem('rca-users')
      }
    } else {
      // Initialize with default admin user
      const initial = [DEFAULT_ADMIN]
      setUsers(initial)
      localStorage.setItem('rca-users', JSON.stringify(initial))
    }
  }, [])

  const saveUser = () => {
    if (!formData.email || !formData.role) return
    if (users.some(u => u.email === formData.email)) {
      alert('User already exists')
      return
    }
    const newUsers = [...users, { email: formData.email, role: formData.role, name: '' }]
    setUsers(newUsers)
    localStorage.setItem('rca-users', JSON.stringify(newUsers))
    setShowForm(false)
    setFormData({ email: '', role: 'viewer' })
  }

  const updateRole = (email, newRole) => {
    const newUsers = users.map(u => u.email === email ? { ...u, role: newRole } : u)
    setUsers(newUsers)
    localStorage.setItem('rca-users', JSON.stringify(newUsers))
    setEditingUser(null)
  }

  const deleteUser = (email) => {
    if (email === currentUser?.email) {
      alert('Cannot delete yourself')
      return
    }
    const newUsers = users.filter(u => u.email !== email)
    setUsers(newUsers)
    localStorage.setItem('rca-users', JSON.stringify(newUsers))
  }

  const getRoleColor = (roleId) => {
    const role = ROLES.find(r => r.id === roleId)
    if (role?.color === 'red') return 'bg-red-600'
    if (role?.color === 'yellow') return 'bg-yellow-600'
    return 'bg-blue-600'
  }

  return (
    <div>
      {/* Header with Add button */}
      {/* Role legend cards */}
      {/* Add User Modal */}
      {/* Users table/list */}
    </div>
  )
}
```

### Step 2: Update App.jsx Route

Replace PlaceholderPage with RolesUsersPage:

```jsx
import RolesUsersPage from './components/roles-users-page'

// In Routes:
<Route path="/users" element={<RolesUsersPage />} />
```

## Success Criteria

- [ ] Add user form works (email, role selection)
- [ ] Users persisted in localStorage
- [ ] Users displayed in a table/list format
- [ ] Edit role functionality works
- [ ] Delete user functionality works (cannot delete self)
- [ ] Current user shown with "You" badge
- [ ] Dark theme matches existing dashboard
