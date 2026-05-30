"""System runtime info — GET /api/system/runtime-info."""

from fastapi import APIRouter, Depends

from app.config import settings
from app.core.auth import CurrentUser
from app.deps import verify_token

router = APIRouter()


@router.get("/system/runtime-info")
async def get_runtime_info(current_user: CurrentUser = Depends(verify_token)):
    return {
        "chat_model": settings.CHAT_MODEL,
        "chat_timeout": settings.CHAT_TIMEOUT,
        "embedding_model": settings.EMBEDDING_MODEL_NAME,
        "embedding_dim": settings.EMBEDDING_DIM,
        "embedding_device": settings.EMBEDDING_DEVICE,
        "milvus_uri": settings.MILVUS_URI,
        "database_path": settings.DATABASE_PATH,
    }
