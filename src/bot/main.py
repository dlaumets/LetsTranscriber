"""Telegram bot. Run: python -m src.bot.main"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import uuid
from pathlib import Path

import httpx
from aiogram import Bot, Dispatcher, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from src.db.repository import get_or_create_telegram_user, get_user_settings
from src.db.session import get_session_factory, init_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = Router()
API_URL = os.getenv("API_URL", "http://localhost:8000")


async def safe_edit_text(message: Message, text: str, **kwargs) -> bool:
    """Edit message text; ignore Telegram 'message is not modified' errors."""
    try:
        await message.edit_text(text, **kwargs)
        return True
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc).lower():
            return False
        raise


def settings_keyboard(preset: str, save_history: bool) -> InlineKeyboardMarkup:
    preset_row = [
        InlineKeyboardButton(
            text=f"{'✓ ' if pid == preset else ''}{label}",
            callback_data=f"preset:{pid}",
        )
        for pid, label in [("fast", "Fast"), ("balanced", "Balanced"), ("quality", "Quality")]
    ]
    save_label = "История: вкл ✓" if save_history else "История: выкл"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            preset_row,
            [InlineKeyboardButton(text=save_label, callback_data="toggle_save")],
        ]
    )


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    factory = get_session_factory()
    async with factory() as session:
        user = await get_or_create_telegram_user(session, message.from_user.id)
        settings = await get_user_settings(session, user.id)

    await message.answer(
        f"Привет! Перешли голосовое — получишь текст.\n\n"
        f"API key: `{user.api_key}`\n"
        f"Preset: {settings.preset if settings else 'balanced'}\n\n"
        f"/settings — настройки\n"
        f"/help — помощь",
        parse_mode="Markdown",
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "Отправь voice, audio или файл (.ogg, .mp3).\n"
        "Длинные записи (>15 мин) обрабатываются в фоне.\n"
        "/settings — preset и сохранение истории."
    )


@router.message(Command("settings"))
async def cmd_settings(message: Message) -> None:
    factory = get_session_factory()
    async with factory() as session:
        user = await get_or_create_telegram_user(session, message.from_user.id)
        settings = await get_user_settings(session, user.id)

    preset = settings.preset if settings else "balanced"
    save = settings.save_history if settings else True
    await message.answer(
        f"Preset: {preset}\nСохранять историю: {'да' if save else 'нет'}",
        reply_markup=settings_keyboard(preset, save),
    )


@router.callback_query(F.data.startswith("preset:"))
async def on_preset(callback: CallbackQuery) -> None:
    preset_id = callback.data.split(":", 1)[1]
    factory = get_session_factory()
    async with factory() as session:
        user = await get_or_create_telegram_user(session, callback.from_user.id)
        settings = await get_user_settings(session, user.id)
        if settings:
            settings.preset = preset_id
            await session.commit()
            save = settings.save_history
        else:
            save = True

    await callback.message.edit_text(
        f"✓ Preset: {preset_id}",
        reply_markup=settings_keyboard(preset_id, save),
    )
    await callback.answer()


@router.callback_query(F.data == "toggle_save")
async def on_toggle_save(callback: CallbackQuery) -> None:
    factory = get_session_factory()
    async with factory() as session:
        user = await get_or_create_telegram_user(session, callback.from_user.id)
        settings = await get_user_settings(session, user.id)
        if settings:
            settings.save_history = not settings.save_history
            await session.commit()
            preset = settings.preset
            save = settings.save_history
        else:
            preset, save = "balanced", True

    await callback.message.edit_text(
        f"Preset: {preset}\nСохранять историю: {'да' if save else 'нет'}",
        reply_markup=settings_keyboard(preset, save),
    )
    await callback.answer()


async def poll_job(api_key: str, job_id: str, status_msg: Message) -> dict:
    """Poll until job completes or fails."""
    delay = 2.0
    last_progress_text = ""
    async with httpx.AsyncClient(timeout=30.0) as client:
        for attempt in range(7200):
            response = await client.get(
                f"{API_URL}/v1/jobs/{job_id}",
                headers={"X-API-Key": api_key},
            )
            response.raise_for_status()
            data = response.json()
            status = data.get("status")

            if status == "completed":
                return data
            if status == "failed":
                raise RuntimeError(data.get("error", "Job failed"))

            if attempt % 3 == 0:
                pct = int(data.get("progress_percent") or 0)
                stage = data.get("progress_stage") or status
                stage_ru = {
                    "loading_model": "модель",
                    "preparing": "подготовка",
                    "transcribing": "распознавание",
                    "finishing": "завершение",
                    "queued": "очередь",
                    "pending": "очередь",
                }.get(stage, stage)
                bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
                progress_text = f"⏳ {stage_ru}\n[{bar}] {pct}%"
                if progress_text != last_progress_text:
                    if await safe_edit_text(status_msg, progress_text):
                        last_progress_text = progress_text

            await asyncio.sleep(delay)
            if delay < 15:
                delay = min(delay * 1.2, 15)

    raise TimeoutError("Job timed out")


async def transcribe_via_api(
    api_key: str,
    file_path: Path,
    status_msg: Message,
    *,
    preset: str,
    language: str,
    save: bool,
) -> dict:
    async with httpx.AsyncClient(timeout=120.0) as client:
        with file_path.open("rb") as f:
            response = await client.post(
                f"{API_URL}/v1/jobs",
                headers={"X-API-Key": api_key},
                data={
                    "preset": preset,
                    "language": language,
                    "save": str(save).lower(),
                    "response_format": "text",
                    "source": "telegram",
                },
                files={"file": (file_path.name, f, "application/octet-stream")},
            )

        if response.status_code == 202:
            data = response.json()
            job_id = data["job_id"]
            await safe_edit_text(status_msg, "⏳ В очереди…")
            return await poll_job(api_key, job_id, status_msg)

        response.raise_for_status()
        return response.json()


async def send_transcription_result(message: Message, status_msg: Message, text: str) -> None:
    result_text = text or "(пусто)"
    if len(result_text) <= 4096:
        await safe_edit_text(status_msg, result_text)
    else:
        await status_msg.delete()
        doc = BufferedInputFile(result_text.encode("utf-8"), filename="transcription.txt")
        await message.answer_document(doc, caption="Текст слишком длинный для сообщения")


@router.message(F.voice | F.audio | F.document)
async def on_audio(message: Message, bot: Bot) -> None:
    status = await message.answer("⏳ Обрабатываю...")

    factory = get_session_factory()
    async with factory() as session:
        user = await get_or_create_telegram_user(session, message.from_user.id)
        settings = await get_user_settings(session, user.id)

    preset = settings.preset if settings else "balanced"
    language = settings.language if settings else "ru"
    save = settings.save_history if settings else True

    if message.voice:
        file_info = message.voice
        suffix = ".ogg"
    elif message.audio:
        file_info = message.audio
        suffix = Path(message.audio.file_name or "audio.mp3").suffix or ".mp3"
    elif message.document:
        file_info = message.document
        suffix = Path(message.document.file_name or "audio.ogg").suffix or ".ogg"
    else:
        await status.edit_text("Неподдерживаемый тип сообщения")
        return

    temp_path = Path(tempfile.gettempdir()) / f"tg_{uuid.uuid4()}{suffix}"
    try:
        await bot.download(file_info, destination=temp_path)
        result = await transcribe_via_api(
            user.api_key,
            temp_path,
            status,
            preset=preset,
            language=language,
            save=save,
        )
        await send_transcription_result(message, status, result.get("text", ""))
    except httpx.HTTPStatusError as exc:
        await safe_edit_text(status, f"Ошибка API: {exc.response.text[:300]}")
    except Exception as exc:
        logger.exception("Transcription failed")
        await safe_edit_text(status, f"Ошибка: {exc}")
    finally:
        temp_path.unlink(missing_ok=True)


def create_dispatcher() -> Dispatcher:
    dp = Dispatcher()
    dp.include_router(router)
    return dp


async def run_polling(bot: Bot, dp: Dispatcher) -> None:
    logger.info("Starting bot (polling)...")
    await dp.start_polling(bot)


async def run_webhook(bot: Bot, dp: Dispatcher) -> None:
    from aiohttp import web
    from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

    webhook_url = os.environ["WEBHOOK_URL"]
    webhook_path = os.getenv("WEBHOOK_PATH", "/bot/webhook")
    host = os.getenv("BOT_HOST", "0.0.0.0")
    port = int(os.getenv("BOT_PORT", "8081"))

    app = web.Application()
    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=webhook_path)
    setup_application(app, dp, bot=bot, webhook_url=webhook_url)

    # setup_application registers startup hooks, but they only run via web.run_app.
    # With AppRunner we must register the webhook explicitly.
    await bot.set_webhook(webhook_url, drop_pending_updates=False)
    info = await bot.get_webhook_info()
    logger.info(
        "Webhook registered: url=%s pending=%s last_error=%s",
        info.url,
        info.pending_update_count,
        info.last_error_message,
    )

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host=host, port=port)
    await site.start()

    logger.info("Webhook server on %s:%s%s → %s", host, port, webhook_path, webhook_url)

    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()
        await bot.session.close()


async def main() -> None:
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise SystemExit("BOT_TOKEN is required")

    await init_db()
    bot = Bot(token=token)
    dp = create_dispatcher()

    if os.getenv("WEBHOOK_URL"):
        await run_webhook(bot, dp)
    else:
        await run_polling(bot, dp)


if __name__ == "__main__":
    asyncio.run(main())
