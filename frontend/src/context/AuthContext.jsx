import { createContext, useContext, useEffect, useState } from 'react'
import api from '../services/api'
const AuthContext = createContext(null)
export function AuthProvider({ children }) {
  const [user, setUser] = useState(null); const [loading, setLoading] = useState(true)
  useEffect(() => { if (localStorage.getItem('ah_token')) api.get('/users/me').then(r => setUser(r.data)).catch(() => localStorage.removeItem('ah_token')).finally(() => setLoading(false)); else setLoading(false) }, [])
  const signIn = async (path, payload) => { const { data } = await api.post(path, payload); localStorage.setItem('ah_token', data.access_token); setUser(data.user); return data.user }
  const logout = () => { localStorage.removeItem('ah_token'); setUser(null) }
  return <AuthContext.Provider value={{ user, loading, signIn, logout, setUser }}>{children}</AuthContext.Provider>
}
export const useAuth = () => useContext(AuthContext)
