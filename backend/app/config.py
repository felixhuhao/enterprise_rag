"""
应用配置模块

使用 pydantic-settings 统一管理所有配置项，支持从 .env 文件和环境变量读取。
涵盖：API 鉴权、CORS、数据库、LLM 模型、Milvus 向量库、评估阈值等。
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    全局配置类

    所有配置项均有默认值，可通过 .env 文件或环境变量覆盖。
    """

    # ---- 应用基本配置 ----
    API_TOKEN: str = "rag-pro-secret-token"
    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://localhost:4173"]
    UPLOAD_DIR: str = "./uploads"
    DATABASE_PATH: str = "./data/app.db"

    # ---- LLM 模型配置 ----
    DASHSCOPE_API_KEY: str = ""
    DASHSCOPE_BASE_URL: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    CHAT_MODEL: str = "qwen-plus"
    CHAT_TIMEOUT: int = 180
    # 本地模型（vLLM 部署），留空则使用 DashScope 云端模型
    LOCAL_MODEL_URL: str = ""
    LOCAL_MODEL_NAME: str = ""
    EVAL_MODEL: str = "qwen-plus"
    EVAL_TIMEOUT: int = 120

    # ---- Embedding 配置 ----
    EMBEDDING_MODEL: str = "text-embedding-v4"
    EMBEDDING_DIM: int = 1024
    VL_EMBEDDING_DIM: int = 2560

    # ---- 智谱 AI ----
    ZHIPU_API_KEY: str = ""
    ZHIPU_BASE_URL: str = "https://open.bigmodel.cn/api/paas/v4/"

    # ---- Tavily 网络搜索 ----
    TAVILY_API_KEY: str = ""

    # ---- Milvus 向量数据库 ----
    MILVUS_URI: str = "http://localhost:19530"

    # ---- 评估阈值 ----
    EVALUATE_THRESHOLD_HIGH: float = 0.8
    EVALUATE_THRESHOLD_LOW: float = 0.6
    CONTEXT_SEARCH_THRESHOLD: float = 1.3  # 上下文检索分数低于此值视为不相关

    # ---- 其他默认值 ----
    DEFAULT_USER_NAME: str = "ZS"
    TOOL_CONTENT_PREVIEW_LENGTH: int = 500

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )


# 全局单例
settings = Settings()
