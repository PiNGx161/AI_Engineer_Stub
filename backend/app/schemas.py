"""Pydantic schemas for API request/response validation."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


# Tenant

class TenantCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-z0-9-]+$")


class TenantResponse(BaseModel):
    id: UUID
    name: str
    slug: str
    api_key: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# Document

class DocumentCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    content: str = Field(..., min_length=1)
    source: str | None = None
    doc_type: str = "markdown"


class DocumentResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    title: str
    source: str | None
    doc_type: str
    chunk_count: int = 0
    created_at: datetime

    model_config = {"from_attributes": True}


# Query

class QueryRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=20)


class SourceInfo(BaseModel):
    document_title: str
    chunk_content: str
    relevance_score: float


class QueryResponse(BaseModel):
    request_id: UUID
    answer: str
    confidence: str
    sources: list[SourceInfo]
    reasoning: str
    cached: bool = False
    model_used: str
    latency_ms: int
    token_usage: dict = {}


# Health

class HealthResponse(BaseModel):
    status: str
    postgres: str
    redis: str
    version: str
