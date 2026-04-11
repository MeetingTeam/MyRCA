const API_BASE = import.meta.env.VITE_API_URL || ''

export async function fetchIncidents() {
  const res = await fetch(`${API_BASE}/api/incidents`)
  if (!res.ok) throw new Error('Failed to fetch incidents')
  return res.json()
}

export async function fetchIncident(id) {
  const res = await fetch(`${API_BASE}/api/incidents/${id}`)
  if (!res.ok) throw new Error('Incident not found')
  return res.json()
}
