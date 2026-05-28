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
        <div class="logo-mark">ER</div>
        <div class="logo-copy">
          <span class="logo-text">Enterprise RAG</span>
          <span class="logo-subtitle">知识库控制台</span>
        </div>
      </div>
      <a-menu :selected-keys="[currentRoute]" @menu-item-click="onMenuClick">
        <a-menu-item key="/query-chat">
          <template #icon><icon-search /></template>
          知识查询
        </a-menu-item>
        <a-menu-item key="/documents">
          <template #icon><icon-storage /></template>
          文档管理
        </a-menu-item>
        <a-menu-item key="/retrieval-test">
          <template #icon><icon-search /></template>
          检索测试
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
          <span>访问令牌</span>
          <icon-tag v-if="tokenSet && !showTokenInput" :style="{ color: 'var(--success)' }" />
        </div>
        <div v-if="showTokenInput" class="token-input">
          <a-input-password
            v-model="tokenValue"
            placeholder="输入访问令牌"
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
        <div>
          <div class="header-title">{{ pageTitle }}</div>
          <div class="header-subtitle">{{ pageSubtitle }}</div>
        </div>
        <div class="header-status">
          <span class="status-dot"></span>
          <span>{{ tokenSet ? '访问令牌已配置' : '需要访问令牌' }}</span>
        </div>
      </a-layout-header>
      <a-layout-content class="content">
        <router-view v-slot="{ Component }">
          <keep-alive :include="['RetrievalTestView']">
            <component :is="Component" />
          </keep-alive>
        </router-view>
      </a-layout-content>
    </a-layout>
  </a-layout>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import {
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
const pageMeta = computed(() => {
  const map: Record<string, { title: string; subtitle: string }> = {
    '/query-chat': { title: '知识查询', subtitle: '基于引用、检索链路和耗时追踪回答问题。' },
    '/documents': { title: '文档管理', subtitle: '上传、处理、重试和修复知识库文档。' },
    '/retrieval-test': { title: '检索测试', subtitle: '只运行召回和重排，检查 Top K chunks 与检索策略。' },
    '/evaluate': { title: '评估看板', subtitle: '监控查询质量、失败率、回退情况和延迟。' },
    '/settings': { title: '系统设置', subtitle: '配置模型、检索和运行时行为。' },
  }
  return map[route.path] ?? { title: 'Enterprise RAG', subtitle: '知识库运行控制台。' }
})
const pageTitle = computed(() => pageMeta.value.title)
const pageSubtitle = computed(() => pageMeta.value.subtitle)
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
  background: var(--bg-base);
}

/* ---- Sidebar ---- */
.sider {
  background: var(--bg-surface) !important;
  border-right: 1px solid var(--border) !important;
  display: flex;
  flex-direction: column;
}

.logo {
  height: 60px;
  display: flex;
  align-items: center;
  justify-content: flex-start;
  gap: 10px;
  padding: 0 16px;
  border-bottom: 1px solid var(--border);
  animation: fadeIn 0.25s var(--ease-out);
}

.logo-mark {
  width: 32px;
  height: 32px;
  border-radius: var(--radius-md);
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--accent);
  color: #fff;
  font-size: 12px;
  font-weight: 700;
}

.logo-copy {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.logo-text {
  font-family: var(--font-display);
  font-size: 15px;
  font-weight: 700;
  color: var(--text-primary);
}
.logo-subtitle {
  font-size: 11px;
  color: var(--text-muted);
  line-height: 1.1;
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
  justify-content: space-between;
  gap: 16px;
  padding: 0 24px;
  height: 60px !important;
}

.header-title {
  font-family: var(--font-display);
  font-size: 15px;
  font-weight: 700;
  color: var(--text-primary);
}

.header-subtitle {
  margin-top: 2px;
  font-size: 12px;
  color: var(--text-muted);
}

.header-status {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 5px 10px;
  border: 1px solid var(--border);
  border-radius: 999px;
  color: var(--text-secondary);
  font-size: 12px;
  background: var(--bg-hover);
}
.status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--success);
}

/* ---- Content ---- */
.content {
  background: var(--bg-base) !important;
  padding: 20px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.content > :deep(*) {
  flex: 1;
  min-height: 0;
}
</style>
