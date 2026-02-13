"""FastAPI application — Internal Knowledge Assistant."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import documents, health, query, tenants


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    yield  # DB and Redis are lazily initialised via connection pools


app = FastAPI(
    title="Internal Knowledge Assistant",
    description=(
        "AI-powered document Q&A for internal teams. "
        "Multi-tenant, RAG-based, with caching and audit logging."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

# ── Register routers ───────────────────────────────
app.include_router(health.router, prefix="/api/v1")
app.include_router(tenants.router, prefix="/api/v1")
app.include_router(documents.router, prefix="/api/v1")
app.include_router(query.router, prefix="/api/v1")


@app.get("/")
async def root():
    return {
        "service": "Internal Knowledge Assistant",
        "docs": "/docs",
        "health": "/api/v1/health",
    }
