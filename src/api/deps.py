from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.repository import get_user_by_api_key
from src.db.session import get_session
from src.db.models import User

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def require_api_key(
    session: SessionDep,
    x_api_key: Annotated[str | None, Header()] = None,
) -> User:
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing X-API-Key header")
    user = await get_user_by_api_key(session, x_api_key)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return user


UserDep = Annotated[User, Depends(require_api_key)]
