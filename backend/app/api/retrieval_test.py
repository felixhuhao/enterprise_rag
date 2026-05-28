"""Retrieval test API — search-only diagnostics without answer generation."""

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.deps import verify_token
from app.services.retrieval_test_service import run_retrieval_test

router = APIRouter()


class RetrievalTestRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=4000)
    top_k: int = Field(10, ge=1, le=30)
    use_hybrid: bool = True
    use_hyde: bool = True
    use_rerank: bool = True


@router.post("/query/retrieval-test")
async def retrieval_test(req: RetrievalTestRequest, _: None = Depends(verify_token)):
    """Run retrieval pipeline up to rerank and return inspectable chunks."""
    try:
        return await asyncio.to_thread(
            run_retrieval_test,
            req.query,
            top_k=req.top_k,
            use_hybrid=req.use_hybrid,
            use_hyde=req.use_hyde,
            use_rerank=req.use_rerank,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"检索测试失败: {e}") from e
