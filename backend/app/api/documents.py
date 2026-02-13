"""Document ingestion endpoints — scoped to authenticated tenant."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_tenant
from app.models import Document, DocumentChunk, Tenant
from app.schemas import DocumentCreate, DocumentResponse
from app.services.document import ingest_document, get_chunk_count

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("", response_model=DocumentResponse, status_code=201)
async def upload_document(
    body: DocumentCreate,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Ingest a document: store → chunk → embed → index in pgvector."""
    doc = await ingest_document(
        db=db,
        tenant_id=tenant.id,
        title=body.title,
        content=body.content,
        source=body.source,
        doc_type=body.doc_type,
    )
    count = await get_chunk_count(db, doc.id)
    return DocumentResponse(
        id=doc.id,
        tenant_id=doc.tenant_id,
        title=doc.title,
        source=doc.source,
        doc_type=doc.doc_type,
        chunk_count=count,
        created_at=doc.created_at,
    )


@router.get("", response_model=list[DocumentResponse])
async def list_documents(
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """List all documents for the authenticated tenant."""
    result = await db.execute(
        select(
            Document,
            func.count(DocumentChunk.id).label("chunk_count"),
        )
        .outerjoin(DocumentChunk, DocumentChunk.document_id == Document.id)
        .where(Document.tenant_id == tenant.id)
        .group_by(Document.id)
        .order_by(Document.created_at.desc())
    )
    rows = result.all()
    return [
        DocumentResponse(
            id=doc.id,
            tenant_id=doc.tenant_id,
            title=doc.title,
            source=doc.source,
            doc_type=doc.doc_type,
            chunk_count=count,
            created_at=doc.created_at,
        )
        for doc, count in rows
    ]


@router.delete("/{document_id}", status_code=204)
async def delete_document(
    document_id: str,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Delete a document and its chunks (cascade). Tenant-scoped."""
    result = await db.execute(
        select(Document).where(Document.id == document_id, Document.tenant_id == tenant.id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await db.delete(doc)
    await db.commit()
