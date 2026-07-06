from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import get_settings
from src.db.models import RateLimitEvent, Transcription, User, UserSettings, generate_api_key


async def create_user(
    session: AsyncSession,
    *,
    telegram_id: int | None = None,
) -> User:
    user = User(api_key=generate_api_key(), telegram_id=telegram_id)
    session.add(user)
    await session.flush()
    session.add(UserSettings(user_id=user.id))
    await session.commit()
    await session.refresh(user)
    return user


async def get_user_by_api_key(session: AsyncSession, api_key: str) -> User | None:
    result = await session.execute(select(User).where(User.api_key == api_key))
    return result.scalar_one_or_none()


async def get_user_by_telegram_id(session: AsyncSession, telegram_id: int) -> User | None:
    result = await session.execute(select(User).where(User.telegram_id == telegram_id))
    return result.scalar_one_or_none()


async def get_or_create_telegram_user(session: AsyncSession, telegram_id: int) -> User:
    user = await get_user_by_telegram_id(session, telegram_id)
    if user is None:
        user = await create_user(session, telegram_id=telegram_id)
    return user


async def get_user_settings(session: AsyncSession, user_id: uuid.UUID) -> UserSettings | None:
    result = await session.execute(select(UserSettings).where(UserSettings.user_id == user_id))
    return result.scalar_one_or_none()


async def check_rate_limit(session: AsyncSession, user_id: uuid.UUID) -> bool:
    """Return True if request is allowed."""
    settings = get_settings()
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    result = await session.execute(
        select(func.count())
        .select_from(RateLimitEvent)
        .where(RateLimitEvent.user_id == user_id, RateLimitEvent.created_at >= since)
    )
    count = result.scalar_one()
    return count < settings.rate_limit_per_hour


async def record_rate_event(session: AsyncSession, user_id: uuid.UUID) -> None:
    session.add(RateLimitEvent(user_id=user_id))
    await session.commit()


async def save_transcription(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    text: str,
    segments: list[dict] | None,
    meta: dict,
    source: str,
) -> Transcription:
    row = Transcription(
        user_id=user_id,
        text=text,
        segments=segments,
        meta=meta,
        source=source,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def list_transcriptions(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    page: int = 1,
    limit: int = 20,
) -> tuple[list[Transcription], int]:
    offset = (page - 1) * limit
    total_result = await session.execute(
        select(func.count()).select_from(Transcription).where(Transcription.user_id == user_id)
    )
    total = total_result.scalar_one()

    result = await session.execute(
        select(Transcription)
        .where(Transcription.user_id == user_id)
        .order_by(Transcription.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(result.scalars().all()), total


async def search_transcriptions(
    session: AsyncSession,
    user_id: uuid.UUID,
    query: str,
    *,
    page: int = 1,
    limit: int = 20,
) -> tuple[list[Transcription], int]:
    offset = (page - 1) * limit
    ts_query = func.plainto_tsquery("russian", query)

    base_filter = (
        Transcription.user_id == user_id,
        func.to_tsvector("russian", Transcription.text).op("@@")(ts_query),
    )

    total_result = await session.execute(
        select(func.count()).select_from(Transcription).where(*base_filter)
    )
    total = total_result.scalar_one()

    result = await session.execute(
        select(Transcription)
        .where(*base_filter)
        .order_by(Transcription.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(result.scalars().all()), total
