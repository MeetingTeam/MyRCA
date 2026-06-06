import { ExternalLink, Database, FileText, Activity } from 'lucide-react'

const GRAFANA_BASE_URL = import.meta.env.VITE_GRAFANA_URL || 'http://grafana.local'

const dashboards = [
  {
    id: 'loki',
    name: 'Loki Logs',
    description: 'Application logs and error tracking',
    icon: FileText,
  },
  {
    id: 'clickhouse',
    name: 'ClickHouse Metrics',
    description: 'Database performance and query analytics',
    icon: Database,
  },
  {
    id: 'tempo',
    name: 'Tempo Traces',
    description: 'Distributed tracing and latency analysis',
    icon: Activity,
  },
]

export default function GrafanaLinks() {
  return (
    <div>
      <h1 className="text-2xl font-bold mb-6">Grafana Dashboards</h1>
      <p className="text-gray-400 mb-8">
        Access observability dashboards for logs, metrics, and traces.
      </p>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {dashboards.map(dashboard => (
          <a
            key={dashboard.id}
            href={`${GRAFANA_BASE_URL}/d/${dashboard.id}`}
            target="_blank"
            rel="noopener noreferrer"
            className="bg-dark-800 border border-gray-700 rounded-lg p-6 hover:border-blue-500 hover:bg-dark-700 transition group"
          >
            <div className="flex items-center gap-3 mb-3">
              <dashboard.icon size={24} className="text-blue-400" />
              <h2 className="text-lg font-semibold">{dashboard.name}</h2>
              <ExternalLink size={16} className="text-gray-500 group-hover:text-blue-400 ml-auto" />
            </div>
            <p className="text-sm text-gray-400">{dashboard.description}</p>
          </a>
        ))}
      </div>
    </div>
  )
}
