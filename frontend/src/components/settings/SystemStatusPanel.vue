<template>
  <div>
    <div class="status-grid">
      <div class="status-card">
        <span class="status-label">后端 API</span>
        <strong :class="loadError ? 'bad' : 'ok'">{{ loadError ? '异常' : '正常' }}</strong>
        <small>{{ loadError || '设置接口可访问' }}</small>
      </div>
      <div class="status-card">
        <span class="status-label">当前用户</span>
        <strong>{{ username || '未知' }}</strong>
        <small>{{ userId || '未读取到用户信息' }}</small>
      </div>
      <div class="status-card">
        <span class="status-label">权限</span>
        <strong>{{ isAdmin ? '管理员' : '普通用户' }}</strong>
        <small>{{ isAdmin ? '可修改系统设置' : '仅可查看当前设置' }}</small>
      </div>
      <div class="status-card">
        <span class="status-label">配置加载</span>
        <strong :class="settingsCount ? 'ok' : ''">{{ settingsCount ? '已加载' : '未加载' }}</strong>
        <small>{{ loadedAt || '尚未刷新' }}</small>
      </div>
    </div>

    <div class="info-panel">
      <div class="panel-title">模型与服务</div>
      <div class="info-list">
        <div class="info-row">
          <span>聊天模型</span>
          <strong>{{ chatModel || '未读取' }}</strong>
        </div>
        <div class="info-row">
          <span>Embedding</span>
          <strong>{{ embeddingLabel }}</strong>
        </div>
        <div class="info-row">
          <span>向量库（backend）</span>
          <strong>{{ backendMilvusLabel }}</strong>
        </div>
        <div class="info-row">
          <span>向量库（宿主机）</span>
          <strong>{{ hostMilvusUri }}</strong>
        </div>
        <div class="info-row">
          <span>数据库（backend）</span>
          <strong>{{ backendDatabaseLabel }}</strong>
        </div>
        <div class="info-row">
          <span>Token</span>
          <strong>{{ tokenStatus }}</strong>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  loadError: string
  username: string
  userId: string
  isAdmin: boolean
  settingsCount: number
  loadedAt: string
  chatModel: string
  embeddingLabel: string
  backendMilvusLabel: string
  hostMilvusUri: string
  backendDatabaseLabel: string
  tokenStatus: string
}>()
</script>

<style scoped>
.status-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.status-card,
.info-panel {
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: #fbfdff;
}

.status-card {
  display: grid;
  gap: 6px;
  padding: 14px;
}

.status-label,
.status-card small,
.info-row span {
  color: var(--text-muted);
  font-size: 12px;
}

.status-card strong {
  color: var(--text-primary);
  font-size: 16px;
  font-variant-numeric: tabular-nums;
}

.status-card strong.ok {
  color: #166534;
}

.status-card strong.bad {
  color: #991b1b;
}

.info-panel {
  margin-top: 14px;
  padding: 14px;
}

.panel-title {
  margin-bottom: 10px;
  font-size: 13px;
  font-weight: 700;
  color: var(--text-secondary);
}

.info-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px 18px;
}

.info-row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  min-width: 0;
}

.info-row strong {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 600;
}

@media (max-width: 1100px) {
  .status-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 760px) {
  .status-grid,
  .info-list {
    grid-template-columns: 1fr;
  }
}
</style>
