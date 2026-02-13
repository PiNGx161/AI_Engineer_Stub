"""
Embedding service — generates vector embeddings for text.

Supports two modes:
  1. STUB mode (default): deterministic word-hash embeddings for demo/testing.
     Texts sharing words will produce similar vectors (cosine similarity).
  2. OpenAI mode: real embeddings via text-embedding-3-small when API key is set.
"""

import hashlib
import math

from app.config import settings


class EmbeddingService:
    def __init__(self) -> None:
        self.dim = settings.embedding_dim
        self.use_openai = bool(settings.openai_api_key)

    # Public API

    async def embed(self, text: str) -> list[float]:
        if self.use_openai:
            return await self._openai_embed(text)
        return self._stub_embed(text)

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if self.use_openai:
            return await self._openai_embed_batch(texts)
        return [self._stub_embed(t) for t in texts]

    # Stub embeddings (word-hash approach)

    def _stub_embed(self, text: str) -> list[float]:
        """
        Deterministic embedding using word-level hashing.
        Words map to fixed dimensions, so texts sharing vocabulary
        will have higher cosine similarity — good enough for demos.
        """
        words = set(text.lower().split())
        vec = [0.0] * self.dim

        for word in words:
            clean = "".join(c for c in word if c.isalnum())
            if not clean:
                continue
            h = hashlib.sha256(clean.encode()).digest()
            for i in range(0, min(len(h), 16), 2):
                idx = int.from_bytes(h[i : i + 2], "big") % self.dim
                val_bytes = h[i + 2 : i + 4] if i + 4 <= len(h) else h[:2]
                val = (int.from_bytes(val_bytes, "big") / 65535.0) * 2 - 1
                vec[idx] += val

        # L2 normalise
        norm = math.sqrt(sum(x * x for x in vec))
        if norm > 0:
            vec = [x / norm for x in vec]
        else:
            h = hashlib.sha256(text.encode()).digest()
            for i in range(self.dim):
                vec[i] = (h[i % len(h)] / 255.0) * 2 - 1
            norm = math.sqrt(sum(x * x for x in vec))
            vec = [x / norm for x in vec]

        return vec

    # OpenAI embeddings

    async def _openai_embed(self, text: str) -> list[float]:
        import httpx

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.openai.com/v1/embeddings",
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                json={"model": settings.embedding_model, "input": text},
                timeout=30.0,
            )
            resp.raise_for_status()
            return resp.json()["data"][0]["embedding"]

    async def _openai_embed_batch(self, texts: list[str]) -> list[list[float]]:
        import httpx

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.openai.com/v1/embeddings",
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                json={"model": settings.embedding_model, "input": texts},
                timeout=60.0,
            )
            resp.raise_for_status()
            data = resp.json()["data"]
            return [d["embedding"] for d in sorted(data, key=lambda x: x["index"])]


embedding_service = EmbeddingService()
