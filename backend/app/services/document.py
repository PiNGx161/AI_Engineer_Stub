"""
Document processing service — chunking and ingestion pipeline.

Chunking strategy:
  - Split by paragraph boundaries (double-newline)
  - Merge small paragraphs until max_chars
  - Overlap between chunks for context continuity
  - Respects markdown structure (headers as natural boundaries)
"""

import re
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Document, DocumentChunk
from app.services.embedding import embedding_service


def chunk_text(content: str, max_chars: int = 500, overlap_chars: int = 50) -> list[dict]:
    """Split document text into overlapping chunks by paragraph boundaries."""
    paragraphs = re.split(r"\n\s*\n", content.strip())
    paragraphs = [p.strip() for p in paragraphs if p.strip()]

    chunks: list[str] = []
    current = ""

    for para in paragraphs:
        if current and len(current) + len(para) + 2 > max_chars:
            chunks.append(current.strip())
            if overlap_chars > 0 and len(current) > overlap_chars:
                current = current[-overlap_chars:] + "\n\n" + para
            else:
                current = para
        else:
            current = (current + "\n\n" + para) if current else para

    if current.strip():
        chunks.append(current.strip())

    return [{"index": i, "content": c} for i, c in enumerate(chunks)]


async def ingest_document(
    db: AsyncSession,
    tenant_id: UUID,
    title: str,
    content: str,
    source: str | None = None,
    doc_type: str = "markdown",
) -> Document:
    """
    Full ingestion pipeline:
      1. Store raw document in PostgreSQL
      2. Chunk the content
      3. Generate embeddings for each chunk
      4. Store chunks + embeddings in pgvector
    """
    # Chunk the content
    chunks = chunk_text(content)

    # Generate embeddings for each chunk
    texts = [c["content"] for c in chunks]
    embeddings = await embedding_service.embed_batch(texts)

    # Calculate total tokens (approximate)
    total_tokens = sum(len(c["content"].split()) for c in chunks)

    # Create document record
    doc = Document(
        tenant_id=tenant_id,
        title=title,
        content=content,
        source=source,
        doc_type=doc_type,
    )
    db.add(doc)
    await db.flush()

    # Save chunks with embeddings (pgvector)
    for i, (chunk_data, embedding) in enumerate(zip(chunks, embeddings)):
        db.add(
            DocumentChunk(
                document_id=doc.id,
                tenant_id=tenant_id,
                chunk_index=i,
                content=chunk_data["content"],
                embedding=embedding,
                token_count=len(chunk_data["content"].split()),  # Approx
            )
        )

    await db.commit()
    await db.refresh(doc)
    return doc


async def get_chunk_count(db: AsyncSession, document_id: UUID) -> int:
    result = await db.execute(
        select(func.count(DocumentChunk.id)).where(DocumentChunk.document_id == document_id)
    )
    return result.scalar() or 0
