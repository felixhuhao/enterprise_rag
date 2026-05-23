/**
 * Vue 应用入口
 *
 * 注册全局插件：Pinia 状态管理、Vue Router 路由、Arco Design 组件库
 */
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ArcoVue from '@arco-design/web-vue'
import '@arco-design/web-vue/dist/arco.css'
import App from './App.vue'
import router from './router'
import './styles/global.css'

const app = createApp(App)
app.use(createPinia())  // 状态管理
app.use(router)         // 路由
app.use(ArcoVue)        // UI 组件库
app.mount('#app')
