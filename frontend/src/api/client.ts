import axios from 'axios'
import { ElMessage } from 'element-plus'

const instance = axios.create({
  baseURL: import.meta.env.VITE_API_BASE ? `${import.meta.env.VITE_API_BASE}/api` : '/api',
  timeout: 15000,
})

instance.interceptors.request.use((config) => {
  const token = localStorage.getItem('xzc25_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

instance.interceptors.response.use(
  (resp) => resp,
  (err) => {
    if (err.response?.status === 401) {
      ElMessage.error('登录已失效，请重新登录')
      localStorage.removeItem('xzc25_token')
      localStorage.removeItem('xzc25_user')
      if (location.pathname !== '/login') {
        location.href = '/login'
      }
    } else if (err.response?.status === 409) {
      ElMessage.warning(err.response.data?.detail || '业务冲突')
    } else if (err.response?.status === 403) {
      ElMessage.error(err.response.data?.detail || '无权访问')
    } else {
      ElMessage.error(err.response?.data?.detail || err.message || '请求失败')
    }
    return Promise.reject(err)
  }
)

export default instance
