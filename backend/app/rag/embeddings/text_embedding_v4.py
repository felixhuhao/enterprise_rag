"""text-embedding-v4 embedding wrapper."""

from langchain_openai import OpenAIEmbeddings

from app.config import settings

_text_embedding = OpenAIEmbeddings(
    api_key=settings.DASHSCOPE_API_KEY,
    base_url=settings.DASHSCOPE_BASE_URL,
    model=settings.EMBEDDING_MODEL,
    dimensions=settings.EMBEDDING_DIM,
    check_embedding_ctx_length=False,
    request_timeout=30,
)


def embed_chunks(chunks: list[dict]) -> list[dict]:
    """Embed chunk content with text-embedding-v4 and validate dimensions."""
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
    vectors = _text_embedding.embed_documents(texts, chunk_size=6)
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
