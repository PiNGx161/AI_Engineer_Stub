"""
RAG service — Retrieval-Augmented Generation pipeline.

Flow:
  1. Check Redis cache (same tenant + same question = cache hit)
  2. Rate-limit check per tenant
  3. Embed the question
  4. Retrieve top-K similar chunks filtered by tenant_id
  5. Send chunks as context to LLM
  6. Cache the result in Redis
  7. Log the request in PostgreSQL audit table
"""

import hashlib
import json
import time
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import AIRequest
from app.redis_client import redis_client
from app.services.embedding import embedding_service
from app.services.llm import llm_service


class RAGService:
    # Main entry point

    async def query(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        tenant_name: str,
        question: str,
        top_k: int = 5,
    ) -> dict:
        start = time.time()

        # 1. Cache check
        cache_key = self._cache_key(str(tenant_id), question)
        cached = await self._get_cache(cache_key)
        if cached:
            cached["cached"] = True
            cached["latency_ms"] = int((time.time() - start) * 1000)
            await self._log_request(db, tenant_id, question, cached, is_cached=True)
            return cached

        # 2. Rate limit
        allowed = await self._check_rate_limit(str(tenant_id))
        if not allowed:
            return {
                "answer": "Rate limit exceeded. Please try again later.",
                "confidence": "low",
                "sources": [],
                "reasoning": "Request throttled by rate limiter.",
                "model_used": "none",
                "latency_ms": int((time.time() - start) * 1000),
                "cached": False,
                "token_usage": {},
            }

        # 3. Embed question
        q_embedding = await embedding_service.embed(question)

        # 4. Retrieve chunks (tenant-scoped vector search)
        chunks = await self._retrieve_chunks(db, tenant_id, q_embedding, top_k)

        # 5. Generate answer
        result = await llm_service.generate_answer(question, chunks, tenant_name)
        result["cached"] = False
        result["latency_ms"] = int((time.time() - start) * 1000)

        # 6. Cache result
        await self._set_cache(cache_key, result)

        # 7. Audit log
        request_id = await self._log_request(db, tenant_id, question, result, chunks_used=chunks)
        result["request_id"] = str(request_id)

        return result

    # Tenant-scoped vector retrieval

    @staticmethod
    async def _retrieve_chunks(
        db: AsyncSession,
        tenant_id: UUID,
        query_embedding: list[float],
        top_k: int,
    ) -> list[dict]:
        """
        Retrieve top-K most similar chunks scoped to the given tenant.
        Uses pgvector's cosine distance operator (<=>).
        tenant_id filter ensures complete data isolation between tenants.
        """
        embedding_str = "[" + ",".join(str(x) for x in query_embedding) + "]"

        sql = text("""
            SELECT
                dc.content,
                dc.chunk_index,
                d.title AS document_title,
                1 - (dc.embedding <=> CAST(:embedding AS vector)) AS score
            FROM document_chunks dc
            JOIN documents d ON d.id = dc.document_id
            WHERE dc.tenant_id = :tenant_id
            ORDER BY dc.embedding <=> CAST(:embedding AS vector)
            LIMIT :top_k
        """)

        result = await db.execute(
            sql,
            {
                "embedding": embedding_str,
                "tenant_id": str(tenant_id),
                "top_k": top_k,
            },
        )
        rows = result.fetchall()

        return [
            {
                "content": row.content,
                "chunk_index": row.chunk_index,
                "document_title": row.document_title,
                "score": float(row.score) if row.score else 0.0,
            }
            for row in rows
        ]

    # Redis cache

    @staticmethod
    def _cache_key(tenant_id: str, question: str) -> str:
        q_hash = hashlib.sha256(question.strip().lower().encode()).hexdigest()[:16]
        return f"rag:cache:{tenant_id}:{q_hash}"

    @staticmethod
    async def _get_cache(key: str) -> dict | None:
        try:
            data = await redis_client.get(key)
            return json.loads(data) if data else None
        except Exception:
            return None

    @staticmethod
    async def _set_cache(key: str, value: dict) -> None:
        try:
            safe = {k: v for k, v in value.items() if k != "request_id"}
            await redis_client.setex(key, settings.cache_ttl, json.dumps(safe, default=str))
        except Exception:
            pass  # Cache failure should not break the main flow

    # Rate limiter (sliding window)

    @staticmethod
    async def _check_rate_limit(tenant_id: str) -> bool:
        try:
            key = f"rag:ratelimit:{tenant_id}"
            current = await redis_client.incr(key)
            if current == 1:
                await redis_client.expire(key, settings.rate_limit_window)
            return current <= settings.rate_limit_requests
        except Exception:
            return True  # Fail-open: allow requests if Redis is unreachable

    # Audit log

    @staticmethod
    async def _log_request(
        db: AsyncSession,
        tenant_id: UUID,
        question: str,
        result: dict,
        chunks_used: list[dict] | None = None,
        is_cached: bool = False,
    ) -> UUID:
        req = AIRequest(
            tenant_id=tenant_id,
            query=question,
            response={"answer": result.get("answer", ""), "confidence": result.get("confidence", "")},
            chunks_used=[{"doc": c["document_title"], "score": c["score"]} for c in (chunks_used or [])],
            model_used=result.get("model_used", "unknown"),
            token_usage=result.get("token_usage", {}),
            latency_ms=result.get("latency_ms", 0),
            cached=is_cached,
        )
        db.add(req)
        await db.commit()
        await db.refresh(req)
        return req.id


rag_service = RAGService()
