import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import apiClient from '../api/client'
import * as authApi from '../api/auth'

export interface CurrentUser {
  user_id: string
  username: string
  role: 'user' | 'admin'
}

export const useAuthStore = defineStore('auth', () => {
  const currentUser = ref<CurrentUser | null>(null)
  const isAdmin = computed(() => currentUser.value?.role === 'admin')
  const isAuthenticated = computed(() => currentUser.value !== null)

  async function fetchMe() {
    const token = localStorage.getItem('api_token')
    if (!token) {
      currentUser.value = null
      return
    }
    try {
      const res = await apiClient.get('/me')
      currentUser.value = res.data
    } catch {
      currentUser.value = null
    }
  }

  async function login(username: string, password: string) {
    const result = await authApi.login(username, password)
    localStorage.setItem('api_token', result.token)
    currentUser.value = result.user
    return result
  }

  async function logout() {
    try {
      await authApi.logout()
    } catch {
      // logout is best-effort
    }
    localStorage.removeItem('api_token')
    currentUser.value = null
  }

  return { currentUser, isAdmin, isAuthenticated, fetchMe, login, logout }
})
