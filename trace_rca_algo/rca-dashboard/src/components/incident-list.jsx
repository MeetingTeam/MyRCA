import { useState, useEffect, useMemo } from 'react'
import { Link } from 'react-router-dom'
import { fetchIncidents } from '../api'
import { useAppFilter } from '../App'
import SeverityBadge from './severity-badge'

export default function IncidentList() {
  const { selectedApps } = useAppFilter()
  const [incidents, setIncidents] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  // Filter state
  const [serviceFilter, setServiceFilter] = useState('')
  const [severityFilter, setSeverityFilter] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')

  // Refetch when selected apps change
  useEffect(() => {
    const abortController = new AbortController()
    setLoading(true)
    setError(null)

    const params = selectedApps.length > 0
      ? { appIds: selectedApps }
      : {}

    fetchIncidents(params)
      .then(data => {
        if (!abortController.signal.aborted) {
          setIncidents(data)
        }
      })
      .catch(e => {
        if (!abortController.signal.aborted) {
          setError(e.message)
        }
      })
      .finally(() => {
        if (!abortController.signal.aborted) {
          setLoading(false)
        }
      })

    return () => abortController.abort()
  }, [selectedApps])

  // Derive unique services from loaded data
  const services = useMemo(() => {
    const set = new Set()
    incidents.forEach(inc => {
      const svc = inc.root_cause?.service || inc.top_service
      if (svc) set.add(svc)
    })
    return [...set].sort()
  }, [incidents])

  // Apply filters
  const filteredIncidents = useMemo(() => {
    return incidents.filter(inc => {
      const rootSvc = inc.root_cause?.service || inc.top_service || ''
      const level = inc.confidence_level || ''
      const start = inc.time_window?.start || ''

      if (serviceFilter && rootSvc !== serviceFilter) return false
      if (severityFilter && level !== severityFilter) return false
      if (dateFrom && start < dateFrom) return false
      if (dateTo && start > dateTo + 'T23:59:59') return false

      return true
    })
  }, [incidents, serviceFilter, severityFilter, dateFrom, dateTo])

  const hasFilters = serviceFilter || severityFilter || dateFrom || dateTo
  const clearFilters = () => {
    setServiceFilter('')
    setSeverityFilter('')
    setDateFrom('')
    setDateTo('')
  }

  if (loading) return <div className="text-center py-12 text-gray-400">Loading incidents...</div>
  if (error) return <div className="text-center py-12 text-red-400">Error: {error}</div>
  if (incidents.length === 0) {
    return (
      <div className="text-center py-20">
        <div className="text-4xl mb-4">&#128994;</div>
        <h2 className="text-xl text-gray-400">No incidents detected</h2>
        <p className="text-gray-500 mt-2">
          {selectedApps.length > 0
            ? `No incidents found for selected apps: ${selectedApps.join(', ')}`
            : 'System is healthy. Incidents will appear here when anomalies are detected.'}
        </p>
      </div>
    )
  }

  const severityLevels = ['AUTO', 'WARNING', 'ESCALATE']
  const severityColors = {
    AUTO: 'bg-green-600 text-green-100',
    WARNING: 'bg-yellow-600 text-yellow-100',
    ESCALATE: 'bg-red-600 text-red-100',
  }

  return (
    <div>
      <h1 className="text-2xl font-bold mb-4">Incidents</h1>

      {/* Filter Bar */}
      <div className="bg-dark-800 rounded-lg border border-gray-700 p-4 mb-4">
        <div className="flex flex-wrap items-center gap-4">
          {/* Service dropdown */}
          <div className="flex items-center gap-2">
            <label className="text-xs text-gray-500 uppercase">Service</label>
            <select
              value={serviceFilter}
              onChange={e => setServiceFilter(e.target.value)}
              className="bg-dark-900 border border-gray-600 rounded px-3 py-1.5 text-sm text-gray-200 focus:outline-none focus:border-blue-500"
            >
              <option value="">All Services</option>
              {services.map(svc => (
                <option key={svc} value={svc}>{svc}</option>
              ))}
            </select>
          </div>

          {/* Severity pills */}
          <div className="flex items-center gap-2">
            <label className="text-xs text-gray-500 uppercase">Severity</label>
            <div className="flex gap-1">
              {severityLevels.map(level => (
                <button
                  key={level}
                  onClick={() => setSeverityFilter(severityFilter === level ? '' : level)}
                  className={`px-3 py-1 rounded text-xs font-semibold transition ${
                    severityFilter === level
                      ? severityColors[level]
                      : 'bg-dark-900 text-gray-400 hover:text-gray-200'
                  }`}
                >
                  {level}
                </button>
              ))}
            </div>
          </div>

          {/* Date range */}
          <div className="flex items-center gap-2">
            <label className="text-xs text-gray-500 uppercase">From</label>
            <input
              type="date"
              value={dateFrom}
              onChange={e => setDateFrom(e.target.value)}
              className="bg-dark-900 border border-gray-600 rounded px-2 py-1.5 text-sm text-gray-200 focus:outline-none focus:border-blue-500"
            />
            <label className="text-xs text-gray-500 uppercase">To</label>
            <input
              type="date"
              value={dateTo}
              onChange={e => setDateTo(e.target.value)}
              className="bg-dark-900 border border-gray-600 rounded px-2 py-1.5 text-sm text-gray-200 focus:outline-none focus:border-blue-500"
            />
          </div>

          {/* Clear */}
          {hasFilters && (
            <button
              onClick={clearFilters}
              className="ml-auto text-xs text-gray-400 hover:text-white transition"
            >
              Clear All
            </button>
          )}
        </div>
      </div>

      {/* Table */}
      <div className="bg-dark-800 rounded-lg border border-gray-700 overflow-hidden">
        <table className="w-full">
          <thead>
            <tr className="border-b border-gray-700 text-gray-400 text-sm">
              <th className="text-left px-4 py-3">Time Window</th>
              <th className="text-left px-4 py-3">App</th>
              <th className="text-left px-4 py-3">Root Cause</th>
              <th className="text-left px-4 py-3">Confidence</th>
              <th className="text-left px-4 py-3">Severity</th>
              <th className="text-left px-4 py-3">Traces</th>
            </tr>
          </thead>
          <tbody>
            {filteredIncidents.map((inc) => {
              const rootSvc = inc.root_cause?.service || inc.top_service || '—'
              const confidence = inc.root_cause?.confidence ?? inc.top_score
              const level = inc.confidence_level
              const tw = inc.time_window || {}
              const start = tw.start ? new Date(tw.start + 'Z').toLocaleString() : '—'

              return (
                <tr key={inc.incident_id} className="border-b border-gray-700/50 hover:bg-dark-700 transition">
                  <td className="px-4 py-3">
                    <Link to={`/incidents/${inc.incident_id}${inc.app_id ? `?app_id=${inc.app_id}` : ''}`} className="text-blue-400 hover:underline text-sm">
                      {start}
                    </Link>
                  </td>
                  <td className="px-4 py-3">
                    {inc.app_id ? (
                      <span className="px-2 py-0.5 bg-blue-900/50 text-blue-300 rounded text-xs font-medium">
                        {inc.app_id}
                      </span>
                    ) : (
                      <span className="text-gray-500 text-xs">—</span>
                    )}
                  </td>
                  <td className="px-4 py-3 font-mono text-sm">{rootSvc}</td>
                  <td className="px-4 py-3 text-sm">
                    {confidence != null ? `${(confidence * 100).toFixed(1)}%` : '—'}
                  </td>
                  <td className="px-4 py-3"><SeverityBadge level={level} /></td>
                  <td className="px-4 py-3 text-sm text-gray-400">
                    {inc.trace_summary?.anomalous_traces ?? '—'} / {inc.trace_summary?.total_traces ?? '—'}
                  </td>
                </tr>
              )
            })}
            {filteredIncidents.length === 0 && (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-gray-500">
                  No incidents match the current filters
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Result count */}
      <div className="mt-2 text-xs text-gray-500 text-right">
        Showing {filteredIncidents.length} of {incidents.length} incidents
        {selectedApps.length > 0 && ` (filtered by ${selectedApps.length} app${selectedApps.length > 1 ? 's' : ''})`}
      </div>
    </div>
  )
}
