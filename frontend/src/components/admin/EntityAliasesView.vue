<template>
  <div class="alias-page">
    <div class="alias-header">
      <div>
        <h3>实体别名</h3>
        <p>维护查询时使用的简称、缩写和英文别名。</p>
      </div>
      <a-button size="small" :loading="loading" @click="loadAliases">刷新</a-button>
    </div>

    <div v-if="!authStore.isAdmin" class="alias-forbidden">
      <a-empty description="仅管理员可管理实体别名" />
    </div>

    <a-spin v-else :loading="loading" style="width: 100%">
      <div class="alias-tools">
        <div class="alias-form">
          <a-input v-model="aliasInput" placeholder="别名，如 SMIC" allow-clear />
          <a-input v-model="canonicalInput" placeholder="标准实体，如 中芯国际" allow-clear />
          <a-button type="primary" :loading="saving" @click="onCreate">新增</a-button>
        </div>

        <div class="batch-box">
          <a-textarea
            v-model="batchInput"
            placeholder="批量导入：每行一个映射，格式为 别名,标准实体"
            :auto-size="{ minRows: 3, maxRows: 6 }"
          />
          <div class="batch-actions">
            <span class="hint">重复映射会自动跳过；标准实体必须已存在于索引。</span>
            <a-button size="small" :loading="batchSaving" @click="onBatchCreate">批量导入</a-button>
          </div>
        </div>
      </div>

      <a-table
        :data="records"
        :pagination="{ pageSize: 20 }"
        row-key="id"
        size="small"
      >
        <template #columns>
          <a-table-column title="别名" data-index="alias" :width="180" />
          <a-table-column title="标准实体" data-index="canonical_entity" />
          <a-table-column title="来源" data-index="source" :width="90">
            <template #cell="{ record }">
              <a-tag size="small">{{ record.source }}</a-tag>
            </template>
          </a-table-column>
          <a-table-column title="创建时间" data-index="created_at" :width="180" />
          <a-table-column title="操作" :width="90" align="right">
            <template #cell="{ record }">
              <a-popconfirm content="删除这条别名映射？" @ok="onDelete(record.id)">
                <a-button size="mini" status="danger">删除</a-button>
              </a-popconfirm>
            </template>
          </a-table-column>
        </template>
      </a-table>
    </a-spin>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useAuthStore } from '../../stores/auth'
import {
  batchCreateEntityAliases,
  createEntityAlias,
  deleteEntityAlias,
  listEntityAliases,
  type EntityAliasRecord,
  type EntityAliasBatchItem,
} from '../../api/entityAliases'

const authStore = useAuthStore()
const loading = ref(false)
const saving = ref(false)
const batchSaving = ref(false)
const records = ref<EntityAliasRecord[]>([])
const aliasInput = ref('')
const canonicalInput = ref('')
const batchInput = ref('')

onMounted(async () => {
  if (!authStore.currentUser) await authStore.fetchMe()
  if (authStore.isAdmin) await loadAliases()
})

async function loadAliases() {
  loading.value = true
  try {
    const data = await listEntityAliases()
    records.value = data.records
  } finally {
    loading.value = false
  }
}

async function onCreate() {
  const alias = aliasInput.value.trim()
  const canonical = canonicalInput.value.trim()
  if (!alias || !canonical) {
    Message.warning('请输入别名和标准实体')
    return
  }
  saving.value = true
  try {
    await createEntityAlias(alias, canonical)
    aliasInput.value = ''
    canonicalInput.value = ''
    Message.success('已新增别名映射')
    await loadAliases()
  } catch (err: any) {
    Message.error(err?.response?.data?.detail || '新增失败')
  } finally {
    saving.value = false
  }
}

async function onBatchCreate() {
  const items = parseBatchInput(batchInput.value)
  if (!items.length) {
    Message.warning('请输入可导入的映射')
    return
  }
  batchSaving.value = true
  try {
    const result = await batchCreateEntityAliases(items)
    const suffix = result.errors.length ? `，${result.errors.length} 条失败` : ''
    Message.success(`新增 ${result.created} 条，跳过 ${result.skipped} 条${suffix}`)
    batchInput.value = ''
    await loadAliases()
  } catch (err: any) {
    Message.error(err?.response?.data?.detail || '批量导入失败')
  } finally {
    batchSaving.value = false
  }
}

async function onDelete(id: number) {
  try {
    await deleteEntityAlias(id)
    Message.success('已删除')
    await loadAliases()
  } catch (err: any) {
    Message.error(err?.response?.data?.detail || '删除失败')
  }
}

function parseBatchInput(value: string): EntityAliasBatchItem[] {
  return value
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const separator = line.includes('\t') ? '\t' : ','
      const [alias = '', canonical = ''] = line.split(separator)
      return {
        alias: alias.trim(),
        canonical_entity: canonical.trim(),
        source: 'admin',
      }
    })
    .filter((item) => item.alias && item.canonical_entity)
}
</script>

<style scoped>
.alias-page {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 20px;
  height: 100%;
  overflow-y: auto;
  animation: fadeIn 0.22s var(--ease-out);
}

.alias-header {
  margin-bottom: 16px;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}
.alias-header h3 { margin: 0; font-size: 18px; font-weight: 700; color: var(--text-primary); }
.alias-header p { margin: 6px 0 0; color: var(--text-muted); font-size: 13px; }

.alias-forbidden { padding: 60px 0; }

.alias-tools {
  display: grid;
  gap: 12px;
  margin-bottom: 16px;
}

.alias-form {
  display: grid;
  grid-template-columns: minmax(160px, 220px) minmax(220px, 1fr) auto;
  gap: 8px;
  align-items: center;
}

.batch-box {
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 10px;
  background: var(--bg-base);
}

.batch-actions {
  margin-top: 8px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.hint {
  color: var(--text-muted);
  font-size: 12px;
}
</style>
