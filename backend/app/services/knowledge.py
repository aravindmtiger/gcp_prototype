"""Ingestion and retrieval over pgvector (Cloud SQL for PostgreSQL).

Ingest: text -> overlapping chunks -> embeddings (Vertex AI) -> ``document_chunks``.
Retrieve: query -> embedding -> cosine-distance top-k, scoped to the caller's rows.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DocumentChunk, utcnow
from app.services.llm import LLMClient

EMBED_BATCH_SIZE = 64


def chunk_text(text: str, size: int = 1000, overlap: int = 150) -> list[str]:
    """Split text into fixed-size windows that overlap so sentences are not cut off unseen."""
    if size <= overlap:
        raise ValueError("chunk size must be larger than overlap")
    cleaned = text.strip()
    if not cleaned:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(cleaned):
        chunks.append(cleaned[start : start + size])
        if start + size >= len(cleaned):
            break
        start += size - overlap
    return chunks


async def ingest_text(
    session: AsyncSession,
    llm: LLMClient,
    *,
    owner_email: str,
    collection: str,
    source: str,
    text: str,
) -> int:
    chunks = chunk_text(text)
    if not chunks:
        raise ValueError("document has no text to index")

    rows: list[DocumentChunk] = []
    for start in range(0, len(chunks), EMBED_BATCH_SIZE):
        batch = chunks[start : start + EMBED_BATCH_SIZE]
        vectors = await llm.embed(batch)
        for content, vector in zip(batch, vectors, strict=True):
            rows.append(
                DocumentChunk(
                    owner_email=owner_email,
                    collection=collection,
                    source=source,
                    content=content,
                    embedding=vector,
                    created_at=utcnow(),
                )
            )

    session.add_all(rows)
    await session.commit()
    return len(rows)


async def search(
    session: AsyncSession,
    llm: LLMClient,
    *,
    owner_email: str,
    collection: str,
    query: str,
    top_k: int,
) -> list[str]:
    [query_vector] = await llm.embed([query])
    statement = (
        select(DocumentChunk.content)
        .where(DocumentChunk.owner_email == owner_email, DocumentChunk.collection == collection)
        .order_by(DocumentChunk.embedding.cosine_distance(query_vector))
        .limit(top_k)
    )
    result = await session.execute(statement)
    return list(result.scalars().all())
