const API_BASE = import.meta.env.VITE_API_URL || ''

function getAuthHeaders() {
  const token = localStorage.getItem('auth_token')
  return token ? { Authorization: `Bearer ${token}` } : {}
}

function handleAuthError(res) {
  if (res.status === 401) {
    localStorage.removeItem('auth_token')
    window.location.href = '/login'
    throw new Error('Unauthorized')
  }
}

export async function googleLogin(idToken) {
  const res = await fetch(`${API_BASE}/api/auth/google`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id_token: idToken }),
  })
  if (!res.ok) throw new Error('Login failed')
  return res.json()
}

export async function fetchMe() {
  const res = await fetch(`${API_BASE}/api/auth/me`, {
    headers: getAuthHeaders(),
  })
  if (!res.ok) throw new Error('Not authenticated')
  return res.json()
}

export async function fetchApplications() {
  const res = await fetch(`${API_BASE}/api/applications`, {
    headers: getAuthHeaders(),
  })
  handleAuthError(res)
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

  const res = await fetch(url, { headers: getAuthHeaders() })
  handleAuthError(res)
  if (!res.ok) throw new Error('Failed to fetch incidents')
  return res.json()
}

export async function fetchIncident(id, appId = null) {
  const params = new URLSearchParams()
  if (appId) params.set('app_id', appId)

  const queryString = params.toString()
  const url = `${API_BASE}/api/incidents/${id}${queryString ? `?${queryString}` : ''}`

  const res = await fetch(url, { headers: getAuthHeaders() })
  handleAuthError(res)
  if (!res.ok) throw new Error('Incident not found')
  return res.json()
}
