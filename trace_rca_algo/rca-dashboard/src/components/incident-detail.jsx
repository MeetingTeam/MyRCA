import { useState, useEffect } from 'react'
import { useParams, useSearchParams, Link } from 'react-router-dom'
import { fetchIncident } from '../api'
import SeverityBadge from './severity-badge'
import PropagationChain from './propagation-chain'
import LogEvidence from './log-evidence'

export default function IncidentDetail() {
  const { id } = useParams()
  const [searchParams] = useSearchParams()
  const appIdHint = searchParams.get('app_id')

  const [incident, setIncident] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    fetchIncident(id, appIdHint)
      .then(setIncident)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [id, appIdHint])

  if (loading) return <div className="text-center py-12 text-gray-400">Loading...</div>
  if (error) return <div className="text-center py-12 text-red-400">Error: {error}</div>
  if (!incident) return <div className="text-center py-12 text-gray-400">Not found</div>

  const s2 = incident.stage2_result || {}
  const rc = s2.root_cause || {}
  const analysis = s2.analysis || []
  const chain = s2.propagation_chain || []
  const ranking = incident.stage1_ranking || []
  const tw = incident.time_window || {}
  const ts = incident.trace_summary || {}

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3 flex-wrap">
        <Link to="/" className="text-gray-400 hover:text-white">&larr; Back</Link>
        <h1 className="text-xl font-bold">Incident Analysis</h1>
        {incident.app_id && (
          <span className="px-3 py-1 bg-blue-900/50 text-blue-300 rounded-full text-sm font-medium">
            {incident.app_id}
          </span>
        )}
        <SeverityBadge level={s2.confidence_level} />
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <Card title="Time Window">
          <div className="text-sm">
            <div>{tw.start ? new Date(tw.start + 'Z').toLocaleString() : '—'}</div>
            <div className="text-gray-500">to {tw.end ? new Date(tw.end + 'Z').toLocaleString() : '—'}</div>
          </div>
        </Card>
        <Card title="Root Cause">
          <div className="font-mono text-red-400 text-lg">{rc.service || '—'}</div>
        </Card>
        <Card title="Confidence">
          <div className="text-2xl font-bold">
            {rc.confidence != null ? `${(rc.confidence * 100).toFixed(1)}%` : '—'}
          </div>
          {s2.agreement_ratio != null && (
            <div className="text-xs text-gray-500">Agreement: {(s2.agreement_ratio * 100).toFixed(0)}%</div>
          )}
        </Card>
        <Card title="Traces">
          <div className="text-2xl font-bold">{ts.anomalous_traces ?? '—'}</div>
          <div className="text-xs text-gray-500">anomalous of {ts.total_traces ?? '—'} total</div>
        </Card>
      </div>

      {/* Propagation Chain */}
      <Section title="Propagation Path">
        <PropagationChain chain={chain} />
      </Section>

      {/* Stage 1 Ranking */}
      <Section title="Stage 1 — Structural Ranking">
        <div className="space-y-2">
          {ranking.map((r, i) => (
            <div key={i} className="flex items-center gap-3">
              <span className="text-gray-500 w-6 text-right">#{i + 1}</span>
              <span className="font-mono text-sm w-48">{r.service}</span>
              <div className="flex-1 bg-dark-900 rounded-full h-3 overflow-hidden">
                <div
                  className="h-full bg-blue-500 rounded-full"
                  style={{ width: `${Math.min(r.score * 100, 100)}%` }}
                />
              </div>
              <span className="text-sm text-gray-400 w-16 text-right">{r.score?.toFixed(4)}</span>
            </div>
          ))}
        </div>
      </Section>

      {/* Affected Services */}
      <Section title="Affected Services">
        {analysis.length === 0 ? (
          <p className="text-gray-500">No LLM analysis available (Stage 1 only)</p>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {analysis.map((a, i) => (
              <div
                key={i}
                className={`p-4 rounded-lg border ${
                  a.classification === 'INTRINSIC'
                    ? 'border-red-500/50 bg-red-900/20'
                    : 'border-yellow-500/50 bg-yellow-900/20'
                }`}
              >
                <div className="flex items-center gap-2 mb-2">
                  <span className="font-mono font-bold">{a.service}</span>
                  <span className={`text-xs px-2 py-0.5 rounded ${
                    a.classification === 'INTRINSIC'
                      ? 'bg-red-600 text-red-100'
                      : 'bg-yellow-600 text-yellow-100'
                  }`}>
                    {a.classification}
                  </span>
                </div>
                <p className="text-sm text-gray-300">{a.evidence}</p>
              </div>
            ))}
          </div>
        )}
      </Section>

      {/* AI Severity Suggestion */}
      <Section title="AI Severity Suggestion">
        <div className="flex items-start gap-4">
          <SeverityBadge level={s2.confidence_level} />
          <div className="text-sm text-gray-300">
            {s2.confidence_level === 'AUTO' && 'Confidence is high enough for automated remediation. The structural and LLM analyses agree on the root cause.'}
            {s2.confidence_level === 'WARNING' && 'Moderate confidence. Human review recommended before taking action. The analyses show some uncertainty.'}
            {s2.confidence_level === 'ESCALATE' && 'Low confidence. Manual investigation required. The structural and LLM analyses disagree or show high uncertainty.'}
            {!s2.confidence_level && 'Stage 2 analysis not available. Only structural ranking is shown.'}
          </div>
        </div>
      </Section>

      {/* Remediation Suggestions */}
      <Section title="Remediation Suggestions">
        {analysis.length === 0 ? (
          <p className="text-gray-500">No remediation data available</p>
        ) : (
          <div className="space-y-3">
            {analysis.filter(a => a.classification === 'INTRINSIC').map((a, i) => (
              <div key={i} className="p-3 bg-dark-700 rounded-lg border border-gray-600">
                <div className="text-sm font-semibold text-red-400 mb-1">
                  Investigate: {a.service}
                </div>
                <p className="text-sm text-gray-300">{a.evidence}</p>
              </div>
            ))}
            {analysis.filter(a => a.classification === 'PROPAGATED').map((a, i) => (
              <div key={i} className="p-3 bg-dark-700 rounded-lg border border-gray-700">
                <div className="text-sm font-semibold text-yellow-400 mb-1">
                  Cascading failure: {a.service}
                </div>
                <p className="text-sm text-gray-300">{a.evidence}</p>
              </div>
            ))}
          </div>
        )}
      </Section>

      {/* Log Evidence */}
      <Section title="Log Evidence">
        <LogEvidence logs={incident.log_evidence} />
      </Section>
    </div>
  )
}

function Card({ title, children }) {
  return (
    <div className="bg-dark-800 rounded-lg border border-gray-700 p-4">
      <div className="text-xs text-gray-500 uppercase mb-1">{title}</div>
      {children}
    </div>
  )
}

function Section({ title, children }) {
  return (
    <div className="bg-dark-800 rounded-lg border border-gray-700 p-5">
      <h2 className="text-lg font-semibold mb-4">{title}</h2>
      {children}
    </div>
  )
}
