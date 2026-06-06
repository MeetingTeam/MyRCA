import { createContext, useContext, useState, useEffect } from 'react'
import { googleLogin, fetchMe } from './api'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [token, setToken] = useState(() => localStorage.getItem('auth_token'))
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (token) {
      fetchMe()
        .then(setUser)
        .catch(() => {
          localStorage.removeItem('auth_token')
          setToken(null)
        })
        .finally(() => setLoading(false))
    } else {
      setLoading(false)
    }
  }, [token])

  const loginWithGoogle = async (googleIdToken) => {
    const data = await googleLogin(googleIdToken)
    localStorage.setItem('auth_token', data.access_token)
    setToken(data.access_token)
    setUser(data.user)
    return data
  }

  const loginWithPassword = async () => {
    throw new Error('Username/password login not implemented yet')
  }

  const logout = () => {
    localStorage.removeItem('auth_token')
    setToken(null)
    setUser(null)
  }

  return (
    <AuthContext.Provider value={{
      user,
      token,
      loginWithGoogle,
      loginWithPassword,
      logout,
      loading,
      isAuthenticated: !!user,
    }}>
      {children}
    </AuthContext.Provider>
  )
}

export const useAuth = () => useContext(AuthContext)
