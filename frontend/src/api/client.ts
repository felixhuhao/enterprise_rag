/**
 * Axios HTTP 客户端
 *
 * 统一配置 baseURL 和超时时间，自动在请求头中注入 Bearer Token，
 * 401 响应时清除本地 Token 提示用户重新设置
 */
import axios from 'axios'
import { Message } from '@arco-design/web-vue'

const apiClient = axios.create({
  baseURL: '/api',     // 所有请求走 Vite proxy 代理到后端
  timeout: 30000,      // 30 秒超时
})

// 请求拦截器：自动携带 Token
apiClient.interceptors.request.use((config) => {
  const token = localStorage.getItem('api_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// 响应拦截器：统一处理 HTTP 错误
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('api_token')
      Message.error('登录已过期，请重新登录')
      // Redirect to login page
      if (window.location.pathname !== '/login') {
        window.location.href = '/login'
      }
    }
    return Promise.reject(error)
  },
)

export default apiClient
