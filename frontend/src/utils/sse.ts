/**
 * fetch-based SSE (Server-Sent Events) 处理器
 *
 * 为什么不用原生 EventSource？
 * - EventSource 只支持 GET 请求，而我们需要 POST（携带消息体）
 * - EventSource 无法自定义 Authorization 头
 *
 * 解决方案：用 fetch + ReadableStream 手动解析 SSE 协议
 */

/** SSE 事件结构（与后端 SSE 输出格式对应） */
export interface SSEEvent {
  type: string       // message_start | retrieval_step | rerank | trace | delta | citations | message_end | error
  data?: unknown
  [key: string]: unknown
}

const API_BASE = '/api'

/**
 * 建立 SSE 连接并监听事件流
 *
 * @param path API 路径，如 '/query/chat/stream'
 * @param body POST 请求体
 * @param onEvent 收到 SSE 事件的回调
 * @param onError 连接错误的回调
 * @param onComplete 流结束的回调
 * @returns AbortController，可用于中止连接
 */
export function connectSSE<TEvent extends SSEEvent = SSEEvent>(
  path: string,
  body: object,
  onEvent: (event: TEvent) => void,
  onError: (err: any) => void,
  onComplete: () => void,
): AbortController {
  const controller = new AbortController()
  const token = localStorage.getItem('api_token') || ''

  fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(body),
    signal: controller.signal,  // 支持通过 controller.abort() 取消请求
  })
    .then(async (response) => {
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`)
      }

      // 逐块读取响应流
      const reader = response.body!.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        // 将新数据拼接到缓冲区，按换行符分割
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''  // 保留最后一行（可能不完整）

        for (const line of lines) {
          const trimmed = line.trim()
          if (trimmed.startsWith('data:')) {
            try {
              const event = JSON.parse(trimmed.slice(5).trim()) as TEvent
              onEvent(event)
            } catch {
              // 忽略解析失败的行（如心跳空行）
            }
          }
        }
      }
      onComplete()
    })
    .catch((err) => {
      // AbortError 是主动取消，不算错误
      if (err.name !== 'AbortError') {
        onError(err)
      }
    })

  return controller
}
