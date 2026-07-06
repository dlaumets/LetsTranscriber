"""Shared transcription helpers for sync and async paths."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException, UploadFile

from src.core.audio import get_audio_duration, validate_extension
from src.core.config import Settings
from src.core.worker import wake_worker
from src.db.jobs import create_job
from src.db.models import User
from src.db.repository import get_user_settings, save_transcription
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class UploadValidation:
    temp_path: Path
    duration: float


async def validate_and_save_upload(
    file: UploadFile,
    temp_dir: Path,
    settings: Settings,
) -> UploadValidation:
    suffix = Path(file.filename or "audio.ogg").suffix.lower() or ".ogg"
    temp_path = temp_dir / f"{uuid.uuid4()}{suffix}"

    content = await file.read()
    if len(content) > settings.max_upload_bytes:
        temp_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=413,
            detail=f"File too large (max {settings.max_upload_mb} MB)",
        )

    temp_path.write_bytes(content)
    try:
        validate_extension(temp_path)
        duration = get_audio_duration(temp_path)
    except ValueError as exc:
        temp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        temp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if duration > settings.max_duration_seconds:
        temp_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=400,
            detail=f"Audio too long ({duration:.0f}s, max {settings.max_duration_hours}h)",
        )

    return UploadValidation(temp_path=temp_path, duration=duration)


async def enqueue_job(
    session: AsyncSession,
    user: User,
    upload: UploadValidation,
    *,
    preset: str,
    language: str,
    task: str,
    response_format: str,
    save: bool,
    source: str,
    jobs_dir: Path,
) -> uuid.UUID:
    """Move file to jobs dir and create DB job."""
    jobs_dir.mkdir(parents=True, exist_ok=True)
    job_path = jobs_dir / upload.temp_path.name
    upload.temp_path.rename(job_path)

    job = await create_job(
        session,
        user_id=user.id,
        file_path=str(job_path),
        duration_seconds=upload.duration,
        preset=preset,
        language=language,
        task=task,
        response_format=response_format,
        save=save,
        source=source,
    )
    wake_worker()
    return job.id


def job_to_response(job) -> dict:
    payload = {
        "job_id": str(job.id),
        "status": job.status,
        "created_at": job.created_at.isoformat(),
        "duration_seconds": job.duration_seconds,
    }
    if job.status == "completed":
        payload["text"] = job.result_text
        payload["meta"] = job.result_meta
        if job.response_format == "json":
            payload["segments"] = job.result_segments
        payload["transcription_id"] = (
            str(job.transcription_id) if job.transcription_id else None
        )
    elif job.status == "failed":
        payload["error"] = job.error_message
    if job.started_at:
        payload["started_at"] = job.started_at.isoformat()
    if job.completed_at:
        payload["completed_at"] = job.completed_at.isoformat()
    return payload


async def persist_sync_result(
    session: AsyncSession,
    user: User,
    *,
    text: str,
    segments: list | None,
    meta: dict,
    response_format: str,
    save: bool,
    source: str,
) -> bool:
    user_settings = await get_user_settings(session, user.id)
    should_save = save and (user_settings.save_history if user_settings else True)
    segments_payload = segments if response_format == "json" else None
    if should_save:
        await save_transcription(
            session,
            user_id=user.id,
            text=text,
            segments=segments_payload,
            meta=meta,
            source=source,
        )
    return should_save
