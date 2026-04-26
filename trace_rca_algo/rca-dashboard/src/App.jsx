import { useState, useEffect, createContext, useContext } from 'react'
import { Routes, Route, Link, useSearchParams } from 'react-router-dom'
import IncidentList from './components/incident-list'
import IncidentDetail from './components/incident-detail'
import { fetchApplications } from './api'

// App filter context for sharing selected apps across components
const AppFilterContext = createContext({
  applications: [],
  selectedApps: [],
  setSelectedApps: () => {},
  loading: true,
  error: null,
})

export const useAppFilter = () => useContext(AppFilterContext)

export default function App() {
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
          <div className="flex items-center gap-4 mb-2">
            <Link to="/" className="text-lg font-bold text-white hover:text-blue-400">
              MyRCA Dashboard
            </Link>
            <span className="text-gray-500 text-sm">Root Cause Analysis</span>
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
