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
    subscriptionPlan: apiUser.subscription_plan || 'free',
    subscriptionPlanLabel: apiUser.subscription_plan_label || 'Free',
    subscriptionStartedAt: apiUser.subscription_started_at || null,
    subscriptionEndsAt: apiUser.subscription_ends_at || null,
    subscriptionAutoRenew: Boolean(apiUser.subscription_auto_renew),
    latestPayment: apiUser.latest_payment || null,
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

  const loginWithGoogle = async (credential) => {
    await authApi.loginWithGoogle(credential)
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

  const updateSubscription = async ({ plan, autoRenew, paymentMethod }) => {
    const updated = await authApi.updateSubscription({ plan, autoRenew, paymentMethod })
    const mapped = mapUser(updated)
    setUser(mapped)
    return mapped
  }

  return (
    <AuthContext.Provider value={{ user, loading, login, loginWithGoogle, register, logout, updateSubscription }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
