const API_BASE = '/api'

function getStoredAccess() {
  return localStorage.getItem('diploma_access')
}

function getStoredRefresh() {
  return localStorage.getItem('diploma_refresh')
}

function setTokens(access, refresh) {
  if (access) localStorage.setItem('diploma_access', access)
  if (refresh) localStorage.setItem('diploma_refresh', refresh)
}

function clearTokens() {
  localStorage.removeItem('diploma_access')
  localStorage.removeItem('diploma_refresh')
}

async function request(path, options = {}) {
  const url = `${API_BASE}${path}`
  const headers = {
    'Content-Type': 'application/json',
    ...options.headers,
  }
  const access = getStoredAccess()
  if (access) headers['Authorization'] = `Bearer ${access}`

  const res = await fetch(url, { ...options, headers })
  if (!res.ok) {
    const err = new Error(res.statusText || 'Request failed')
    err.status = res.status
    try {
      err.body = await res.json()
    } catch (_) {
      err.body = null
    }
    throw err
  }
  if (res.status === 204) return null
  return res.json()
}

export const authApi = {
  async login(email, password) {
    const data = await request('/auth/token/', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    })
    setTokens(data.access, data.refresh)
    return data
  },

  async register({ email, password, password_confirm, first_name, last_name }) {
    await request('/auth/register/', {
      method: 'POST',
      body: JSON.stringify({
        email,
        password,
        password_confirm,
        first_name: first_name || '',
        last_name: last_name || '',
      }),
    })
  },

  async getMe() {
    const data = await request('/auth/me/')
    return data
  },

  async refreshToken() {
    const refresh = getStoredRefresh()
    if (!refresh) throw new Error('No refresh token')
    const data = await fetch(`${API_BASE}/auth/token/refresh/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh }),
    }).then((r) => {
      if (!r.ok) throw new Error('Refresh failed')
      return r.json()
    })
    setTokens(data.access, null)
    return data.access
  },

  logout() {
    clearTokens()
  },

  getStoredAccess,
  clearTokens,
}

export const plansApi = {
  async listPlans() {
    return request('/plans/')
  },

  async createPlan({ title, description }) {
    return request('/plans/', {
      method: 'POST',
      body: JSON.stringify({ title, description }),
    })
  },

  async uploadDocument(planId, file) {
    const formData = new FormData()
    formData.append('file', file)

    const headers = {}
    const access = getStoredAccess()
    if (access) headers['Authorization'] = `Bearer ${access}`

    const res = await fetch(`${API_BASE}/plans/${planId}/documents/`, {
      method: 'POST',
      headers,
      body: formData,
    })
    if (!res.ok) {
      const err = new Error(res.statusText || 'Upload failed')
      err.status = res.status
      try {
        err.body = await res.json()
      } catch (_) {
        err.body = null
      }
      throw err
    }
    return res.json()
  },
}
