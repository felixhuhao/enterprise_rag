"""Dense embedding wrapper with swappable backends.

The project-facing interface stays generic so the underlying embedding backend
can be switched between local BGE-M3 (FlagEmbedding) and a remote OpenAI-
compatible embedding API (Qwen `text-embedding-v4`) without changing
ingestion or query code.

Public surface (stable across providers):
    dense_embedding.embed_documents(texts, chunk_size=None) -> list[list[float]]
    dense_embedding.embed_query(text) -> list[float]
    embed_chunks(chunks) -> list[dict]
"""

from __future__ import annotations

import logging
import threading
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.config import settings
from openai import OpenAI

logger = logging.getLogger(__name__)
_MODEL_ENCODE_LOCK = threading.Lock()


@lru_cache(maxsize=1)
def _get_model() -> Any:
    """Lazy-load the local BGE-M3 model. Heavy deps imported here only."""
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


class LocalBgeDenseEmbedding:
    """Local BGE-M3 dense embedding via FlagEmbedding."""

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


class QwenDenseEmbedding:
    """Remote dense embedding via an OpenAI-compatible endpoint (Qwen/DashScope)."""

    #: DashScope `text-embedding-v4` accepts at most 10 input items per request.
    QWEN_MAX_BATCH = 10

    def __init__(self) -> None:
        if settings.EMBEDDING_BATCH_SIZE > self.QWEN_MAX_BATCH:
            raise RuntimeError(
                f"Embedding config error: EMBEDDING_BATCH_SIZE="
                f"{settings.EMBEDDING_BATCH_SIZE} exceeds Qwen max batch "
                f"{self.QWEN_MAX_BATCH}. Lower EMBEDDING_BATCH_SIZE."
            )
        self._client: Any = None

    def _get_client(self) -> Any:
        # Lazily construct a single shared client. Not locked by design: client
        # construction is cheap and must not become a global serialization point
        # (see design §8). A benign race may build a second client that is
        # discarded.
        if self._client is None:
            self._client = OpenAI(
                api_key=settings.QWEN_API_KEY,
                base_url=settings.QWEN_BASE_URL,
                timeout=settings.EMBEDDING_TIMEOUT,
                max_retries=settings.EMBEDDING_MAX_RETRIES,
            )
        return self._client

    def embed_documents(self, texts: list[str], chunk_size: int | None = None) -> list[list[float]]:
        if not texts:
            return []

        if not settings.QWEN_API_KEY.strip():
            raise RuntimeError(
                "Embedding config error: EMBEDDING_PROVIDER=qwen but QWEN_API_KEY is empty."
            )

        client = self._get_client()
        batch_size = chunk_size or settings.EMBEDDING_BATCH_SIZE
        if batch_size > self.QWEN_MAX_BATCH:
            raise RuntimeError(
                f"Embedding config error: effective batch size={batch_size} "
                f"exceeds Qwen max batch {self.QWEN_MAX_BATCH}."
            )
        results: list[list[float]] = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            try:
                resp = client.embeddings.create(
                    model=settings.EMBEDDING_MODEL_NAME,
                    input=batch,
                    dimensions=settings.EMBEDDING_DIM,
                    encoding_format="float",
                )
            except Exception as e:
                raise RuntimeError(f"Embedding request failed: {e}") from e
            # Preserve request order using response item `index`.
            ordered = sorted(resp.data, key=lambda d: d.index)
            results.extend([list(d.embedding) for d in ordered])
        return results

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text], chunk_size=1)[0]


def get_dense_embedding() -> Any:
    """Select the active dense embedding backend from settings."""
    provider = settings.EMBEDDING_PROVIDER.strip().lower()
    if provider == "qwen":
        return QwenDenseEmbedding()
    if provider == "local":
        return LocalBgeDenseEmbedding()
    raise RuntimeError(
        f"Embedding config error: unknown EMBEDDING_PROVIDER={provider!r} "
        f"(expected 'local' or 'qwen')."
    )


dense_embedding = get_dense_embedding()


def embed_chunks(chunks: list[dict]) -> list[dict]:
    """Embed chunk content with the configured dense model and validate dimensions."""
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
