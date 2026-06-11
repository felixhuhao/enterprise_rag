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
          {{ authStore.isAdmin ? '文档管理' : '知识库文档' }}
        </a-menu-item>
        <a-menu-item v-if="authStore.isAdmin" key="/entity-aliases">
          <template #icon><icon-safe /></template>
          实体别名
        </a-menu-item>
        <a-menu-item v-if="authStore.isAdmin" key="/acl-audit">
          <template #icon><icon-safe /></template>
          权限审计
        </a-menu-item>
        <a-menu-item key="/evaluate">
          <template #icon><icon-bar-chart /></template>
          {{ authStore.isAdmin ? '质量中心' : '查询记录' }}
        </a-menu-item>
        <a-menu-item v-if="authStore.isAdmin" key="/retrieval-test">
          <template #icon><icon-search /></template>
          检索测试
        </a-menu-item>
        <a-menu-item v-if="authStore.isAdmin" key="/settings">
          <template #icon><icon-settings /></template>
          系统设置
        </a-menu-item>
      </a-menu>
      <!-- Demo 用户切换 -->
      <div class="sider-footer">
        <div class="user-label">Demo 用户</div>
        <div class="user-switcher">
          <a-select
            :model-value="currentUserToken"
            size="small"
            @change="onUserSwitch"
          >
            <a-option value="alice-demo-token">Alice（星辰科技）</a-option>
            <a-option value="bob-demo-token">Bob（远景能源）</a-option>
            <a-option v-if="isCustomToken" :value="currentUserToken">自定义 Token</a-option>
          </a-select>
          <div class="custom-token">
            <a-input-password
              v-model="customToken"
              placeholder="自定义 Token"
              size="small"
              @keydown.enter="saveCustomToken"
            />
            <a-button size="mini" @click="saveCustomToken">保存</a-button>
          </div>
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
          <span>就绪</span>
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
import { useAuthStore } from '../../stores/auth'
import {
  IconStorage,
  IconBarChart,
  IconSettings,
  IconSafe,
  IconSearch,
} from '@arco-design/web-vue/es/icon'

const router = useRouter()
const route = useRoute()

const currentRoute = computed(() => {
  if (route.path.startsWith('/documents/')) return '/documents'
  if (route.path === '/evaluation' || route.path === '/feedback') return '/evaluate'
  return route.path
})
const pageMeta = computed(() => {
  const isAdmin = authStore.isAdmin
  const map: Record<string, { title: string; subtitle: string }> = {
    '/query-chat': { title: '知识查询', subtitle: '基于引用、检索链路和耗时追踪回答问题。' },
    '/documents': {
      title: isAdmin ? '文档管理' : '知识库文档',
      subtitle: isAdmin ? '上传、处理、重试和修复知识库文档。' : '查看可访问的知识库文档。',
    },
    '/retrieval-test': { title: '检索测试', subtitle: '检查检索链路、扩展查询、预算和 Top K 切片。' },
    '/evaluate': {
      title: isAdmin ? '质量中心' : '查询记录',
      subtitle: isAdmin ? '查询监控、检索记录、答案反馈和基准测试集回归评测。' : '查看自己的查询记录和反馈。',
    },
    '/evaluation': { title: '回归评测', subtitle: '基准测试集质量验证、通过率、失败用例。' },
    '/settings': { title: '系统设置', subtitle: '配置模型、检索和运行时行为。' },
    '/acl-audit': { title: '权限审计', subtitle: '查看文档 ACL、owner/read 分配和清理状态。' },
    '/entity-aliases': { title: '实体别名', subtitle: '维护企业简称、缩写和英文别名，用于查询路由。' },
    '/feedback': { title: '答案反馈', subtitle: '用户反馈记录和基准测试集草稿管理。' },
  }
  return map[route.path] ?? { title: 'Enterprise RAG', subtitle: '知识库运行控制台。' }
})
const pageTitle = computed(() => pageMeta.value.title)
const pageSubtitle = computed(() => pageMeta.value.subtitle)
const DEMO_TOKENS: Record<string, string> = {
  'Alice（星辰科技）': 'alice-demo-token',
  'Bob（远景能源）': 'bob-demo-token',
}

const customToken = ref('')
const currentUserToken = ref(DEMO_TOKENS['Admin（全部文档）'])

function onMenuClick(key: string) {
  router.push(key)
}

const authStore = useAuthStore()

onMounted(() => {
  const stored = localStorage.getItem('api_token')
  if (stored) {
    currentUserToken.value = stored
  } else {
    localStorage.setItem('api_token', currentUserToken.value)
  }
  authStore.fetchMe()
})

function switchUser(token: string) {
  localStorage.setItem('api_token', token)
  currentUserToken.value = token
  window.location.reload()
}

const isCustomToken = computed(() =>
  currentUserToken.value !== '' && !Object.values(DEMO_TOKENS).includes(currentUserToken.value),
)

function onUserSwitch(value: unknown) {
  if (typeof value !== 'string') return
  switchUser(value)
}

function saveCustomToken() {
  const trimmed = customToken.value.trim()
  if (!trimmed) return
  switchUser(trimmed)
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
  width: 34px;
  height: 34px;
  border-radius: var(--radius-md);
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, var(--accent), var(--accent-active));
  color: #fff;
  font-family: var(--font-mono);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.02em;
  box-shadow: 0 2px 8px var(--accent-glow);
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
  letter-spacing: -0.01em;
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

.user-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-muted);
  margin-bottom: 6px;
}

.user-switcher {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.custom-token {
  display: flex;
  gap: 6px;
}
.custom-token :deep(.arco-input-password) {
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
  font-size: 16px;
  font-weight: 700;
  letter-spacing: -0.01em;
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
  gap: 7px;
  padding: 5px 12px;
  border: 1px solid var(--border);
  border-radius: 999px;
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 500;
  background: var(--bg-surface);
  box-shadow: var(--shadow-sm);
}
.status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--success);
  box-shadow: 0 0 0 3px rgba(22, 163, 74, 0.15);
}

/* ---- Content ---- */
.content {
  background: var(--bg-base) !important;
  padding: 18px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.content > :deep(*) {
  flex: 1;
  min-height: 0;
}
</style>
