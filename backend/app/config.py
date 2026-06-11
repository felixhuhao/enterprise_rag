"""
应用配置模块

使用 pydantic-settings 统一管理所有配置项，支持从 .env 文件和环境变量读取。
涵盖：API 鉴权、CORS、数据库、LLM 模型、Milvus 向量库等。
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    全局配置类

    所有配置项均有默认值，可通过 .env 文件或环境变量覆盖。
    """

    # ---- 应用基本配置 ----
    API_TOKEN: str = ""
    RATE_LIMIT_PER_MINUTE: int = 60
    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://localhost:4173"]
    GENERAL_UPLOAD_DIR: str = "./data/general_uploads"
    GENERAL_PARSED_DIR: str = "./data/general_parsed"
    DATABASE_PATH: str = "./data/app.db"
    STORAGE_MIN_FREE_MB: int = 1024

    # ---- LLM 模型配置 ----
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com/v1"
    CHAT_MODEL: str = "deepseek-v4-flash"
    CHAT_TIMEOUT: int = 180
    CHAT_TEMPERATURE: float = 0.0
    CHAT_MAX_TOKENS: int = 1600
    HYDE_TEMPERATURE: float = 0.3
    HYDE_MAX_TOKENS: int = 256
    QUERY_EXPANSION_TEMPERATURE: float = 0.3
    QUERY_EXPANSION_MAX_TOKENS: int = 256
    RERANK_MAX_TOKENS: int = 128
    GROUNDEDNESS_TEMPERATURE: float = 0.0
    GROUNDEDNESS_MAX_TOKENS: int = 1800
    # 本地模型（vLLM 部署），留空则使用 DashScope 云端模型
    LOCAL_MODEL_URL: str = ""
    LOCAL_MODEL_NAME: str = ""

    # ---- Embedding 配置 ----
    EMBEDDING_MODEL_NAME: str = "bge-m3"
    EMBEDDING_MODEL_PATH: str = "/models/embedding"
    EMBEDDING_DIM: int = 1024
    EMBEDDING_BATCH_SIZE: int = 4
    EMBEDDING_MAX_LENGTH: int = 8192
    EMBEDDING_DEVICE: str = "auto"  # auto | cuda | cpu
    EMBEDDING_USE_FP16: bool = True
    MINERU_BASE_URL: str = "https://mineru.net/api/v4"
    MINERU_API_TOKEN: str = ""
    MINERU_MODEL_VERSION: str = "vlm"
    MINERU_POLL_INTERVAL: int = 3
    MINERU_POLL_TIMEOUT: int = 1800
    MINERU_UPLOAD_TIMEOUT: int = 300
    MINERU_DOWNLOAD_TIMEOUT: int = 300

    # ---- Milvus 向量数据库 ----
    MILVUS_URI: str = "http://localhost:19530"
    MILVUS_REQUIRED_ON_STARTUP: bool = False
    MILVUS_HEALTH_TIMEOUT_SECONDS: float = 2.0

    # ---- Markdown Zip 配置 ----
    MD_ZIP_MAX_SIZE_MB: int = 50

    # ---- 通用上传限制 ----
    UPLOAD_MAX_SIZE_MB: int = 100

    # ---- Chunk search enrichment ----
    CHUNK_ENRICHMENT_ENABLED: bool = False
    CHUNK_ENRICHMENT_PROFILE: str = "none"

    # ---- 图片描述配置 (智谱 GLM-4.6V) ----
    ZHIPU_API_KEY: str = ""
    ZHIPU_BASE_URL: str = "https://open.bigmodel.cn/api/paas/v4"
    IMAGE_DESCRIPTION_ENABLED: bool = True
    IMAGE_DESCRIPTION_MODEL: str = "glm-4.6v-flash"
    IMAGE_DESCRIPTION_CONCURRENCY: int = 3
    IMAGE_DESCRIPTION_TIMEOUT: int = 30
    IMAGE_DESCRIPTION_MAX_TOKENS: int = 800
    IMAGE_DESCRIPTION_MAX_SIZE_MB: int = 10

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


# 全局单例
settings = Settings()
