<template>
  <div class="panel">
    <!-- ── Section 1: 访问授权 ── -->
    <div class="section-header">
      <h3>访问授权</h3>
    </div>

    <a-spin :loading="aclLoading" style="width: 100%">
      <a-table
        :data="entityData"
        :pagination="{ pageSize: 10 }"
        size="small"
        row-key="entity_name"
      >
        <template #columns>
          <a-table-column title="实体名称" data-index="entity_name" />
          <a-table-column title="文档数" data-index="document_count" :width="80" />
          <a-table-column title="授权">
            <template #cell="{ record }">
              <div class="grant-list">
                <a-tag
                  v-for="g in record.grants"
                  :key="g.user_id"
                  :color="g.permission === 'write' ? 'green' : 'arcoblue'"
                  size="small"
                  closable
                  @close="handleRevoke(record.entity_name, g.user_id)"
                >
                  {{ g.username }} ({{ g.permission === 'write' ? '编辑' : '查看' }})
                </a-tag>
                <a-button size="mini" @click="openGrant(record.entity_name)">授权</a-button>
              </div>
            </template>
          </a-table-column>
        </template>
      </a-table>
    </a-spin>

    <a-divider />

    <!-- ── Section 2: 实体别名 ── -->
    <div class="section-header">
      <h3>实体别名</h3>
    </div>

    <a-spin :loading="aliasLoading" style="width: 100%">
      <div class="alias-tools">
        <div class="alias-form">
          <a-input v-model="aliasInput" placeholder="别名，如 SMIC" allow-clear />
          <a-input v-model="canonicalInput" placeholder="标准实体，如 中芯国际" allow-clear />
          <a-button type="primary" :loading="aliasSaving" @click="onCreateAlias">新增</a-button>
        </div>

        <details class="batch-box">
          <summary>
            <span>批量导入</span>
            <small>每行一个映射：别名,标准实体</small>
          </summary>
          <a-textarea
            v-model="batchInput"
            placeholder="每行一个映射，格式为 别名,标准实体"
            :auto-size="{ minRows: 3, maxRows: 6 }"
          />
          <div class="batch-actions">
            <span class="hint">重复映射会自动跳过；标准实体必须已存在于索引。</span>
            <a-button size="small" :loading="batchSaving" @click="onBatchCreate">批量导入</a-button>
          </div>
        </details>
      </div>

      <a-table
        :data="aliasRecords"
        :pagination="{ pageSize: 10 }"
        row-key="id"
        size="small"
      >
        <template #columns>
          <a-table-column title="别名" data-index="alias" />
          <a-table-column title="标准实体" data-index="canonical_entity" />
          <a-table-column title="来源" data-index="source" :width="90">
            <template #cell="{ record }">
              <a-tag size="small">{{ record.source }}</a-tag>
            </template>
          </a-table-column>
          <a-table-column title="操作" :width="90" align="right">
            <template #cell="{ record }">
              <a-popconfirm content="删除这条别名映射？" @ok="onDeleteAlias(record.id)">
                <a-button size="mini" status="danger">删除</a-button>
              </a-popconfirm>
            </template>
          </a-table-column>
        </template>
      </a-table>
    </a-spin>

    <!-- 授权对话框 -->
    <a-modal v-model:visible="showGrant" title="授予实体权限" :footer="false">
      <p>实体: <strong>{{ grantEntity }}</strong></p>
      <a-select v-model="grantForm.userId" placeholder="选择用户" style="width: 100%; margin-bottom: 12px">
        <a-option v-for="u in grantableUsers" :key="u.user_id" :value="u.user_id">{{ u.username }}</a-option>
      </a-select>
      <a-select v-model="grantForm.permission" style="width: 100%; margin-bottom: 12px">
        <a-option value="read">查看 (read)</a-option>
        <a-option value="write">编辑 (write)</a-option>
      </a-select>
      <div class="modal-actions">
        <a-button @click="showGrant = false">取消</a-button>
        <a-button type="primary" :loading="actionLoading" @click="handleGrant">确认</a-button>
      </div>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, reactive, computed } from 'vue'
import { Message } from '@arco-design/web-vue'
import {
  listUsers,
  getEntityAclOverview,
  grantEntityAccess,
  revokeEntityAccess,
  type UserInfo,
  type EntityAclEntry,
} from '../../api/adminUsers'
import {
  batchCreateEntityAliases,
  createEntityAlias,
  deleteEntityAlias,
  listEntityAliases,
  type EntityAliasRecord,
  type EntityAliasBatchItem,
} from '../../api/entityAliases'

// ── Alias state ──
const aliasLoading = ref(false)
const aliasSaving = ref(false)
const batchSaving = ref(false)
const aliasRecords = ref<EntityAliasRecord[]>([])
const aliasInput = ref('')
const canonicalInput = ref('')
const batchInput = ref('')

// ── ACL state ──
const aclLoading = ref(false)
const actionLoading = ref(false)
const users = ref<UserInfo[]>([])
const entityData = ref<EntityAclEntry[]>([])
const showGrant = ref(false)
const grantEntity = ref('')
const grantForm = reactive({ userId: '', permission: 'read' })

const grantableUsers = computed(() => users.value.filter((u) => u.role !== 'admin'))

onMounted(() => {
  loadAliases()
  loadAcl()
})

// ── Alias functions ──
async function loadAliases() {
  aliasLoading.value = true
  try {
    const data = await listEntityAliases()
    aliasRecords.value = data.records
  } finally {
    aliasLoading.value = false
  }
}

async function onCreateAlias() {
  const alias = aliasInput.value.trim()
  const canonical = canonicalInput.value.trim()
  if (!alias || !canonical) {
    Message.warning('请输入别名和标准实体')
    return
  }
  aliasSaving.value = true
  try {
    await createEntityAlias(alias, canonical)
    aliasInput.value = ''
    canonicalInput.value = ''
    Message.success('已新增别名映射')
    await loadAliases()
  } catch (err: any) {
    Message.error(err?.response?.data?.detail || '新增失败')
  } finally {
    aliasSaving.value = false
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

async function onDeleteAlias(id: number) {
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
      return { alias: alias.trim(), canonical_entity: canonical.trim(), source: 'admin' }
    })
    .filter((item) => item.alias && item.canonical_entity)
}

// ── ACL functions ──
async function loadAcl() {
  aclLoading.value = true
  try {
    const [u, e] = await Promise.all([listUsers(), getEntityAclOverview()])
    users.value = u
    entityData.value = e.entities
  } catch (err: any) {
    Message.error(err?.response?.data?.detail || '加载失败')
  } finally {
    aclLoading.value = false
  }
}

function openGrant(entityName: string) {
  grantEntity.value = entityName
  grantForm.userId = ''
  grantForm.permission = 'read'
  showGrant.value = true
}

async function handleGrant() {
  if (!grantForm.userId) {
    Message.warning('请选择用户')
    return
  }
  actionLoading.value = true
  try {
    await grantEntityAccess(grantEntity.value, grantForm.userId, grantForm.permission)
    Message.success('授权成功')
    showGrant.value = false
    await loadAcl()
  } catch (err: any) {
    Message.error(err?.response?.data?.detail || '授权失败')
  } finally {
    actionLoading.value = false
  }
}

async function handleRevoke(entityName: string, userId: string) {
  try {
    await revokeEntityAccess(entityName, userId)
    Message.success('已撤销')
    await loadAcl()
  } catch (err: any) {
    Message.error(err?.response?.data?.detail || '撤销失败')
  }
}
</script>

<style scoped>
.panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.section-header h3 {
  margin: 0;
  font-size: 15px;
  font-weight: 700;
}

.alias-tools {
  display: grid;
  gap: 10px;
  margin-bottom: 8px;
}

.alias-form {
  display: grid;
  grid-template-columns: minmax(150px, 220px) minmax(220px, 1fr) auto;
  gap: 8px;
  align-items: center;
}

.batch-box {
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--bg-base);
}

.batch-box summary {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 10px;
  cursor: pointer;
  color: var(--text-primary);
  font-size: 13px;
  font-weight: 600;
  list-style: none;
}

.batch-box summary::-webkit-details-marker {
  display: none;
}

.batch-box summary::after {
  content: '展开';
  margin-left: auto;
  color: var(--text-muted);
  font-size: 12px;
  font-weight: 400;
}

.batch-box[open] summary::after {
  content: '收起';
}

.batch-box summary small {
  color: var(--text-muted);
  font-size: 12px;
  font-weight: 400;
}

.batch-box :deep(.arco-textarea-wrapper) {
  margin: 0 10px;
  width: calc(100% - 20px);
}

.batch-actions {
  padding: 8px 10px 10px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.hint {
  color: var(--text-muted);
  font-size: 12px;
}

.grant-list {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  align-items: center;
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
</style>
