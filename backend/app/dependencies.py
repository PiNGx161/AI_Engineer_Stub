"""FastAPI dependencies — tenant resolution via API key header."""

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Tenant


async def get_current_tenant(
    x_api_key: str = Header(..., description="Tenant API key for authentication"),
    db: AsyncSession = Depends(get_db),
) -> Tenant:
    """
    Resolve tenant from X-API-Key header.
    This is the tenant isolation boundary — every downstream query
    is scoped to this tenant's ID.
    """
    result = await db.execute(
        select(Tenant).where(Tenant.api_key == x_api_key, Tenant.is_active.is_(True))
    )
    tenant = result.scalar_one_or_none()
    if tenant is None:
        raise HTTPException(status_code=401, detail="Invalid or inactive API key")
    return tenant
