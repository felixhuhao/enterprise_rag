/**
 * 错误码 → 中文提示映射
 * 后端 AppErrorCode 定义的错误码
 */

export const ERROR_HINTS: Record<string, string> = {
  MINERU_API_ERROR: '文档解析服务异常，请稍后重试',
  EMBEDDING_ERROR: '向量化服务异常，请稍后重试',
  MILVUS_ERROR: '向量数据库异常，请检查 Milvus 连接',
  LLM_ERROR: '大模型服务异常，请稍后重试',
  NO_CONTEXT_FOUND: '未找到相关内容，请尝试换个表述或上传更多文档',
}
