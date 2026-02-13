"""Query endpoint — the core RAG-powered Q&A."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_tenant
from app.models import Tenant
from app.schemas import QueryRequest, QueryResponse
from app.services.rag import rag_service

router = APIRouter(prefix="/query", tags=["query"])


@router.post("", response_model=QueryResponse)
async def ask_question(
    body: QueryRequest,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """
    Ask a question against the tenant's knowledge base.

    Pipeline: cache check → embed → vector search → LLM → cache → audit log
    """
    result = await rag_service.query(
        db=db,
        tenant_id=tenant.id,
        tenant_name=tenant.name,
        question=body.question,
        top_k=body.top_k,
    )

    return QueryResponse(
        request_id=result.get("request_id", "00000000-0000-0000-0000-000000000000"),
        answer=result["answer"],
        confidence=result["confidence"],
        sources=[
            {
                "document_title": s["document_title"],
                "chunk_content": s.get("chunk_content", ""),
                "relevance_score": s.get("relevance_score", 0.0),
            }
            for s in result.get("sources", [])
        ],
        reasoning=result.get("reasoning", ""),
        cached=result.get("cached", False),
        model_used=result.get("model_used", "unknown"),
        latency_ms=result.get("latency_ms", 0),
        token_usage=result.get("token_usage", {}),
    )
