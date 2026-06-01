"""Local dense embedding wrapper.

The current implementation uses FlagEmbedding's M3 encoder with dense vectors.
The project-facing interface stays generic so the underlying local embedding
model can be replaced without changing ingestion or query code.
"""

from __future__ import annotations

import logging
import threading
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)
_MODEL_ENCODE_LOCK = threading.Lock()


@lru_cache(maxsize=1)
def _get_model() -> Any:
    import torch
    from FlagEmbedding import BGEM3FlagModel

    model_path = settings.EMBEDDING_MODEL_PATH
    if not Path(model_path).exists():
        raise RuntimeError(f"Embedding model path does not exist: {model_path}")

    device = settings.EMBEDDING_DEVICE.strip().lower()
    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("EMBEDDING_DEVICE=cuda but CUDA is not available")

    logger.info("加载 embedding model: %s (device=%s)", model_path, device)
    return BGEM3FlagModel(
        model_path,
        use_fp16=settings.EMBEDDING_USE_FP16 and device == "cuda",
        devices=[device],
    )


class LocalDenseEmbedding:
    """Minimal embedding interface used by ingestion/search/HyDE."""

    def embed_documents(self, texts: list[str], chunk_size: int | None = None) -> list[list[float]]:
        if not texts:
            return []

        with _MODEL_ENCODE_LOCK:
            model = _get_model()
            result = model.encode(
                texts,
                batch_size=chunk_size or settings.EMBEDDING_BATCH_SIZE,
                max_length=settings.EMBEDDING_MAX_LENGTH,
                return_dense=True,
                return_sparse=False,
                return_colbert_vecs=False,
            )
        dense_vecs = result["dense_vecs"]
        return [vec.tolist() for vec in dense_vecs]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text], chunk_size=1)[0]


dense_embedding = LocalDenseEmbedding()


def embed_chunks(chunks: list[dict]) -> list[dict]:
    """Embed chunk content with the configured local dense model and validate dimensions."""
    if not chunks:
        return []

    texts = []
    for chunk in chunks:
        entity = chunk.get("entity_name", "")
        content = chunk["content"]
        if entity:
            texts.append(f"实体：{entity}，内容：{content}")
        else:
            texts.append(content)

    vectors = dense_embedding.embed_documents(texts, chunk_size=settings.EMBEDDING_BATCH_SIZE)
    if len(vectors) != len(chunks):
        raise RuntimeError("embedding result count does not match chunk count")

    embedded = []
    for chunk, dense in zip(chunks, vectors):
        if len(dense) != settings.EMBEDDING_DIM:
            raise RuntimeError(
                f"embedding dim mismatch: expected {settings.EMBEDDING_DIM}, got {len(dense)}"
            )
        row = chunk.copy()
        row["dense"] = dense
        embedded.append(row)
    return embedded
