"""
LLM service — generates answers from context chunks.

Stub mode returns realistic structured responses derived from retrieved chunks.
OpenAI mode calls gpt-4o-mini with structured JSON output.
"""

import json

from app.config import settings

# Prompt templates
SYSTEM_PROMPT = """You are an internal knowledge assistant for {tenant_name}.
Your role is to answer employee questions based ONLY on the provided context documents.

Rules:
1. Answer ONLY based on the provided context. Do not use external knowledge.
2. If the context does not contain enough information, set confidence to "low" and say you cannot answer.
3. Always cite your sources by referencing the document title.
4. Be concise, professional, and helpful.
5. Never fabricate or guess information.
6. Structure your response as valid JSON matching the output format below.

Output JSON format:
{{
  "answer": "Your answer here",
  "confidence": "high|medium|low",
  "sources": [
    {{"document_title": "...", "chunk_content": "relevant excerpt...", "relevance_score": 0.95}}
  ],
  "reasoning": "Brief explanation of how you arrived at this answer"
}}"""

USER_PROMPT = """Context documents:
{context}

---
Question: {question}

Respond with valid JSON only."""


class LLMService:
    def __init__(self) -> None:
        self.use_openai = bool(settings.openai_api_key)
        self.model = settings.openai_model

    async def generate_answer(
        self,
        question: str,
        context_chunks: list[dict],
        tenant_name: str,
    ) -> dict:
        context_str = self._format_context(context_chunks)
        system = SYSTEM_PROMPT.format(tenant_name=tenant_name)
        user = USER_PROMPT.format(context=context_str, question=question)

        if self.use_openai:
            return await self._call_openai(system, user)
        return self._stub_response(question, context_chunks)

    # Helpers

    @staticmethod
    def _format_context(chunks: list[dict]) -> str:
        parts = []
        for i, c in enumerate(chunks, 1):
            parts.append(
                f"[{i}. Document: {c['document_title']}]\n"
                f"{c['content']}\n"
                f"(Relevance: {c['score']:.2f})"
            )
        return "\n\n---\n\n".join(parts) if parts else "(No relevant documents found)"

    def _stub_response(self, question: str, chunks: list[dict]) -> dict:
        """Build a realistic stub response using actual retrieved chunks."""
        threshold = settings.relevance_threshold

        if not chunks or all(c["score"] < threshold for c in chunks):
            return {
                "answer": (
                    "I don't have enough information in the available "
                    "documents to answer this question."
                ),
                "confidence": "low",
                "sources": [],
                "reasoning": "No relevant context found in the knowledge base.",
                "model_used": "stub-llm-v1",
                "token_usage": {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0},
            }

        top = [c for c in chunks if c["score"] >= threshold][:3]

        # Extract first meaningful sentence per chunk
        answer_parts = []
        sources = []
        for chunk in top:
            sentences = [s.strip() for s in chunk["content"].split(".") if len(s.strip()) > 20]
            if sentences:
                answer_parts.append(sentences[0] + ".")
            sources.append(
                {
                    "document_title": chunk["document_title"],
                    "chunk_content": chunk["content"][:200],
                    "relevance_score": round(chunk["score"], 3),
                }
            )

        answer = (
            f"Based on the available documents: {' '.join(answer_parts)}"
            if answer_parts
            else "Information found in relevant documents."
        )
        confidence = "high" if top[0]["score"] > 0.7 else "medium" if top[0]["score"] > 0.5 else "low"
        est_in = len(question.split()) + sum(len(c["content"].split()) for c in top)
        est_out = len(answer.split())

        return {
            "answer": answer,
            "confidence": confidence,
            "sources": sources,
            "reasoning": (
                f"Answer derived from {len(top)} relevant document(s). "
                f"Top relevance score: {top[0]['score']:.2f}."
            ),
            "model_used": "stub-llm-v1",
            "token_usage": {
                "input_tokens": est_in,
                "output_tokens": est_out,
                "cost_usd": round((est_in * 0.15 + est_out * 0.60) / 1_000_000, 6),
            },
        }

    async def _call_openai(self, system: str, user: str) -> dict:
        import httpx

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "temperature": 0.1,
                    "response_format": {"type": "json_object"},
                },
                timeout=60.0,
            )
            resp.raise_for_status()
            data = resp.json()
            content = json.loads(data["choices"][0]["message"]["content"])
            usage = data.get("usage", {})
            content["model_used"] = self.model
            content["token_usage"] = {
                "input_tokens": usage.get("prompt_tokens", 0),
                "output_tokens": usage.get("completion_tokens", 0),
                "cost_usd": round(
                    (usage.get("prompt_tokens", 0) * 0.15 + usage.get("completion_tokens", 0) * 0.60) / 1_000_000,
                    6,
                ),
            }
            return content


llm_service = LLMService()
