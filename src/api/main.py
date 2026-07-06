from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from src.api.deps import SessionDep, UserDep
from src.api.transcribe_helpers import (
    enqueue_job,
    job_to_response,
    persist_sync_result,
    validate_and_save_upload,
)
from src.core.config import get_settings
from src.core.presets import list_presets
from src.core.service import get_transcribe_service
from src.core.worker import start_worker, stop_worker
from src.db.jobs import get_job, list_jobs
from src.db.repository import (
    check_rate_limit,
    create_user,
    get_user_settings,
    list_transcriptions,
    record_rate_event,
    search_transcriptions,
)
from src.db.session import close_db, init_db

app = FastAPI(title="Transcribe Service", version="1.1.0")

STATIC_DIR = Path(__file__).resolve().parent.parent / "web" / "static"
DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
TEMP_DIR = DATA_DIR / "temp"
JOBS_DIR = DATA_DIR / "jobs"


@app.on_event("startup")
async def on_startup() -> None:
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    await init_db()
    start_worker()


@app.on_event("shutdown")
async def on_shutdown() -> None:
    await stop_worker()
    await close_db()


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def web_index():
    index = STATIC_DIR / "index.html"
    if index.exists():
        return FileResponse(index)
    return {"message": "Transcribe Service API", "docs": "/docs"}


@app.get("/history")
async def web_history():
    page = STATIC_DIR / "history.html"
    if page.exists():
        return FileResponse(page)
    raise HTTPException(status_code=404, detail="History page not found")


@app.get("/v1/health")
async def health():
    service = get_transcribe_service()
    return {
        "status": "ok",
        "model_loaded": service.model_loaded,
        "current_preset": service.current_preset_id,
        "queue_size": service.queue_size,
    }


@app.get("/v1/presets")
async def presets():
    return {
        "presets": [
            {
                "id": p.id,
                "label": p.label,
                "model": p.model,
                "description": p.description,
            }
            for p in list_presets()
        ]
    }


@app.post("/v1/register")
async def register(session: SessionDep):
    user = await create_user(session)
    return {
        "api_key": user.api_key,
        "user_id": str(user.id),
        "message": "Save your API key — it won't be shown again.",
    }


@app.get("/v1/me")
async def me(user: UserDep, session: SessionDep):
    settings = await get_user_settings(session, user.id)
    return {
        "user_id": str(user.id),
        "telegram_id": user.telegram_id,
        "settings": {
            "preset": settings.preset if settings else "balanced",
            "language": settings.language if settings else "ru",
            "save_history": settings.save_history if settings else True,
        },
    }


@app.patch("/v1/me/settings")
async def update_settings(
    user: UserDep,
    session: SessionDep,
    preset: str | None = Form(default=None),
    language: str | None = Form(default=None),
    save_history: bool | None = Form(default=None),
):
    settings = await get_user_settings(session, user.id)
    if settings is None:
        raise HTTPException(status_code=404, detail="Settings not found")
    if preset is not None:
        from src.core.presets import PRESETS

        if preset not in PRESETS:
            raise HTTPException(status_code=400, detail=f"Unknown preset: {preset}")
        settings.preset = preset
    if language is not None:
        settings.language = language
    if save_history is not None:
        settings.save_history = save_history
    await session.commit()
    return {
        "preset": settings.preset,
        "language": settings.language,
        "save_history": settings.save_history,
    }


async def _check_rate(session: SessionDep, user: UserDep) -> None:
    if not await check_rate_limit(session, user.id):
        raise HTTPException(status_code=429, detail="Rate limit exceeded (30 requests/hour)")


@app.post("/v1/transcribe")
async def transcribe_endpoint(
    session: SessionDep,
    user: UserDep,
    file: UploadFile = File(...),
    preset: str = Form(default="balanced"),
    language: str = Form(default="ru"),
    task: str = Form(default="transcribe"),
    response_format: str = Form(default="text"),
    save: bool = Form(default=True),
    source: str = Form(default="api"),
    force_async: bool = Form(default=False),
):
    settings = get_settings()
    await _check_rate(session, user)

    upload = await validate_and_save_upload(file, TEMP_DIR, settings)

    # Long audio → background job (don't block queue)
    if force_async or upload.duration > settings.async_threshold_seconds:
        job_id = await enqueue_job(
            session,
            user,
            upload,
            preset=preset,
            language=language,
            task=task,
            response_format=response_format,
            save=save,
            source=source,
            jobs_dir=JOBS_DIR,
        )
        await record_rate_event(session, user.id)
        job = await get_job(session, job_id, user.id)
        return JSONResponse(
            status_code=202,
            content={
                **job_to_response(job),
                "message": "Audio queued for background processing",
            },
        )

    try:
        lang = None if language == "auto" else language
        service = get_transcribe_service()
        try:
            result = await asyncio.to_thread(
                service.transcribe,
                upload.temp_path,
                preset_id=preset,
                language=lang,
                task=task,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc

        await record_rate_event(session, user.id)
        should_save = await persist_sync_result(
            session,
            user,
            text=result.text,
            segments=result.segments,
            meta=result.meta,
            response_format=response_format,
            save=save,
            source=source,
        )

        if response_format == "json":
            return {
                "text": result.text,
                "segments": result.segments,
                "meta": result.meta,
                "saved": should_save,
            }
        return {"text": result.text, "meta": result.meta, "saved": should_save}
    finally:
        upload.temp_path.unlink(missing_ok=True)


@app.post("/v1/jobs")
async def create_job_endpoint(
    session: SessionDep,
    user: UserDep,
    file: UploadFile = File(...),
    preset: str = Form(default="balanced"),
    language: str = Form(default="ru"),
    task: str = Form(default="transcribe"),
    response_format: str = Form(default="text"),
    save: bool = Form(default=True),
    source: str = Form(default="api"),
):
    """Always enqueue — returns 202 with job_id."""
    settings = get_settings()
    await _check_rate(session, user)

    upload = await validate_and_save_upload(file, TEMP_DIR, settings)
    job_id = await enqueue_job(
        session,
        user,
        upload,
        preset=preset,
        language=language,
        task=task,
        response_format=response_format,
        save=save,
        source=source,
        jobs_dir=JOBS_DIR,
    )
    await record_rate_event(session, user.id)
    job = await get_job(session, job_id, user.id)
    return JSONResponse(status_code=202, content=job_to_response(job))


@app.get("/v1/jobs")
async def jobs_list(
    user: UserDep,
    session: SessionDep,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
):
    rows, total = await list_jobs(session, user.id, page=page, limit=limit)
    return {
        "items": [job_to_response(j) for j in rows],
        "page": page,
        "limit": limit,
        "total": total,
    }


@app.get("/v1/jobs/{job_id}")
async def job_status(job_id: uuid.UUID, user: UserDep, session: SessionDep):
    job = await get_job(session, job_id, user.id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job_to_response(job)


@app.get("/v1/history")
async def history(
    user: UserDep,
    session: SessionDep,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
):
    rows, total = await list_transcriptions(session, user.id, page=page, limit=limit)
    return {
        "items": [
            {
                "id": str(r.id),
                "text": r.text[:500] + ("..." if len(r.text) > 500 else ""),
                "meta": r.meta,
                "source": r.source,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ],
        "page": page,
        "limit": limit,
        "total": total,
    }


@app.get("/v1/history/search")
async def history_search(
    user: UserDep,
    session: SessionDep,
    q: str = Query(min_length=1),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
):
    rows, total = await search_transcriptions(session, user.id, q, page=page, limit=limit)
    return {
        "query": q,
        "items": [
            {
                "id": str(r.id),
                "text": r.text[:500] + ("..." if len(r.text) > 500 else ""),
                "meta": r.meta,
                "source": r.source,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ],
        "page": page,
        "limit": limit,
        "total": total,
    }


@app.get("/v1/history/{item_id}")
async def history_item(item_id: uuid.UUID, user: UserDep, session: SessionDep):
    from sqlalchemy import select

    from src.db.models import Transcription

    result = await session.execute(
        select(Transcription).where(
            Transcription.id == item_id,
            Transcription.user_id == user.id,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Not found")
    return {
        "id": str(row.id),
        "text": row.text,
        "segments": row.segments,
        "meta": row.meta,
        "source": row.source,
        "created_at": row.created_at.isoformat(),
    }
