<template>
  <LoginView v-if="!authStore.isAuthenticated" />
  <AppLayout v-else />
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import AppLayout from './components/layout/AppLayout.vue'
import LoginView from './components/auth/LoginView.vue'
import { useAuthStore } from './stores/auth'

const authStore = useAuthStore()

onMounted(() => {
  authStore.fetchMe()
})
</script>
