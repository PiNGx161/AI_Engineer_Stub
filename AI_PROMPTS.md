# AI_PROMPTS.md — Prompt Design & AI-Assisted Development Log

## 1. Production Prompt (Used in LLM Service)

### System Prompt

```
You are an internal knowledge assistant for {tenant_name}.
Your role is to answer employee questions based ONLY on the provided context documents.

Rules:
1. Answer ONLY based on the provided context. Do not use external knowledge.
2. If the context does not contain enough information, set confidence to "low"
   and say you cannot answer.
3. Always cite your sources by referencing the document title.
4. Be concise, professional, and helpful.
5. Never fabricate or guess information.
6. Structure your response as valid JSON matching the output format below.

Output JSON format:
{
  "answer": "Your answer here",
  "confidence": "high|medium|low",
  "sources": [
    {"document_title": "...", "chunk_content": "relevant excerpt...", "relevance_score": 0.95}
  ],
  "reasoning": "Brief explanation of how you arrived at this answer"
}
```

### User Prompt

```
Context documents:
{context}

---
Question: {question}

Respond with valid JSON only.
```

### Why this structure?

1. **Grounding instruction ("ONLY based on the provided context"):**
   This is the single most important instruction to reduce hallucination. Without it, the LLM will use its training data to fill gaps.

2. **Explicit refusal pattern:**
   Telling the model exactly what to do when it doesn't know prevents it from guessing. The structured low-confidence response makes it easy for the calling code to detect "don't know" cases.

3. **Structured JSON output:**
   Using `response_format: json_object` with a clear schema ensures parseable responses. The `confidence` field lets the UI/caller decide whether to show the answer or escalate to a human.

4. **Source citation:**
   Forces the model to trace its answer back to specific documents. This is critical for:
   - User trust ("where did this come from?")
   - Auditability ("which document informed this decision?")
   - Debugging ("is the model using the right context?")

5. **Reasoning field:**
   Chain-of-thought reasoning improves answer quality and provides explainability for non-technical stakeholders.

---

## 2. Prompt Iterations

### Iteration 1 (Rejected) — Too open-ended

```
You are a helpful assistant. Answer the user's question.

Context: {context}
Question: {question}
```

**Problem:** No grounding constraint. The model freely uses its training data, causing hallucinations about company-specific policies.

**Example failure:**
- Question: "How many sick leave days do I get?"
- Answer: "Most companies offer 10-15 sick days per year" ← generic, not from our docs

### Iteration 2 (Rejected) — No structure

```
You are an internal assistant. Only use the provided context.
If you don't know, say "I don't know."

Context: {context}
Question: {question}
```

**Problem:** Free-text responses are hard to parse programmatically. No confidence scoring. No source citation.

### Iteration 3 (Accepted) — Current version

Added: JSON schema, confidence levels, source citation, reasoning. See Section 1 above.

**Why accepted:**
- Parseable by code (JSON)
- Includes confidence for threshold-based decisions
- Source citation for audit trail
- Reasoning for explainability
- Explicit refusal pattern for unknown questions

---

## 3. AI-Assisted Development Decisions

### Decision 1: pgvector vs. separate vector DB

**AI suggestion:** Use a dedicated vector database (Milvus/Qdrant) for better scalability.

**Human judgment:** Rejected for v1. pgvector in PostgreSQL reduces operational complexity — one database instead of two. For <1M chunks, pgvector with HNSW index performs well enough. The architecture allows swapping later if needed.

**Rationale:** In a 90-minute test and for a v1 ship, operational simplicity beats theoretical scalability. If the system grows to millions of documents, we can migrate the vector search layer without changing the API.

### Decision 2: Stub vs. Real LLM

**AI suggestion:** Always use OpenAI for realistic demo.

**Human judgment:** Both modes are valuable. Stub mode allows:
- Testing the full pipeline without API keys
- Deterministic outputs for integration testing
- Zero-cost development and CI/CD
- the data flow is exercised end-to-end

The stub builds real responses from actual retrieved chunks, making it behaviourally similar to a real LLM.

### Decision 3: Word-hash embeddings for stub mode

**AI suggestion:** Use random vectors for stub embeddings.

**Human judgment:** Random vectors would make retrieval meaningless (random similarity scores). Instead, I chose word-level hashing where each word maps to fixed vector dimensions. This means:
- Texts sharing vocabulary produce higher cosine similarity
- Retrieval actually works in a meaningful way during demos
- Results are deterministic (same text = same embedding)

### Decision 4: Pre-filter vs. post-filter tenant isolation in vector search

**AI suggestion:** Post-filter (retrieve, then filter by tenant).

**Human judgment:** Rejected. Pre-filter (WHERE tenant_id = X before vector scan) is more secure:
- Tenant B's data never enters the retrieval pipeline
- No risk of leaking ranked results across tenants
- The B-tree index on tenant_id makes the filter efficient

---

## 4. Key Prompt Engineering Principles Applied

| Principle | Implementation |
|---|---|
| **Grounding** | "Answer ONLY based on the provided context" |
| **Structured output** | JSON schema with response_format enforcement |
| **Graceful degradation** | Explicit "I don't know" pattern with low confidence |
| **Chain of thought** | Reasoning field forces step-by-step thinking |
| **Temperature control** | 0.1 — near-deterministic for factual Q&A |
| **Source attribution** | Required citation of document title per source |
| **Tenant scoping** | Tenant name in system prompt for personalised tone |
