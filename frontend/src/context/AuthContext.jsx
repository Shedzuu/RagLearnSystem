import { createContext, useContext, useState, useEffect, useCallback } from 'react'
import { authApi } from '../api/client'

const AuthContext = createContext(null)

function mapUser(apiUser) {
  if (!apiUser) return null
  return {
    id: apiUser.id,
    email: apiUser.email,
    firstName: apiUser.first_name || '',
    lastName: apiUser.last_name || '',
  }
}

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)

  const loadUser = useCallback(async () => {
    const access = authApi.getStoredAccess()
    if (!access) {
      setLoading(false)
      return
    }
    try {
      const data = await authApi.getMe()
      setUser(mapUser(data))
    } catch (e) {
      if (e.status === 401) {
        try {
          await authApi.refreshToken()
          const data = await authApi.getMe()
          setUser(mapUser(data))
        } catch (_) {
          authApi.logout()
          setUser(null)
        }
      } else {
        setUser(null)
      }
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadUser()
  }, [loadUser])

  const login = async (email, password) => {
    await authApi.login(email, password)
    const data = await authApi.getMe()
    setUser(mapUser(data))
  }

  const register = async (data) => {
    await authApi.register(data)
    await authApi.login(data.email, data.password)
    const me = await authApi.getMe()
    setUser(mapUser(me))
  }

  const logout = () => {
    authApi.logout()
    setUser(null)
  }

  return (
    <AuthContext.Provider value={{ user, loading, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
