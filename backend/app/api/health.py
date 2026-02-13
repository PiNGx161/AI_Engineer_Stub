"""Health check endpoint — verifies PostgreSQL and Redis connectivity."""

from fastapi import APIRouter
from sqlalchemy import text

from app.database import async_session
from app.redis_client import redis_client
from app.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health_check():
    pg_status = "unhealthy"
    redis_status = "unhealthy"

    # Check PostgreSQL
    try:
        async with async_session() as session:
            await session.execute(text("SELECT 1"))
        pg_status = "healthy"
    except Exception:
        pass

    # Check Redis
    try:
        await redis_client.ping()
        redis_status = "healthy"
    except Exception:
        pass

    overall = "healthy" if pg_status == "healthy" and redis_status == "healthy" else "degraded"

    return HealthResponse(
        status=overall,
        postgres=pg_status,
        redis=redis_status,
        version="0.1.0",
    )
