import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import apiClient from '../api/client'

export interface CurrentUser {
  user_id: string
  username: string
  role: 'user' | 'admin'
}

export const useAuthStore = defineStore('auth', () => {
  const currentUser = ref<CurrentUser | null>(null)
  const isAdmin = computed(() => currentUser.value?.role === 'admin')

  async function fetchMe() {
    try {
      const res = await apiClient.get('/me')
      currentUser.value = res.data
    } catch {
      currentUser.value = null
    }
  }

  return { currentUser, isAdmin, fetchMe }
})
