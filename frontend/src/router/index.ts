/**
 * Vue Router 路由配置
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
      path: '/retrieval-test',
      name: 'RetrievalTest',
      component: () => import('../components/retrieval-test/RetrievalTestView.vue'),
    },
    {
      path: '/documents/:documentId',
      name: 'DocumentDetail',
      component: () => import('../components/documents/DocumentDetailView.vue'),
    },
    {
      path: '/settings',
      name: 'Settings',
      component: () => import('../components/settings/SettingsView.vue'),
    },
    {
      path: '/acl-audit',
      name: 'AclAudit',
      component: () => import('../components/admin/AclAuditView.vue'),
    },
  ],
})

export default router
