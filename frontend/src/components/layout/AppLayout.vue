<!--
  应用主布局

  左侧导航栏（可折叠）+ 顶部标题栏 + 主内容区
  侧边栏底部提供 Token 输入（不依赖 API，直接写 localStorage）
-->
<template>
  <a-layout class="app-layout">
    <!-- 左侧导航栏 -->
    <a-layout-sider :width="220" :collapsible="true" class="sider">
      <div class="logo">
        <span class="logo-icon">◆</span>
        <span class="logo-text">港股 AI 助手</span>
      </div>
      <a-menu :selected-keys="[currentRoute]" @menu-item-click="onMenuClick">
        <a-menu-item key="/query-chat">
          <template #icon><icon-search /></template>
          知识查询
        </a-menu-item>
        <a-menu-item key="/chat">
          <template #icon><icon-message /></template>
          智能对话
        </a-menu-item>
        <a-menu-item key="/documents">
          <template #icon><icon-storage /></template>
          文档管理
        </a-menu-item>
        <a-menu-item key="/evaluate">
          <template #icon><icon-bar-chart /></template>
          评估看板
        </a-menu-item>
        <a-menu-item key="/settings">
          <template #icon><icon-settings /></template>
          系统设置
        </a-menu-item>
      </a-menu>
      <!-- Token 输入区域 -->
      <div class="sider-footer">
        <div class="token-label" @click="showTokenInput = !showTokenInput">
          <icon-lock />
          <span>API Token</span>
          <icon-tag v-if="tokenSet && !showTokenInput" :style="{ color: 'var(--success)' }" />
        </div>
        <div v-if="showTokenInput" class="token-input">
          <a-input-password
            v-model="tokenValue"
            placeholder="输入 API Token"
            size="small"
            @keydown.enter="saveToken"
          />
          <a-button type="primary" size="mini" @click="saveToken">保存</a-button>
        </div>
      </div>
    </a-layout-sider>
    <!-- 右侧主区域 -->
    <a-layout>
      <a-layout-header class="header">
        <span class="header-title">多模态 RAG 知识库</span>
        <span class="header-badge">Pro</span>
      </a-layout-header>
      <a-layout-content class="content">
        <router-view />
      </a-layout-content>
    </a-layout>
  </a-layout>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import {
  IconMessage,
  IconStorage,
  IconBarChart,
  IconSettings,
  IconLock,
  IconTag,
  IconSearch,
} from '@arco-design/web-vue/es/icon'

const router = useRouter()
const route = useRoute()

const currentRoute = computed(() => route.path)
const showTokenInput = ref(false)
const tokenValue = ref('')
const tokenSet = ref(false)

function onMenuClick(key: string) {
  router.push(key)
}

onMounted(() => {
  const stored = localStorage.getItem('api_token')
  if (stored) {
    tokenValue.value = stored
    tokenSet.value = true
  } else {
    showTokenInput.value = true
  }
})

function saveToken() {
  const trimmed = tokenValue.value.trim()
  if (!trimmed) return
  localStorage.setItem('api_token', trimmed)
  tokenSet.value = true
  showTokenInput.value = false
}
</script>

<style scoped>
.app-layout {
  height: 100vh;
}

/* ---- Sidebar ---- */
.sider {
  background: linear-gradient(180deg, #0F1318 0%, #0B0E14 100%) !important;
  border-right: 1px solid var(--border) !important;
  display: flex;
  flex-direction: column;
}

.logo {
  height: 60px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  border-bottom: 1px solid var(--border);
  animation: fadeIn 0.5s var(--ease-out);
}

.logo-icon {
  color: var(--accent);
  font-size: 18px;
  filter: drop-shadow(0 0 6px var(--accent-glow));
}

.logo-text {
  font-family: var(--font-display);
  font-size: 15px;
  font-weight: 700;
  color: var(--text-primary);
  letter-spacing: 0.02em;
}

.sider-footer {
  margin-top: auto;
  border-top: 1px solid var(--border);
  padding: 12px 16px;
}

.token-label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--text-muted);
  cursor: pointer;
  user-select: none;
  transition: color 0.2s var(--ease-out);
}
.token-label:hover {
  color: var(--accent);
}

.token-input {
  display: flex;
  gap: 6px;
  margin-top: 8px;
}
.token-input :deep(.arco-input-password) {
  flex: 1;
}

/* ---- Header ---- */
.header {
  background: var(--bg-surface) !important;
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 24px;
  height: 52px !important;
}

.header-title {
  font-family: var(--font-display);
  font-size: 14px;
  font-weight: 500;
  color: var(--text-secondary);
  letter-spacing: 0.02em;
}

.header-badge {
  font-family: var(--font-display);
  font-size: 10px;
  font-weight: 700;
  color: var(--accent);
  background: var(--accent-subtle);
  border: 1px solid var(--border-accent);
  padding: 1px 6px;
  border-radius: 4px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

/* ---- Content ---- */
.content {
  background: var(--bg-base) !important;
  padding: 16px;
  overflow: hidden;
}
</style>
