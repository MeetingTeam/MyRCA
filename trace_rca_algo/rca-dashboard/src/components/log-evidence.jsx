import { useState } from 'react'

const LEVEL_COLORS = {
  ERROR: 'text-red-400',
  WARN: 'text-yellow-400',
  WARNING: 'text-yellow-400',
  FATAL: 'text-red-500',
  INFO: 'text-blue-400',
}

export default function LogEvidence({ logs }) {
  const [expanded, setExpanded] = useState({})

  if (!logs || Object.keys(logs).length === 0) {
    return <p className="text-gray-500">No log evidence available</p>
  }

  const toggle = (svc) => setExpanded(prev => ({ ...prev, [svc]: !prev[svc] }))

  return (
    <div className="space-y-2">
      {Object.entries(logs).map(([service, entries]) => (
        <div key={service} className="border border-gray-700 rounded-lg overflow-hidden">
          <button
            onClick={() => toggle(service)}
            className="w-full flex items-center justify-between px-4 py-2 bg-dark-700 hover:bg-dark-800 text-left"
          >
            <span className="font-mono text-sm">{service}</span>
            <span className="text-gray-500 text-xs">
              {entries.length} log{entries.length !== 1 ? 's' : ''}
              {expanded[service] ? ' ▼' : ' ▶'}
            </span>
          </button>
          {expanded[service] && (
            <div className="p-3 bg-dark-900 space-y-1 max-h-60 overflow-y-auto">
              {entries.map((entry, i) => {
                const level = (entry.level || '').toUpperCase()
                const color = LEVEL_COLORS[level] || 'text-gray-400'
                return (
                  <div key={i} className="text-xs font-mono flex gap-2">
                    <span className={`${color} font-semibold w-14 shrink-0`}>[{level}]</span>
                    <span className="text-gray-300 break-all">{entry.message}</span>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}
