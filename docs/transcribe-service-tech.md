# Technical Design: Transcribe Service

> Status: FINAL  
> Last updated: 2026-07-06  
> Product requirements: [transcribe-service-prd.md](./transcribe-service-prd.md)

## Overview

API-first monolith на Python 3.11+. Ядро транскрипции — **faster-whisper** (уже в проекте). FastAPI обслуживает HTTP; Telegram-бот и Web UI — thin clients. Модель Whisper загружается один раз (singleton), запросы обрабатываются через asyncio semaphore.

```
┌─────────────┐  ┌─────────────┐  ┌──────────────┐
│ Telegram    │  │  Web UI     │  │ External     │
│ Bot         │  │  (static)   │  │ clients      │
└──────┬──────┘  └──────┬──────┘  └──────┬───────┘
       │                │                 │
       └────────────────┼─────────────────┘
                        ▼
              ┌─────────────────┐
              │  FastAPI        │
              │  /v1/transcribe │
              │  /v1/health     │
              └────────┬────────┘
                       ▼
              ┌─────────────────┐
              │ TranscribeService│
              │ (singleton)      │
              │ + asyncio lock   │
              └────────┬────────┘
                       ▼
              ┌─────────────────┐
              │ faster-whisper  │
              │ WhisperModel    │
              │ + Silero VAD    │
              └─────────────────┘
```

## Key Components

| Component | Path | Responsibility |
|-----------|------|----------------|
| `TranscribeService` | `src/core/service.py` | Load model, run transcribe, VAD config |
| `Presets` | `src/core/presets.py` | Model size, compute_type, vad params |
| `Config` | `src/core/config.py` | Env vars (API_KEY, DEVICE, etc.) |
| `API` | `src/api/main.py` | FastAPI routes, auth, validation |
| `Bot` | `src/bot/main.py` | aiogram handlers, user settings |
| `Web` | `src/web/static/` | HTML + minimal JS or HTMX |
| `CLI` | `transcribe.py` | Thin wrapper → `TranscribeService` (sync) |

## faster-whisper: текущее состояние и план

**Уже используется** — миграция не нужна.

```python
# transcribe.py (текущее)
MODEL = "small"
DEVICE = "cpu"
COMPUTE_TYPE = "int8"
vad_filter=True
vad_parameters={"min_silence_duration_ms": 500}
```

**Изменения в сервисе:**
1. Модель создаётся **один раз** в `TranscribeService.__init__` или lazy on first request
2. Параметры модели берутся из `Preset`, не hardcoded
3. CLI продолжает работать через тот же `TranscribeService`

## VAD и чистка тишины

### MVP — встроенный VAD (Silero)

faster-whisper вызывает VAD **до** подачи сегментов в Whisper. Тишина не декодируется → экономия CPU на длинных записях.

```python
# src/core/presets.py
@dataclass
class Preset:
    id: str
    model: str
    compute_type: str
    vad_filter: bool = True
    vad_parameters: dict = field(default_factory=lambda: {
        "min_silence_duration_ms": 500,
        "speech_pad_ms": 400,
    })

PRESETS = {
    "fast": Preset("fast", "base", "int8"),
    "balanced": Preset("balanced", "small", "int8"),
    "quality": Preset(
        "quality", "medium", "int8",
        vad_parameters={"min_silence_duration_ms": 700, "speech_pad_ms": 300},
    ),
}
```

**Почему не ffmpeg silenceremove в MVP:**
- VAD уже даёт основной выигрыш без риска обрезать тихую речь
- ffmpeg добавляет зависимость и ломает таймкоды без offset-map
- Имеет смысл для Phase 4: файлы > 30 мин, флаг `pre_trim_silence=true`

### Phase 4 — optional ffmpeg pre-trim

```python
async def maybe_trim_silence(path: Path, threshold_db: float = -40) -> Path:
    """Only if duration > 30min and pre_trim enabled."""
    # ffmpeg -i in.mp3 -af silenceremove=... out.wav
```

## API Design

### POST /v1/transcribe

**Request** (multipart/form-data):
| Field | Type | Required | Default |
|-------|------|----------|---------|
| `file` | binary | yes | — |
| `preset` | string | no | `balanced` |
| `language` | string | no | `ru` |
| `task` | string | no | `transcribe` |
| `response_format` | string | no | `text` |
| `save` | bool | no | `true` — если `false`, результат не пишется в БД |

**Headers:** `X-API-Key: <key>` (required in prod; key выдаётся автоматически при `/start` или первом web-visit)

**Pre-upload validation:**
- ffprobe: duration ≤ **4 hours** → иначе 400
- file size ≤ `MAX_UPLOAD_MB` → иначе 413

**Response 200** (`response_format=text`):
```json
{
  "text": "распознанный текст",
  "meta": {
    "language": "ru",
    "language_probability": 0.98,
    "duration": 45.2,
    "preset": "balanced",
    "processing_time_ms": 8200
  }
}
```

**Response 200** (`response_format=json`):
```json
{
  "text": "...",
  "segments": [
    {"start": 0.0, "end": 2.5, "text": "..."}
  ],
  "meta": { ... }
}
```

**Errors:**
| Code | When |
|------|------|
| 400 | Invalid format, corrupt audio, duration > 4 h |
| 401 | Missing/invalid API key |
| 413 | File > MAX_UPLOAD_BYTES |
| 429 | Rate limit (30/h) or queue full |
| 503 | Model not loaded |

### GET /v1/health
```json
{
  "status": "ok",
  "model_loaded": true,
  "current_preset": "balanced",
  "queue_size": 0
}
```

### GET /v1/presets
```json
{
  "presets": [
    {"id": "fast", "label": "Быстро", "model": "base", "description": "..."},
    {"id": "balanced", "label": "Баланс", "model": "small"},
    {"id": "quality", "label": "Качество", "model": "medium"}
  ]
}
```

### GET /v1/history
Query: `?page=1&limit=20`  
Auth: `X-API-Key` → resolves to `user_id`

### GET /v1/history/search?q=keyword
PostgreSQL `tsvector` full-text search on `transcriptions.text`

## Database Schema (PostgreSQL)

```sql
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    telegram_id BIGINT UNIQUE,
    api_key TEXT UNIQUE NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE user_settings (
    user_id UUID REFERENCES users(id),
    preset TEXT DEFAULT 'balanced',
    language TEXT DEFAULT 'ru',
    save_history BOOLEAN DEFAULT true,
    PRIMARY KEY (user_id)
);

CREATE TABLE transcriptions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id),
    text TEXT NOT NULL,
    segments JSONB,       -- optional, if response_format=json
    meta JSONB NOT NULL,  -- duration, preset, language, processing_time_ms
    source TEXT,          -- 'telegram' | 'api' | 'web'
    created_at TIMESTAMPTZ DEFAULT now()
    -- NOTE: audio files are NOT stored; temp files deleted immediately after processing
);

CREATE INDEX idx_transcriptions_user_created ON transcriptions(user_id, created_at DESC);
CREATE INDEX idx_transcriptions_fts ON transcriptions USING gin(to_tsvector('russian', text));
```

## Data Flow

### Transcription request
```
1. Client uploads file → temp dir (uuid.ext)
2. API validates: size, extension, duration (ffprobe, max 4h)
3. Check rate limit (30 req/h per api_key) → 429 if exceeded
4. Acquire semaphore (wait or 429)
5. TranscribeService.transcribe(path, preset, language)
6. Delete temp file immediately (audio never persisted)
7. If save=true AND user.save_history → INSERT transcriptions
8. Release semaphore
9. Return JSON
```

### Model lifecycle
```python
class TranscribeService:
    _instance: TranscribeService | None = None
    _lock = asyncio.Semaphore(1)

    def __init__(self):
        self._model: WhisperModel | None = None
        self._current_preset: str | None = None

    async def ensure_model(self, preset: Preset) -> WhisperModel:
        if self._current_preset != preset.id:
            self._model = WhisperModel(
                preset.model, device=DEVICE, compute_type=preset.compute_type
            )
            self._current_preset = preset.id
        return self._model
```

Run `model.transcribe()` in `asyncio.to_thread()` — blocking CTranslate2 не блокирует event loop.

## Bot Design

- **Framework:** aiogram 3
- **Mode:** webhook (VPS + HTTPS), not long polling
- **Access:** open — `/start` auto-creates user + API key, no captcha
- **Storage:** PostgreSQL — `users`, `user_settings`, `transcriptions` (text + meta only)
- **Flow:** download → save temp → API → save to DB → reply
- **Config:** `BOT_TOKEN`, `WEBHOOK_URL`, `API_URL`, `API_KEY`

```python
@router.message(F.voice | F.audio)
async def on_voice(message: Message):
    await message.answer("⏳ Обрабатываю...")
    settings = await get_user_settings(message.from_user.id)
    file = await bot.download(message.voice)
    result = await api.transcribe(file, preset=settings.preset, user_id=...)
    await save_transcription(user_id, result)
    await message.answer(result.text[:4096] or "(пусто)")
```

## Web Design

- Single page: `src/web/static/index.html`
- Served by FastAPI `StaticFiles` at `/`
- `fetch('/v1/transcribe', { method: 'POST', body: FormData })`
- No build step (vanilla JS or HTMX)

## Project Structure

```
audio_to_text/
├── docs/
│   ├── transcribe-service-prd.md
│   ├── transcribe-service-tech.md
│   └── ...
├── src/
│   ├── core/
│   │   ├── service.py
│   │   ├── presets.py
│   │   └── config.py
│   ├── api/
│   │   └── main.py
│   ├── bot/
│   │   └── main.py
│   └── web/
│       └── static/
├── transcribe.py          # CLI entry (refactored)
├── transcribe.cmd
├── requirements.txt
├── requirements-service.txt  # fastapi, aiogram, httpx, uvicorn
├── docker-compose.yml
├── .env.example
└── Dockerfile
```

## Configuration (.env.example)

```env
DEVICE=cpu
MAX_UPLOAD_MB=500
MAX_DURATION_HOURS=4
DEFAULT_PRESET=balanced
DEFAULT_LANGUAGE=ru
RATE_LIMIT_PER_HOUR=30

DATABASE_URL=postgresql://transcribe:pass@db:5432/transcribe

BOT_TOKEN=
WEBHOOK_URL=https://your.domain.com/bot/webhook
API_URL=http://api:8000
```

## Docker Compose

```yaml
services:
  api:
    build: .
    ports: ["8000:8000"]
    env_file: .env
    volumes: ["./models-cache:/root/.cache/huggingface"]
    depends_on: [db]
  bot:
    build: .
    command: python -m src.bot.main
    env_file: .env
    depends_on: [api, db]
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: transcribe
      POSTGRES_USER: transcribe
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes: [pgdata:/var/lib/postgresql/data]
  caddy:  # or nginx — HTTPS + webhook
    image: caddy:2-alpine
    ports: ["443:443", "80:80"]
    volumes: ["./Caddyfile:/etc/caddy/Caddyfile"]

volumes:
  pgdata:
```

## Migration Plan

| Step | Action |
|------|--------|
| 1 | Extract `transcribe()` logic → `src/core/service.py` |
| 2 | Update `transcribe.py` to import from core (no behavior change) |
| 3 | Add FastAPI, verify with curl |
| 4 | Add bot + web |
| 5 | Update Cursor skill path if API mode added (optional) |

**Backward compatibility:** CLI calls core directly by default; env `TRANSCRIBE_MODE=api` switches to HTTP client.

## Testing Strategy

| Test | Method |
|------|--------|
| Core unit | pytest with small test audio fixture |
| API | httpx TestClient, mock model optional |
| VAD speed | benchmark 10min audio with/without vad_filter |
| Bot | manual + aiogram test utils |
| Regression | existing voice samples → compare text hash |

## Dependencies

```
# requirements.txt (existing)
faster-whisper>=1.1.0

# requirements-service.txt (new)
fastapi>=0.115
uvicorn[standard]>=0.32
python-multipart>=0.0.12
aiogram>=3.15
httpx>=0.28
aiosqlite>=0.20
pydantic-settings>=2.6
asyncpg>=0.30
sqlalchemy[asyncio]>=2.0
slowapi>=0.1.9          # rate limiting
```

---

*FINAL v1.*
