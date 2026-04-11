import { Routes, Route, Link } from 'react-router-dom'
import IncidentList from './components/incident-list'
import IncidentDetail from './components/incident-detail'

export default function App() {
  return (
    <div className="min-h-screen">
      <nav className="bg-dark-800 border-b border-gray-700 px-6 py-3 flex items-center gap-4">
        <Link to="/" className="text-lg font-bold text-white hover:text-blue-400">
          MyRCA Dashboard
        </Link>
        <span className="text-gray-500 text-sm">Root Cause Analysis</span>
      </nav>
      <main className="max-w-7xl mx-auto px-6 py-6">
        <Routes>
          <Route path="/" element={<IncidentList />} />
          <Route path="/incidents/:id" element={<IncidentDetail />} />
        </Routes>
      </main>
    </div>
  )
}
