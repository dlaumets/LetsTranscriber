# PRD: Transcribe Service

> Status: FINAL  
> Last updated: 2026-07-06  
> Technical design: [transcribe-service-tech.md](./transcribe-service-tech.md)

## Table of Contents
- [Problem Statement](#problem-statement)
- [Goals and Non-Goals](#goals-and-non-goals)
- [Success Criteria](#success-criteria)
- [Scope](#scope)
- [Requirements](#requirements)
- [User Flows](#user-flows)
- [Implementation Plan](#implementation-plan)

---

## Problem Statement

Сейчас транскрипция работает только через CLI (`transcribe.cmd`) и Cursor skill. Чтобы получить текст из голосового, нужно вручную запускать скрипт или прикреплять файл в чат с агентом. Нет:

- быстрого канала «переслал в Telegram → получил текст»;
- веб-интерфейса для настройки скорости/качества без правки кода;
- HTTP API для интеграции в другие сервисы (CRM, n8n, собственные боты).

Ядро на **faster-whisper** уже есть и даёт хорошее качество на CPU. Задача — обернуть его в сервис с тремя точками входа, сохранив CLI для локального использования.

## Goals and Non-Goals

### Goals
- Telegram-бот: голосовое / аудио → текст за ≤ 30 с для типичного voice (≤ 1 мин)
- HTTP API: `POST /v1/transcribe` с пресетами скорость/качество
- Веб-страница: выбор пресета, языка, загрузка файла, просмотр результата
- Единое ядро транскрипции с **singleton-моделью** и очередью запросов
- Настраиваемый **VAD** (фильтрация тишины) — включён по умолчанию, параметры зависят от пресета
- Сохранить существующий CLI и Cursor skill без регрессий

### Non-Goals (MVP)
- Биллинг и платёжная система
- Real-time streaming transcription (WebSocket)
- Speaker diarization («кто говорил»)
- Мобильное приложение
- Fine-tuning моделей
- GPU / CUDA (только CPU int8)

## Success Criteria

| Metric | Target |
|--------|--------|
| Telegram voice 60 с, preset `balanced` | Ответ ≤ 30 с на CPU (small/int8) |
| API uptime (VPS) | Healthcheck 200, модель загружена |
| Rate limit | 30 req/h per user, 429 при превышении |
| Max audio duration | 4 h; 413/400 если длиннее |
| History opt-out | `save=false` → ответ без записи в БД |
| Качество RU | Не хуже текущего CLI на тестовых 10 голосовых |
| VAD на записи с 30% пауз | Ускорение ≥ 15% vs VAD off |
| API интеграция | curl / n8n может отправить файл и получить JSON |
| CLI | `transcribe.cmd` работает как раньше |

## Scope

### In Scope (MVP — Phase 1–3)

**Phase 1 — Core + API**
- Рефактор `transcribe.py` → модуль `core/` (service, presets, config)
- FastAPI: transcribe, health, presets list
- API key auth (один ключ)
- Очередь: 1 concurrent transcription
- Docker Compose (API + optional Redis stub)

**Phase 2 — Telegram Bot**
- aiogram 3, long polling
- Voice, audio, document (ogg/mp3)
- Per-user settings (preset, language) в SQLite
- Длинный текст → файл `.txt`
- Статус «обрабатываю…»

**Phase 3 — Web UI**
- Одна страница: drag-drop, пресеты, язык, результат
- Показ meta (duration, detected language)
- Без авторизации (локально) или тот же API key

### Out of Scope (MVP)
- ffmpeg silenceremove pre-trim — Phase 4 (опция для файлов > 30 мин)
- OpenAI-compatible endpoint — Phase 4
- GPU / CUDA — не планируется (CPU only)
- Биллинг / подписки

### Confirmed scope additions (2026-07-06)
- **VPS Linux** — production deploy, Telegram webhook
- **Публичный доступ** — open access, auto API key при `/start` или первом web-visit
- **Полная история** — PostgreSQL, поиск по тексту; **только text + meta**, аудио не храним
- **Opt-out** — `save=false` пропускает запись в БД
- **Limits** — 30 req/h, max audio 4 h

## Requirements

### Functional

#### F1 — Transcription Core
- F1.1 Поддержка форматов: ogg, opus, mp3, m4a, wav, webm, aac
- F1.2 Пресеты: `fast` (base), `balanced` (small), `quality` (medium)
- F1.3 Язык: `ru` (default), `auto`, любой ISO-код Whisper
- F1.4 Task: `transcribe` | `translate` (→ EN)
- F1.5 VAD включён по умолчанию; параметры настраиваются per-preset
- F1.6 Response: plain text или JSON (text + segments + meta)

#### F2 — HTTP API
- F2.1 `POST /v1/transcribe` — multipart file + query params
- F2.2 `GET /v1/health` — status, loaded model, queue depth
- F2.3 `GET /v1/presets` — список пресетов с описанием
- F2.4 `GET /v1/history` — список транскрипций пользователя (pagination)
- F2.5 `GET /v1/history/{id}` — одна запись с segments
- F2.6 `GET /v1/history/search?q=` — полнотекстовый поиск
- F2.7 Auth: per-user `X-API-Key` (выдаётся автоматически, open access)
- F2.8 Rate limit: **30 req/hour** per key (429)
- F2.9 Param `save` (bool, default `true`) — если `false`, не писать в историю
- F2.10 Max duration: **4 hours**; reject longer files (400)
- F2.11 Errors: 400 invalid file / too long, 413 too large (bytes), 429 rate/queue limit, 500 internal

#### F3 — Telegram Bot
- F3.1 Команды: `/start` (auto-register + API key), `/settings`, `/help`, `/history`
- F3.2 Обработка voice, audio, document
- F3.3 Inline-кнопки: preset, toggle «Сохранять историю»
- F3.4 Ответ текстом; fallback — document при > 4000 символов
- F3.5 Open access — любой может `/start` без модерации

#### F4 — Web UI
- F4.1 Upload файла
- F4.2 Выбор preset, language, translate toggle
- F4.3 Отображение результата + кнопка «копировать»
- F4.4 Индикатор прогресса / «идёт обработка»

#### F5 — CLI (backward compatible)
- F5.1 `transcribe.cmd` вызывает core или API (config flag)
- F5.2 Cursor skill `voice-transcribe` без изменений в UX

### Non-Functional
- NFR1 Memory: одна модель в RAM (~500 MB–1.5 GB по preset)
- NFR2 Security: API key в env; bot token в env; не логировать содержимое аудио
- NFR3 Temp files: удалять сразу после обработки (аудио не персистим)
- NFR4 Max file size: 25 MB per upload chunk; длинные файлы — async job + streaming upload (Phase 4) или multipart до 4 h при достаточном диске на VPS
- NFR5 Max duration: 4 h (проверка через ffprobe до транскрипции)

## User Flows

### UF1 — Telegram voice
```
User → forward voice to bot
Bot → "⏳ Обрабатываю..."
Bot → download file → POST /v1/transcribe (user preset)
API → VAD + whisper → text
Bot → reply with text (or .txt file)
```

### UF2 — Web upload
```
User → open localhost:8080
User → drop audio, select "fast", language "ru"
User → click "Transcribe"
UI → POST /v1/transcribe → show result + duration
```

### UF3 — External API (n8n / script)
```
curl -X POST http://host:8000/v1/transcribe \
  -H "X-API-Key: $KEY" \
  -F "file=@meeting.mp3" \
  -F "preset=quality" \
  -F "language=auto" \
  -F "save=false" \
  -F "response_format=json"
```

### UF4 — Settings in Telegram
```
User → /settings
Bot → "Preset: balanced [Fast] [Balanced] [Quality]"
User → tap Quality
Bot → "✓ Preset: quality"
```

## Implementation Plan

| Phase | Deliverable | Effort |
|-------|-------------|--------|
| **1** | `core/`, FastAPI, PostgreSQL, docker-compose | 2–3 дня |
| **2** | Telegram bot (webhook) + user keys + history | 1–2 дня |
| **3** | Web UI + history search | 1–2 дня |
| **4** | Async jobs (длинные файлы), ffmpeg trim, OpenAI-compat | по необходимости |

### Milestone order
1. API работает локально, curl-тест проходит
2. Bot отвечает на голосовые через API
3. Web настраивает preset и показывает результат
4. CLI/skill проверены на регрессию

### Risks & mitigations
| Risk | Mitigation |
|------|------------|
| Model reload on preset change | Cache last 1 preset or lazy reload with 10s timeout message |
| CPU overload on 4h file | Async job queue (Phase 4); semaphore=1 for sync MVP |
| Telegram 4096 char limit | Split message or send .txt |
| medium model OOM | Default balanced; quality opt-in with warning |
| 4h file blocks queue | Async jobs for files > 15 min (Phase 1.5) |
| Open access abuse | Rate limit 30/h; monitor queue depth |

### UF5 — Opt-out from history
```
User → /settings → toggle "Сохранять историю" OFF
User → sends voice
Bot → transcribes, replies, does NOT write to DB
```

---

*FINAL v1. См. [transcribe-service-prd-notes.md](./transcribe-service-prd-notes.md).*
