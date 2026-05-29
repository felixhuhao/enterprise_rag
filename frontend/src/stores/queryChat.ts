/**
 * 知识查询聊天状态管理 (Pinia Store)
 *
 * 管理 query chat 的会话、消息列表、SSE 流式状态
 * 后端 SSE 事件: message_start | retrieval_step | rerank | trace | delta | citations | message_end
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { connectSSE, type SSEEvent } from '../utils/sse'

/** 引用信息 */
export interface Citation {
  id: string
  chunk_id?: number | null
  document_id?: string
  file_title?: string
  entity_name?: string
  section_title?: string
  page?: number | null
  table_id?: string
  source_type?: string
  image_paths?: string[]
}

/** multi-hop trace entry */
export interface HopTraceEntry {
  hop: number
  query?: string
  entity_filter?: string
  result_count: number
  status: string
  discovered_entities?: string[]
  per_entity_counts?: Record<string, number>
}

export interface FallbackInfo {
  used: boolean
  blocked: boolean
  type: string
  reason: string
  original_filter: string
}

/** 检索步骤信息 */
export interface RetrievalInfo {
  results_count: number
  entity: string
  rewritten_query: string
  search_mode: string
  search_mode_hyde: string
  entity_mode: string
  matched_entities: string[]
  per_entity_counts: Record<string, number>
  hop_plan?: string
  hop_trace?: HopTraceEntry[]
  retrieval_flavor?: string
  strict_evidence?: boolean
  query_plan?: Record<string, unknown>
  fallback_info?: FallbackInfo
}

/** groundedness claim */
export interface GroundednessClaim {
  claim: string
  claim_type?: 'factual' | 'no_answer'
  verdict: 'supported' | 'partially_supported' | 'unsupported' | 'contradicted'
  evidence: string | null
  citation_ids: string[]
}

/** groundedness 结果 */
export interface GroundednessResult {
  enabled: boolean
  status: 'ok' | 'skipped' | 'unavailable'
  groundedness_score: number | null
  claims: GroundednessClaim[]
  warning: string | null
}

/** rerank debug 条目 */
export interface RerankItem {
  index: number
  file_title: string
  section_title: string
  source_type: string
  llm_score: number
  rrf_score: number
  final_score: number
}

/** 检索链路耗时 */
export interface TraceData {
  entity_confirm_ms?: number
  rewrite_ms?: number
  search_hyde_ms?: number
  rrf_fusion_ms?: number
  table_expand_ms?: number
  rerank_ms?: number
  post_rerank_fallback_ms?: number
  build_prompt_ms?: number
  retrieval_wall_ms?: number
  first_token_ms?: number | null
  generate_ms?: number
  total_ms?: number
}

/** 聊天消息 */
export interface QueryChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  citations?: Citation[]
  groundedness?: GroundednessResult
  retrievalInfo?: RetrievalInfo
  rerankItems?: RerankItem[]
  trace?: TraceData
}

/** 结构化错误 */
export interface AppError {
  code: string
  message: string
  hint?: string
}

/** 中文建议 */
import { ERROR_HINTS } from '../utils/errorHints'

export const useQueryChatStore = defineStore('queryChat', () => {
  // ---- 响应式状态 ----

  /** 当前会话 ID（前端生成 UUID，不依赖后端创建） */
  const sessionId = ref('')

  /** 消息列表 */
  const messages = ref<QueryChatMessage[]>([])

  /** 是否正在流式接收 */
  const isStreaming = ref(false)

  /** 错误信息 */
  const error = ref<AppError | null>(null)

  /** Query debug config — 本次会话级别，不持久化 */
  const debugConfig = ref({
    retrieval_flavor: 'balanced',
    strict_evidence: false,
    use_groundedness: false,
  })

  /** 当前 SSE 连接的 AbortController */
  let abortController: AbortController | null = null

  /** 当前 AI 消息 ID（用于 SSE 流式更新） */
  let currentAssistantId = ''

  // ---- Actions ----

  /** 确保有 sessionId */
  function ensureSession() {
    if (!sessionId.value) {
      sessionId.value = crypto.randomUUID()
    }
  }

  /** 找到当前 assistant 消息并更新 */
  function updateAssistant(patch: Partial<QueryChatMessage>) {
    const msg = messages.value.find((m) => m.id === currentAssistantId)
    if (msg) {
      Object.assign(msg, patch)
    }
  }

  /** 发送查询消息 */
  function sendMessage(query: string) {
    if (!query.trim() || isStreaming.value) return
    ensureSession()

    // 添加用户消息
    messages.value.push({
      id: crypto.randomUUID(),
      role: 'user',
      content: query.trim(),
    })

    isStreaming.value = true
    error.value = null

    // 添加 AI 占位消息
    currentAssistantId = crypto.randomUUID()
    messages.value.push({ id: currentAssistantId, role: 'assistant', content: '' })

    // 发起 SSE 连接
    abortController = connectSSE(
      '/query/chat/stream',
      {
        session_id: sessionId.value,
        query: query.trim(),
        config: {
          retrieval_flavor: debugConfig.value.retrieval_flavor,
          strict_evidence: debugConfig.value.strict_evidence,
          use_groundedness: debugConfig.value.use_groundedness,
        },
      },
      (event: SSEEvent) => handleEvent(event),
      (err: any) => {
        isStreaming.value = false
        error.value = { code: 'UNKNOWN_ERROR', message: err.message || '连接失败', hint: '网络连接异常，请稍后重试' }
      },
      () => {
        isStreaming.value = false
      },
    )
  }

  /** 处理 SSE 事件 */
  function handleEvent(event: SSEEvent) {
    switch (event.type) {
      case 'message_start':
        break

      case 'retrieval_step':
        updateAssistant({
          retrievalInfo: {
            results_count: (event as any).results_count ?? 0,
            entity: (event as any).entity ?? '',
            rewritten_query: (event as any).rewritten_query ?? '',
            search_mode: (event as any).search_mode ?? '',
            search_mode_hyde: (event as any).search_mode_hyde ?? '',
            entity_mode: (event as any).entity_mode ?? 'none',
            matched_entities: (event as any).matched_entities ?? [],
            per_entity_counts: (event as any).per_entity_counts ?? {},
            hop_plan: (event as any).hop_plan ?? 'direct',
            hop_trace: (event as any).hop_trace ?? [],
            retrieval_flavor: (event as any).retrieval_flavor ?? 'balanced',
            strict_evidence: (event as any).strict_evidence ?? false,
            query_plan: (event as any).query_plan ?? {},
            fallback_info: (event as any).fallback_info ?? undefined,
          },
        })
        break

      case 'rerank':
        updateAssistant({
          rerankItems: (event as any).results ?? [],
        })
        break

      case 'trace':
        {
          const msg = messages.value.find((m) => m.id === currentAssistantId)
          if (msg) {
            msg.trace = { ...msg.trace, ...(event as any).trace }
          }
        }
        break

      case 'delta':
        {
          const msg = messages.value.find((m) => m.id === currentAssistantId)
          if (msg) {
            msg.content += (event as any).content ?? ''
          }
        }
        break

      case 'citations':
        updateAssistant({
          citations: (event as any).citations ?? [],
        })
        break

      case 'groundedness':
        updateAssistant({
          groundedness: {
            enabled: (event as any).enabled ?? false,
            status: (event as any).status ?? 'unavailable',
            groundedness_score: (event as any).groundedness_score ?? null,
            claims: (event as any).claims ?? [],
            warning: (event as any).warning ?? null,
          },
        })
        break

      case 'message_end':
        isStreaming.value = false
        break

      case 'error':
        {
          const code = (event as any).code ?? 'UNKNOWN_ERROR'
          error.value = {
            code,
            message: (event as any).message ?? '未知错误',
            hint: ERROR_HINTS[code] ?? '未知错误，请稍后重试',
          }
        }
        isStreaming.value = false
        break
    }
  }

  /** 中止当前流式连接 */
  function stopStreaming() {
    abortController?.abort()
    abortController = null
    isStreaming.value = false
  }

  /** 清空所有消息和状态 */
  function clearMessages() {
    messages.value = []
    sessionId.value = ''
    error.value = null
  }

  return {
    sessionId,
    messages,
    isStreaming,
    error,
    debugConfig,
    sendMessage,
    stopStreaming,
    clearMessages,
  }
})
