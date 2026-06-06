import { useState, useEffect, createContext, useContext } from 'react'
import { Routes, Route, Link, Navigate, useSearchParams } from 'react-router-dom'
import { GoogleOAuthProvider } from '@react-oauth/google'
import { AuthProvider, useAuth } from './auth-context'
import IncidentList from './components/incident-list'
import IncidentDetail from './components/incident-detail'
import LoginPage from './components/login-page'
import { fetchApplications } from './api'

const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID

const AppFilterContext = createContext({
  applications: [],
  selectedApps: [],
  setSelectedApps: () => {},
  loading: true,
  error: null,
})

export const useAppFilter = () => useContext(AppFilterContext)

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

function UserMenu() {
  const { user, logout } = useAuth()
  if (!user) return null
  return (
    <div className="flex items-center gap-3">
      {user.picture && (
        <img
          src={user.picture}
          alt={user.name}
          className="w-8 h-8 rounded-full border-2 border-gray-600"
        />
      )}
      <span className="text-sm text-gray-300">{user.name || user.email}</span>
      <button
        onClick={logout}
        className="px-3 py-1 text-xs text-gray-400 hover:text-white hover:bg-gray-700 rounded transition"
      >
        Logout
      </button>
    </div>
  )
}

function Dashboard() {
  const [applications, setApplications] = useState([])
  const [selectedApps, setSelectedApps] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [searchParams, setSearchParams] = useSearchParams()

  // Load applications on mount
  useEffect(() => {
    fetchApplications()
      .then(apps => {
        // Ensure apps is an array of strings
        const appList = Array.isArray(apps) ? apps.filter(a => typeof a === 'string') : []
        setApplications(appList)
        // Restore selected apps from URL
        const urlApps = searchParams.get('apps')
        if (urlApps) {
          const parsed = urlApps.split(',').filter(a => a && appList.includes(a))
          setSelectedApps(parsed)
        }
      })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [searchParams])

  // Sync selected apps to URL
  useEffect(() => {
    if (selectedApps.length > 0) {
      searchParams.set('apps', selectedApps.join(','))
    } else {
      searchParams.delete('apps')
    }
    setSearchParams(searchParams, { replace: true })
  }, [selectedApps])

  const toggleApp = (appId) => {
    setSelectedApps(prev =>
      prev.includes(appId)
        ? prev.filter(a => a !== appId)
        : [...prev, appId]
    )
  }

  const clearApps = () => setSelectedApps([])

  return (
    <AppFilterContext.Provider value={{ applications, selectedApps, setSelectedApps, loading, error }}>
      <div className="min-h-screen">
        <nav className="bg-dark-800 border-b border-gray-700 px-6 py-3">
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-4">
              <Link to="/" className="text-lg font-bold text-white hover:text-blue-400">
                MyRCA Dashboard
              </Link>
              <span className="text-gray-500 text-sm">Root Cause Analysis</span>
            </div>
            <UserMenu />
          </div>

          {/* App filter chips */}
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-xs text-gray-500 uppercase">Apps:</span>
            {loading && <span className="text-xs text-gray-400">Loading...</span>}
            {error && <span className="text-xs text-red-400">Error loading apps</span>}
            {!loading && !error && applications.length === 0 && (
              <span className="text-xs text-gray-400">No applications found</span>
            )}
            {applications.map(appId => (
              <button
                key={appId}
                onClick={() => toggleApp(appId)}
                className={`px-3 py-1 rounded-full text-xs font-medium transition ${
                  selectedApps.includes(appId)
                    ? 'bg-blue-600 text-white'
                    : 'bg-dark-900 text-gray-400 hover:text-white hover:bg-dark-700'
                }`}
              >
                {appId}
              </button>
            ))}
            {selectedApps.length > 0 && (
              <button
                onClick={clearApps}
                className="text-xs text-gray-400 hover:text-white ml-2"
              >
                Clear
              </button>
            )}
          </div>
        </nav>

        <main className="max-w-7xl mx-auto px-6 py-6">
          <Routes>
            <Route path="/" element={<IncidentList />} />
            <Route path="/incidents/:id" element={<IncidentDetail />} />
          </Routes>
        </main>
      </div>
    </AppFilterContext.Provider>
  )
}

export default function App() {
  return (
    <GoogleOAuthProvider clientId={GOOGLE_CLIENT_ID}>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/*" element={
            <ProtectedRoute>
              <Dashboard />
            </ProtectedRoute>
          } />
        </Routes>
      </AuthProvider>
    </GoogleOAuthProvider>
  )
}
