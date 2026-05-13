<!--
  知识库管理页

  文档列表 + 上传 PDF + 一键处理（OCR → Markdown → Milvus 入库）+ 删除
-->
<template>
  <div class="knowledge-page">
    <!-- 顶部操作栏 -->
    <div class="page-header">
      <h3>知识库管理</h3>
      <a-upload
        :auto-upload="false"
        :show-file-list="false"
        accept=".pdf"
        @change="onFileSelect"
      >
        <template #upload-button>
          <a-button type="primary" :loading="store.uploading">
            <template #icon><icon-upload /></template>
            上传 PDF
          </a-button>
        </template>
      </a-upload>
    </div>

    <!-- 文档列表 -->
    <a-table
      :data="store.documents"
      :loading="store.loading"
      :pagination="{ pageSize: 10 }"
      row-key="id"
    >
      <template #columns>
        <a-table-column title="文件名" data-index="filename" :width="240" />
        <a-table-column title="状态" :width="120">
          <template #cell="{ record }">
            <a-tag :color="statusColor(record.status)">{{ statusLabel(record.status) }}</a-tag>
          </template>
        </a-table-column>
        <a-table-column title="文档片段" data-index="doc_count" :width="100" />
        <a-table-column title="含图文档" data-index="image_count" :width="100" />
        <a-table-column title="上传时间" data-index="created_at" :width="180" />
        <a-table-column title="操作" :width="220">
          <template #cell="{ record }">
            <a-space>
              <a-button
                v-if="record.status === 'uploaded' || record.status === 'failed'"
                type="primary"
                size="small"
                @click="store.process(record.id)"
              >
                处理入库
              </a-button>
              <a-popconfirm content="确认删除？将从知识库中移除。" @ok="store.remove(record.id)">
                <a-button status="danger" size="small">删除</a-button>
              </a-popconfirm>
            </a-space>
          </template>
        </a-table-column>
      </template>
      <template #empty>
        <a-empty description="暂无文档，上传 PDF 开始" />
      </template>
    </a-table>

    <!-- 错误提示 -->
    <a-alert
      v-for="doc in store.documents.filter((d: any) => d.status === 'failed')"
      :key="'err-' + doc.id"
      type="error"
      :title="`${doc.filename} 处理失败`"
      style="margin-top: 12px"
    >
      {{ doc.error_msg }}
    </a-alert>
  </div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { IconUpload } from '@arco-design/web-vue/es/icon'
import { useKnowledgeStore } from '../../stores/knowledge'

const store = useKnowledgeStore()

onMounted(() => {
  store.fetchDocuments()
})

function onFileSelect(fileItem: any) {
  const file = fileItem.file?.file || fileItem
  if (!(file instanceof File)) return
  if (!file.name.toLowerCase().endsWith('.pdf')) {
    window.alert('仅支持 PDF 文件')
    return
  }
  store.upload(file)
}

function statusColor(status: string): string {
  const map: Record<string, string> = {
    uploaded: 'arcoblue',
    parsing: 'orange',
    parsed: 'cyan',
    saving: 'orange',
    completed: 'green',
    failed: 'red',
  }
  return map[status] || 'gray'
}

function statusLabel(status: string): string {
  const map: Record<string, string> = {
    uploaded: '已上传',
    parsing: '解析中',
    parsed: '已解析',
    saving: '入库中',
    completed: '已完成',
    failed: '失败',
  }
  return map[status] || status
}
</script>

<style scoped>
.knowledge-page {
  background: #fff;
  border-radius: 8px;
  padding: 20px 24px;
  height: 100%;
  overflow-y: auto;
}
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.page-header h3 {
  margin: 0;
  font-size: 18px;
  color: #1d2129;
}
</style>
