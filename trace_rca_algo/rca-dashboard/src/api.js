const API_BASE = import.meta.env.VITE_API_URL || ''

export async function fetchApplications() {
  const res = await fetch(`${API_BASE}/api/applications`)
  if (!res.ok) throw new Error('Failed to fetch applications')
  return res.json()
}

export async function fetchIncidents({ appId, appIds, limit } = {}) {
  const params = new URLSearchParams()
  if (appId) params.set('app_id', appId)
  if (appIds?.length) params.set('app_ids', appIds.join(','))
  if (limit) params.set('limit', limit.toString())

  const queryString = params.toString()
  const url = `${API_BASE}/api/incidents${queryString ? `?${queryString}` : ''}`

  const res = await fetch(url)
  if (!res.ok) throw new Error('Failed to fetch incidents')
  return res.json()
}

export async function fetchIncident(id, appId = null) {
  const params = new URLSearchParams()
  if (appId) params.set('app_id', appId)

  const queryString = params.toString()
  const url = `${API_BASE}/api/incidents/${id}${queryString ? `?${queryString}` : ''}`

  const res = await fetch(url)
  if (!res.ok) throw new Error('Incident not found')
  return res.json()
}
