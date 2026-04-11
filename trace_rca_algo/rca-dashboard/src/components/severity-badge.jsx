const COLORS = {
  AUTO: 'bg-green-600 text-green-100',
  WARNING: 'bg-yellow-600 text-yellow-100',
  ESCALATE: 'bg-red-600 text-red-100',
}

const LABELS = {
  AUTO: 'Auto-Remediate',
  WARNING: 'Review Needed',
  ESCALATE: 'Manual Escalation',
}

export default function SeverityBadge({ level }) {
  const color = COLORS[level] || 'bg-gray-600 text-gray-100'
  const label = LABELS[level] || level || 'Unknown'
  return (
    <span className={`px-2 py-1 rounded text-xs font-semibold ${color}`}>
      {label}
    </span>
  )
}
