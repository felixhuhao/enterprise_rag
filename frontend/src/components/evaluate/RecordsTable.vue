<!--
  评估记录表格（分页）
-->
<template>
  <a-card title="最近评估记录">
    <a-table
      :data="records"
      :pagination="{
        current: currentPage,
        total: total,
        pageSize: 20,
        showTotal: true,
      }"
      row-key="id"
      @page-change="onPageChange"
    >
      <template #columns>
        <a-table-column title="时间" data-index="created_at" :width="180" />
        <a-table-column title="用户输入" data-index="input_text" :ellipsis="true" />
        <a-table-column title="分数" :width="100">
          <template #cell="{ record }">
            <a-tag :color="record.score >= 0.8 ? 'green' : record.score >= 0.6 ? 'orange' : 'red'">
              {{ record.score.toFixed(2) }}
            </a-tag>
          </template>
        </a-table-column>
        <a-table-column title="网络搜索" :width="100">
          <template #cell="{ record }">
            {{ record.from_web_search ? '是' : '否' }}
          </template>
        </a-table-column>
      </template>
      <template #empty>
        <a-empty description="暂无评估数据，进行聊天对话后将自动收集" />
      </template>
    </a-table>
  </a-card>
</template>

<script setup lang="ts">
import type { EvaluateRecord } from '../../api/evaluate'

const props = defineProps<{
  records: EvaluateRecord[]
  total: number
  currentPage: number
}>()

const emit = defineEmits<{ 'page-change': [page: number] }>()

function onPageChange(page: number) {
  emit('page-change', page)
}
</script>
