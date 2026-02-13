# Internal Knowledge Assistant

> AI-powered document Q&A for internal teams — multi-tenant, RAG-based, with caching, audit logging, and tenant isolation.

**Option chosen:** C — Internal Knowledge Assistant

---

## Section A — Core AI System Design

### A1. Problem Framing

**Who is the user?**
Internal employees (HR, Operations, IT support) who need quick, accurate answers from company documents — leave policies, IT FAQs, expense rules, onboarding guides.

**What decision are they trying to make?**
"What does our policy say about X?" — e.g., how many leave days do I have, how to set up VPN, what's the meal reimbursement limit. Currently, employees either search through Confluence/SharePoint or ping HR/IT directly.

**Why is a rule-based system insufficient?**
- Documents are **unstructured** (markdown, PDFs) — keyword search misses semantic meaning ("vacation" vs "annual leave" vs "PTO").
- Questions are asked in **natural language** with varying phrasing — rule-based systems can't generalise.
- Answers often require **synthesising information** across multiple document sections.
- A rule-based system would require manually coding every possible Q&A pair and maintaining it as policies change.

### A2. System Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                        Client (curl / chat UI)               │
│                   X-API-Key: ka-acme-test-key-001            │
└──────────────────────┬───────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────┐
│                    FastAPI API Layer                          │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────────┐  │
│  │ /tenants    │  │ /documents   │  │ /query             │  │
│  │ (CRUD)      │  │ (ingest)     │  │ (RAG pipeline)     │  │
│  └─────────────┘  └──────┬───────┘  └────────┬───────────┘  │
│                          │                    │              │
│  ┌───────────────────────┼────────────────────┼───────────┐  │
│  │              Service Layer                 │           │  │
│  │  ┌────────────┐  ┌────────────┐  ┌────────▼────────┐  │  │
│  │  │ Chunking   │  │ Embedding  │  │ RAG Service     │  │  │
│  │  │ Service    │  │ Service    │  │ (orchestrator)  │  │  │
│  │  └────────────┘  └────────────┘  └────────┬────────┘  │  │
│  │                                           │           │  │
│  │  ┌────────────────────────────────────────▼────────┐  │  │
│  │  │  LLM Service (stub / OpenAI gpt-4o-mini)       │  │  │
│  │  └────────────────────────────────────────────────-┘  │  │
│  └───────────────────────────────────────────────────────┘  │
└──────────────────────┬──────────────────┬────────────────────┘
                       │                  │
          ┌────────────▼──────┐    ┌──────▼──────┐
          │   PostgreSQL      │    │    Redis     │
          │   + pgvector      │    │   (cache +   │
          │                   │    │  rate limit)  │
          │  • tenants        │    │              │
          │  • documents      │    │  • query     │
          │  • document_chunks│    │    cache     │
          │    (embeddings)   │    │  • rate      │
          │  • ai_requests    │    │    limiter   │
          │    (audit log)    │    │              │
          └───────────────────┘    └──────────────┘
```

**Key components:**
- **API Layer (FastAPI):** REST endpoints with OpenAPI docs. Tenant resolved via `X-API-Key` header.
- **Embedding Service:** Stub mode (word-hash vectors) or OpenAI `text-embedding-3-small`. Dimension: 1536.
- **RAG Service:** Orchestrates cache → embed → retrieve → LLM → cache → audit.
- **LLM Service:** Stub mode builds answers from retrieved chunks. OpenAI mode calls `gpt-4o-mini` with structured JSON output.
- **PostgreSQL + pgvector:** System of record + vector search in one database. HNSW index for ANN search.
- **Redis:** Query response cache (1h TTL) + sliding-window rate limiter per tenant.

### A3. Data Model

```sql
-- Tenant: isolation boundary
tenants (id UUID PK, name, slug UNIQUE, api_key UNIQUE, is_active, created_at)

-- Documents: raw source content
documents (id UUID PK, tenant_id FK→tenants, title, content, source, doc_type, metadata JSONB, created_at)

-- Chunks: embedded text for vector search — tenant_id denormalised for fast filtered retrieval
document_chunks (id UUID PK, document_id FK→documents, tenant_id FK→tenants, chunk_index, content, embedding vector(1536), token_count, metadata JSONB, created_at)

-- Audit log: every AI query logged for explainability and cost tracking
ai_requests (id UUID PK, tenant_id FK→tenants, query, response JSONB, chunks_used JSONB, model_used, token_usage JSONB, latency_ms, cached, status, created_at)
```

**Tenant isolation is enforced at 3 levels:**
1. **API boundary:** `X-API-Key` header → resolves to `tenant_id`
2. **Query boundary:** every SQL query includes `WHERE tenant_id = :tenant_id`
3. **Vector search:** `WHERE dc.tenant_id = :tenant_id` in pgvector similarity query

### A4. Prompt Design

**System prompt:**
```
You are an internal knowledge assistant for {tenant_name}.
Answer ONLY based on the provided context documents.
If context is insufficient, set confidence to "low" and refuse to answer.
Always cite sources. Never fabricate information.
Respond in structured JSON: {answer, confidence, sources[], reasoning}
```

**User prompt:**
```
Context documents:
{context}
---
Question: {question}
Respond with valid JSON only.
```

**Output format:**
```json
{
  "answer": "Employees get 10-20 days based on years of service.",
  "confidence": "high",
  "sources": [{"document_title": "Leave Policy", "chunk_content": "...", "relevance_score": 0.95}],
  "reasoning": "Answer derived from Leave Policy section 2."
}
```

**Why this structure?**
- **Grounding** — "ONLY based on context" prevents hallucination
- **Structured JSON** — parseable by code, enables threshold-based decisions
- **Confidence field** — lets caller decide: show answer vs escalate to human
- **Source citation** — audit trail + user trust
- **Reasoning** — explainability for non-technical stakeholders

Full prompt iterations and rejected alternatives: [AI_PROMPTS.md](./AI_PROMPTS.md)

---

## Section B1 — RAG Design

### How documents are chunked
- **Paragraph-boundary splitting**: split on `\n\n` (respects markdown structure)
- **Max chunk size**: 500 characters (configurable)
- **Overlap**: 50 characters between consecutive chunks for context continuity
- **Token counting**: stored per chunk for cost estimation

### How embeddings are stored
- **pgvector** extension in PostgreSQL (no separate vector DB needed)
- Embedding column: `vector(1536)` on `document_chunks` table
- **HNSW index** for approximate nearest neighbour search (cosine distance)
- Same database as relational data → transactional consistency, simpler ops

### How retrieval is filtered per tenant
```sql
SELECT dc.content, d.title,
       1 - (dc.embedding <=> :query_embedding::vector) AS score
FROM document_chunks dc
JOIN documents d ON d.id = dc.document_id
WHERE dc.tenant_id = :tenant_id          -- ← tenant isolation
ORDER BY dc.embedding <=> :query_embedding::vector
LIMIT :top_k
```
- `tenant_id` is **denormalised** on `document_chunks` to avoid a JOIN just for filtering
- The `WHERE` clause runs **before** the vector scan, so Tenant A never sees Tenant B's chunks

---

## Section D1 — Tenant Isolation Strategy

### How prompts avoid cross-tenant leakage
1. **Data-level isolation**: every query is scoped by `tenant_id`. The LLM only ever receives chunks belonging to the authenticated tenant.
2. **Prompt-level isolation**: the system prompt includes `{tenant_name}` but no data from other tenants.
3. **No shared context**: each request is stateless — no conversation memory that could leak across tenants.
4. **API key per tenant**: there is no mechanism to query across tenants via the API.

### How vector search is scoped
- `tenant_id` column on `document_chunks` with a B-tree index
- **Pre-filter** approach: `WHERE tenant_id = X` runs before cosine similarity ranking
- This means the HNSW index scans only the tenant's embeddings, not the entire table
- Alternative considered: separate pgvector tables per tenant (rejected — adds schema complexity without meaningful benefit for <100 tenants)

---

## Section E — Execution Reality Check

1. **What would I ship in 2 weeks?**
   - Working RAG pipeline (ingest → chunk → embed → retrieve → answer)
   - Multi-tenant API with auth
   - Redis caching and rate limiting
   - Audit logging dashboard (simple read endpoint)
   - Docker Compose deployment
   - OpenAI integration (real embeddings + GPT-4o-mini)

2. **What would I explicitly NOT build yet?**
   - Frontend / chat UI (API-first, integrate with Slack/Teams later)
   - Conversation memory / follow-up questions
   - Fine-tuned models or custom reranking
   - PDF/DOCX parsing (start with markdown/text only)
   - Role-based access within a tenant (v2 feature)

3. **What risks worry me the most?**
   - **Hallucination**: stub mode can't detect hallucinations — real LLM evaluation needed before production
   - **Embedding quality**: stub embeddings work for demo but real OpenAI embeddings are required for production accuracy
   - **Cost creep**: without monitoring dashboards, LLM costs can spiral with high traffic
   - **PDPA compliance**: PII in documents needs redaction before embedding — not yet implemented

---

## Assumptions & Trade-offs

| Decision | Rationale |
|---|---|
| **pgvector** instead of Milvus/Qdrant | Fewer moving parts. One database for relational + vector. Good enough for <1M chunks per tenant. |
| **Stub LLM** as default | Allows full system testing without API keys. Real data flow is exercised. |
| **Word-hash embeddings** | Deterministic, fast, no external dependency. Texts with shared vocabulary produce similar vectors. |
| **Pre-filter** tenant isolation | Simpler than separate indexes. `WHERE tenant_id` runs before ANN scan. |
| **No conversation memory** | Stateless requests are simpler to cache and audit. Memory adds complexity and leakage risk. |

---

## Runbook

### Prerequisites
- Docker + Docker Compose v2

### One-command startup
1. **Configure environment**:
   ```bash
   cp .env.example .env
   # (Optional) Edit .env to add your OpenAI API Key for real embeddings
   ```

2. **Start system**:
   ```bash
   docker compose up --build
   ```
   > The system will automatically seed sample data (Tenants, Documents) on startup.

3. **Verify**:
   ```bash
   curl http://localhost:8000/api/v1/health
   # {"status": "healthy", ...}
   ```



### Health check
```bash
curl http://localhost:8000/api/v1/health
```

### Example API calls

**1. Create a tenant:**
```bash
curl -s -X POST http://localhost:8000/api/v1/tenants \
  -H "Content-Type: application/json" \
  -d '{"name": "Acme Corp", "slug": "acme-corp"}' | jq
```

**2. Upload a document** (use the API key from tenant creation or seed):
```bash
curl -s -X POST http://localhost:8000/api/v1/documents \
  -H "Content-Type: application/json" \
  -H "X-API-Key: ka-acme-test-key-001" \
  -d '{
    "title": "Leave Policy",
    "content": "# Leave Policy\n\nAll employees get 15 days annual leave per year.",
    "source": "hr/leave.md"
  }' | jq
```

**3. Ask a question:**
```bash
curl -s -X POST http://localhost:8000/api/v1/query \
  -H "Content-Type: application/json" \
  -H "X-API-Key: ka-acme-test-key-001" \
  -d '{"question": "How many days of annual leave do I get?"}' | jq
```

**4. List documents:**
```bash
curl -s http://localhost:8000/api/v1/documents \
  -H "X-API-Key: ka-acme-test-key-001" | jq
```

**5. Verify tenant isolation** (Beta Inc cannot see Acme Corp's docs):
```bash
curl -s http://localhost:8000/api/v1/documents \
  -H "X-API-Key: ka-beta-test-key-002" | jq
# → Returns only Beta Inc's documents
```

### Environment variables
See [.env.example](./.env.example) for all available configuration.

| Variable | Default | Description |
|---|---|---|
| `OPENAI_API_KEY` | (empty) | Set to enable real LLM. Empty = stub mode. |
| `POSTGRES_PASSWORD` | postgres | PostgreSQL password |
| `RETRIEVAL_TOP_K` | 5 | Number of chunks to retrieve |
| `CACHE_TTL` | 3600 | Redis cache TTL in seconds |
| `RATE_LIMIT_REQUESTS` | 20 | Max requests per tenant per window |

---

## What I would improve with more time

1. **Real embedding model** — use `text-embedding-3-small` or a local sentence-transformer
2. **Reranking** — add a cross-encoder reranker after initial retrieval
3. **PDF/DOCX parsing** — extract text from binary documents
4. **Evaluation pipeline** — golden test set with automated accuracy scoring
5. **PII redaction** — scan documents before embedding (Presidio or regex-based)
6. **Streaming responses** — SSE for real-time answer generation
7. **Conversation memory** — follow-up questions with context window
8. **Observability** — OpenTelemetry tracing, Prometheus metrics, Grafana dashboards
