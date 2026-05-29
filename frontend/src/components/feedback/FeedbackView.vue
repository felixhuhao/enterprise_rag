<!--
  答案反馈管理 — admin-only。
-->
<template>
  <div class="feedback-page">
    <div class="fb-header">
      <div>
        <h3>答案反馈</h3>
        <p>用户对回答质量的反馈记录和 Golden Set 草稿管理。</p>
      </div>
      <a-select v-if="authStore.isAdmin" v-model="filterUserId" :style="{ width: '160px' }" size="small"
                placeholder="筛选用户" allow-clear>
        <a-option value="">全部用户</a-option>
        <a-option value="u_alice">Alice</a-option>
        <a-option value="u_bob">Bob</a-option>
        <a-option value="u_admin">Admin</a-option>
      </a-select>
    </div>
    <div v-if="!authStore.isAdmin" class="fb-forbidden">
      <a-empty description="仅管理员可查看答案反馈" />
    </div>
    <FeedbackRecords v-else :filter-user-id="filterUserId" />
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useAuthStore } from '../../stores/auth'
import FeedbackRecords from './FeedbackRecords.vue'

const authStore = useAuthStore()
const filterUserId = ref('')
</script>

<style scoped>
.feedback-page {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 20px;
  height: 100%;
  overflow-y: auto;
  animation: fadeIn 0.22s var(--ease-out);
}
.fb-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 16px;
}
.fb-header h3 { margin: 0; font-size: 18px; font-weight: 700; color: var(--text-primary); }
.fb-header p { margin: 6px 0 0; color: var(--text-muted); font-size: 13px; }
.fb-forbidden { padding: 60px 0; }
</style>
