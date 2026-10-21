import axios from 'axios'
const api = axios.create({ baseURL: import.meta.env.VITE_API_URL || 'http://localhost:8000/api' })
api.interceptors.request.use(config => { const token = localStorage.getItem('ah_token'); if (token) config.headers.Authorization = `Bearer ${token}`; return config })
export const errorMessage = e => e?.response?.data?.detail || e?.message || 'Something went wrong.'
export default api
