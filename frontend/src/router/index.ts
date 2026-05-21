/**
 * Vue Router 路由配置
 *
 * 路由列表：聊天页、评估看板、设置页
 */
import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      redirect: '/query-chat',
    },
    {
      path: '/query-chat',
      name: 'QueryChat',
      component: () => import('../components/query-chat/QueryChatView.vue'),
    },
    {
      path: '/chat',
      name: 'Chat',
      component: () => import('../components/chat/ChatView.vue'),
    },
    {
      path: '/evaluate',
      name: 'Evaluate',
      component: () => import('../components/evaluate/EvaluateView.vue'),
    },
    {
      path: '/documents',
      name: 'Documents',
      component: () => import('../components/documents/DocumentsView.vue'),
    },
    {
      path: '/settings',
      name: 'Settings',
      component: () => import('../components/settings/SettingsView.vue'),
    },
  ],
})

export default router
