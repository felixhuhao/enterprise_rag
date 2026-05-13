/**
 * Vue Router 路由配置
 *
 * 路由列表：聊天页、知识库管理、评估看板、设置页
 */
import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      redirect: '/chat',
    },
    {
      path: '/chat',
      name: 'Chat',
      component: () => import('../components/chat/ChatView.vue'),
    },
    {
      path: '/knowledge',
      name: 'Knowledge',
      component: () => import('../components/knowledge/KnowledgeView.vue'),
    },
    {
      path: '/evaluate',
      name: 'Evaluate',
      component: () => import('../components/evaluate/EvaluateView.vue'),
    },
    {
      path: '/settings',
      name: 'Settings',
      component: () => import('../components/settings/SettingsView.vue'),
    },
  ],
})

export default router
