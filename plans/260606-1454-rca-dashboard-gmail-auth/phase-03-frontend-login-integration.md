---
phase: 3
title: "Frontend Login Integration"
status: completed
priority: P1
effort: "3h"
dependencies: [2]
---

# Phase 3: Frontend Login Integration

## Overview

Create complete login page with username/password form (placeholder) and Gmail login button. Manage auth state, protect routes.

## Requirements

- Functional: Complete login UI, Google login working, username/password form disabled
- Non-functional: Professional UI, smooth UX, auto-redirect on login/logout

## Login Page Design

```
┌────────────────────────────────────────────────────────────┐
│                                                            │
│                    🔐 MyRCA Dashboard                      │
│               Root Cause Analysis System                   │
│                                                            │
│  ┌──────────────────────────────────────────────────────┐  │
│  │                                                      │  │
│  │   Email / Username                                   │  │
│  │   ┌──────────────────────────────────────────────┐   │  │
│  │   │ user@example.com                             │   │  │
│  │   └──────────────────────────────────────────────┘   │  │
│  │                                                      │  │
│  │   Password                                           │  │
│  │   ┌──────────────────────────────────────────────┐   │  │
│  │   │ ••••••••                                     │   │  │
│  │   └──────────────────────────────────────────────┘   │  │
│  │                                                      │  │
│  │   ┌──────────────────────────────────────────────┐   │  │
│  │   │           Sign In (disabled)                 │   │  │
│  │   └──────────────────────────────────────────────┘   │  │
│  │                                                      │  │
│  │   ─────────────── OR ───────────────                 │  │
│  │                                                      │  │
│  │   ┌──────────────────────────────────────────────┐   │  │
│  │   │   🔵 Continue with Google                    │   │  │
│  │   └──────────────────────────────────────────────┘   │  │
│  │                                                      │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                            │
│          "Username/password coming soon"                   │
│                                                            │
└────────────────────────────────────────────────────────────┘
```

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  App.jsx                                                       │
│  └── AuthProvider (context)                                    │
│        ├── user: { email, name, picture } | null               │
│        ├── token: string | null                                │
│        ├── loginWithGoogle(googleToken) → POST /api/auth/google│
│        ├── loginWithPassword(email, pass) → TODO (disabled)    │
│        ├── logout() → clear state + localStorage               │
│        └── isAuthenticated: boolean                            │
│                                                                  │
│  Routes:                                                        │
│  ├── /login          ← LoginPage (public)                       │
│  ├── /               ← IncidentList (protected)                │
│  └── /incidents/:id  ← IncidentDetail (protected)              │
└─────────────────────────────────────────────────────────────────┘
```

## Related Code Files

- Modify: `rca-dashboard/src/App.jsx`
- Modify: `rca-dashboard/src/api.js`
- Create: `rca-dashboard/src/auth-context.jsx`
- Create: `rca-dashboard/src/components/login-page.jsx`
- Modify: `rca-dashboard/package.json`

## Implementation Steps

### Step 1: Install Dependencies

```bash
cd trace_rca_algo/rca-dashboard
npm install @react-oauth/google
```

### Step 2: Create auth-context.jsx

```jsx
import { createContext, useContext, useState, useEffect } from 'react'
import { googleLogin } from './api'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [token, setToken] = useState(() => localStorage.getItem('auth_token'))
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (token) {
      fetch(`${import.meta.env.VITE_API_URL || ''}/api/auth/me`, {
        headers: { Authorization: `Bearer ${token}` },
      })
        .then(res => res.ok ? res.json() : Promise.reject())
        .then(setUser)
        .catch(() => {
          localStorage.removeItem('auth_token')
          setToken(null)
        })
        .finally(() => setLoading(false))
    } else {
      setLoading(false)
    }
  }, [token])

  const loginWithGoogle = async (googleIdToken) => {
    const data = await googleLogin(googleIdToken)
    localStorage.setItem('auth_token', data.access_token)
    setToken(data.access_token)
    setUser(data.user)
    return data
  }

  // Placeholder for future username/password login
  const loginWithPassword = async (email, password) => {
    throw new Error('Username/password login not implemented yet')
  }

  const logout = () => {
    localStorage.removeItem('auth_token')
    setToken(null)
    setUser(null)
  }

  return (
    <AuthContext.Provider value={{ 
      user, token, loginWithGoogle, loginWithPassword, 
      logout, loading, isAuthenticated: !!user 
    }}>
      {children}
    </AuthContext.Provider>
  )
}

export const useAuth = () => useContext(AuthContext)
```

### Step 3: Update api.js

```js
const API_BASE = import.meta.env.VITE_API_URL || ''

function getAuthHeaders() {
  const token = localStorage.getItem('auth_token')
  return token ? { Authorization: `Bearer ${token}` } : {}
}

export async function googleLogin(idToken) {
  const res = await fetch(`${API_BASE}/api/auth/google`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id_token: idToken }),
  })
  if (!res.ok) throw new Error('Login failed')
  return res.json()
}

export async function fetchApplications() {
  const res = await fetch(`${API_BASE}/api/applications`, {
    headers: getAuthHeaders(),
  })
  if (res.status === 401) {
    localStorage.removeItem('auth_token')
    window.location.href = '/login'
    throw new Error('Unauthorized')
  }
  if (!res.ok) throw new Error('Failed to fetch applications')
  return res.json()
}

// Update fetchIncidents and fetchIncident similarly with getAuthHeaders()
```

### Step 4: Create login-page.jsx (Full Design)

```jsx
import { useState } from 'react'
import { GoogleLogin } from '@react-oauth/google'
import { useAuth } from '../auth-context'
import { useNavigate } from 'react-router-dom'
import { useEffect } from 'react'

export default function LoginPage() {
  const { loginWithGoogle, isAuthenticated } = useAuth()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    if (isAuthenticated) navigate('/')
  }, [isAuthenticated, navigate])

  const handleGoogleSuccess = async (response) => {
    try {
      setError('')
      await loginWithGoogle(response.credential)
      navigate('/')
    } catch (e) {
      setError('Google login failed. Please try again.')
    }
  }

  const handlePasswordSubmit = (e) => {
    e.preventDefault()
    // Disabled for now - show message
    setError('Username/password login coming soon. Please use Google Sign-In.')
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-gray-900 via-gray-800 to-gray-900">
      <div className="w-full max-w-md">
        {/* Logo & Title */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-16 h-16 bg-blue-600 rounded-full mb-4">
            <svg className="w-8 h-8 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
            </svg>
          </div>
          <h1 className="text-3xl font-bold text-white">MyRCA Dashboard</h1>
          <p className="text-gray-400 mt-2">Root Cause Analysis System</p>
        </div>

        {/* Login Card */}
        <div className="bg-gray-800 rounded-xl shadow-2xl p-8 border border-gray-700">
          {/* Error Message */}
          {error && (
            <div className="mb-4 p-3 bg-red-900/50 border border-red-700 rounded-lg text-red-300 text-sm">
              {error}
            </div>
          )}

          {/* Username/Password Form (Disabled) */}
          <form onSubmit={handlePasswordSubmit} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-1">
                Email / Username
              </label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="user@example.com"
                disabled
                className="w-full px-4 py-3 bg-gray-700 border border-gray-600 rounded-lg text-gray-400 placeholder-gray-500 cursor-not-allowed opacity-60"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-1">
                Password
              </label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                disabled
                className="w-full px-4 py-3 bg-gray-700 border border-gray-600 rounded-lg text-gray-400 placeholder-gray-500 cursor-not-allowed opacity-60"
              />
            </div>
            <button
              type="submit"
              disabled
              className="w-full py-3 bg-gray-600 text-gray-400 rounded-lg font-medium cursor-not-allowed opacity-60"
            >
              Sign In
            </button>
          </form>

          {/* Divider */}
          <div className="flex items-center my-6">
            <div className="flex-1 border-t border-gray-600"></div>
            <span className="px-4 text-sm text-gray-400">OR</span>
            <div className="flex-1 border-t border-gray-600"></div>
          </div>

          {/* Google Login Button */}
          <div className="flex justify-center">
            <GoogleLogin
              onSuccess={handleGoogleSuccess}
              onError={() => setError('Google login failed')}
              theme="filled_black"
              size="large"
              width="100%"
              text="continue_with"
            />
          </div>

          {/* Coming Soon Note */}
          <p className="text-center text-xs text-gray-500 mt-6">
            Username/password authentication coming soon
          </p>
        </div>

        {/* Footer */}
        <p className="text-center text-gray-500 text-xs mt-6">
          © 2026 MyRCA. Secure root cause analysis.
        </p>
      </div>
    </div>
  )
}
```

### Step 5: Update App.jsx

```jsx
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { GoogleOAuthProvider } from '@react-oauth/google'
import { AuthProvider, useAuth } from './auth-context'
import LoginPage from './components/login-page'
import IncidentList from './components/incident-list'
import IncidentDetail from './components/incident-detail'

const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID

function ProtectedRoute({ children }) {
  const { isAuthenticated, loading } = useAuth()
  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-900">
        <div className="text-gray-400">Loading...</div>
      </div>
    )
  }
  if (!isAuthenticated) return <Navigate to="/login" replace />
  return children
}

function Dashboard() {
  // ... existing dashboard with navbar + routes
}

export default function App() {
  return (
    <GoogleOAuthProvider clientId={GOOGLE_CLIENT_ID}>
      <AuthProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/*" element={
              <ProtectedRoute>
                <Dashboard />
              </ProtectedRoute>
            } />
          </Routes>
        </BrowserRouter>
      </AuthProvider>
    </GoogleOAuthProvider>
  )
}
```

### Step 6: Add User Menu in Navbar

Update Dashboard navbar to show user info:
```jsx
const { user, logout } = useAuth()

// In nav section:
<div className="flex items-center gap-4">
  {user && (
    <>
      <img 
        src={user.picture} 
        alt={user.name} 
        className="w-8 h-8 rounded-full border-2 border-gray-600" 
      />
      <span className="text-sm text-gray-300">{user.name}</span>
      <button 
        onClick={logout}
        className="px-3 py-1 text-xs text-gray-400 hover:text-white hover:bg-gray-700 rounded"
      >
        Logout
      </button>
    </>
  )}
</div>
```

### Step 7: Environment Variables

Create `.env.development`:
```
VITE_GOOGLE_CLIENT_ID=xxx.apps.googleusercontent.com
VITE_API_URL=http://localhost:8082
```

## Success Criteria

- [x] Login page shows username/password form (disabled)
- [x] Login page shows "OR" divider
- [x] Google Sign-In button works
- [x] "Coming soon" message displayed for password login
- [x] Successful Google login redirects to /
- [x] Protected routes redirect to /login if not authenticated
- [x] User avatar and name show in navbar
- [x] Logout clears state and redirects to /login

## Risk Assessment

| Risk | Mitigation |
|------|------------|
| Token in localStorage XSS | Use httpOnly cookies (future) |
| Google popup blocked | Show error message |
| UI inconsistency | Use Tailwind for consistent styling |

## Future Enhancements (Phase 5+)

- Enable username/password authentication
- Add "Forgot password" flow
- Add "Remember me" checkbox
- Add 2FA support
