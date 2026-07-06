# PRD Notes: Transcribe Service

## Raw Requirements

### Из обсуждения (2026-07-03, 2026-07-06)
- Полноценный мини-сервис, не только CLI
- **Telegram-бот** — быстрая пересылка голосовых → текст
- **Простой веб** — кастомизация скорости и качества (пресеты)
- **HTTP API** — подключение из других сервисов, переиспользование
- Переход на **faster-whisper** (пользователь слышал, что быстрее при том же качестве)
- **Предварительная чистка тишины** для ускорения на длинных аудио

### Уточнение по faster-whisper
> **Уже используется.** Проект на `faster-whisper>=1.1.0`, модель `small`, CPU, `int8`.  
> `install.cmd` явно удаляет старый `openai-whisper` / torch.  
> Задача сервиса — не «мигрировать», а **вынести ядро в API** и добавить управление пресетами.

## Constraints

| Constraint | Detail |
|------------|--------|
| Платформа (dev) | Windows 10, локальный `.venv` |
| Железо (default) | CPU, int8 (как в CLI) |
| Язык по умолчанию | `ru` |
| Зависимости | `faster-whisper`, без torch (CTranslate2) |
| Существующий UX | `transcribe.cmd`, Cursor skill `voice-transcribe` |

## Inferred Patterns (from codebase)

| Edge Case | Source | Pattern Applied |
|-----------|--------|-----------------|
| Язык | `transcribe.py:67` default `ru`, `auto` → `None` | Язык конфигурируемый, дефолт RU |
| VAD / тишина | `transcribe.py:33-34` `vad_filter=True`, `min_silence_duration_ms=500` | Встроенный Silero VAD faster-whisper |
| Вывод | `.txt` рядом с файлом или `--json` с сегментами | API: `text` / `json` format |
| Ошибка «файл не найден» | `transcribe.py:84-86` exit 1 + stderr | API: 404/400 с понятным сообщением |
| Последний файл из Downloads | `find-audio.ps1` | Только для CLI/skill, не для бота |
| Модель грузится каждый вызов | `transcribe.py:26` внутри `transcribe()` | **Анти-паттерн** — в сервисе singleton + очередь |
| Форматы | `.ogg`, `.mp3`, `.m4a`, `.wav`, `.webm`, `.aac` | Те же + Telegram voice (ogg/opus) |

## Edge Cases

### Auto-handled (following codebase patterns)
- Пустой результат после VAD → вернуть пустую строку + meta `duration`
- Неизвестный язык при `auto` → faster-whisper определит сам
- Длинный текст в Telegram → разбить на части или отправить `.txt` (лимит 4096 символов)
- Одновременные запросы → очередь (semaphore=1), не параллельная загрузка моделей
- Невалидный аудиофайл → 400 с текстом ошибки ffmpeg/whisper

### Confirmed by User (2026-07-06)
- **Деплой**: VPS / облако (Linux)
- **Аудитория**: публичный бот и API
- **История**: полная история с поиском
- **GPU**: только CPU (int8)
- **Rate limit**: 30 запросов / час на пользователя
- **Макс. длина аудио**: 4 часа
- **Хранение**: только текст + meta; исходники аудио не храним
- **Opt-out истории**: `save=false` — не писать в БД
- **Access**: open access (без captcha / регистрации)

### Open Questions
- (нет — Phase 7 complete)

## Research Findings

### faster-whisper vs openai-whisper
- faster-whisper — CTranslate2, **4–8× быстрее** при том же качестве на CPU
- Меньше RAM, не требует PyTorch
- Проект уже на faster-whisper — выигрыш получен

### VAD и «чистка пустоты»

**Уровень 1 — встроенный VAD (уже есть)**  
`vad_filter=True` в `model.transcribe()` — Silero VAD пропускает участки тишины **во время** распознавания. Не режет файл физически, но Whisper не тратит время на декодирование пауз.

**Уровень 2 — ffmpeg silenceremove (опционально для длинных файлов)**  
Предобработка: вырезать тишину до Whisper. Плюсы: меньше общая длительность → быстрее на подкастах/лекциях с длинными паузами. Минусы: нужен ffmpeg, риск обрезать тихую речь при агрессивных порогах, таймкоды сдвигаются (нужен маппинг).

**Уровень 3 — настраиваемые VAD-параметры**  
- `min_silence_duration_ms` — мин. длина паузы для вырезания (сейчас 500)
- `speech_pad_ms` — паддинг вокруг речи
- `threshold` — чувствительность

**Рекомендация для MVP**: усилить Level 1 (настраиваемый VAD в пресетах). Level 2 — опция `aggressive_silence_trim` для файлов > N минут в Phase 2.

### Оценка ускорения VAD на длинных аудио
| Сценарий | Паузы | Ожидаемый выигрыш |
|----------|-------|-------------------|
| Telegram voice 30–60 с | мало | ~5–15% |
| Совещание 1 ч, 30% тишины | много | ~20–35% |
| Подкаст с музыкой/паузами | средне | ~15–25% |

### Telegram bot stack
- aiogram 3 — async, хорошо стыкуется с FastAPI
- Long polling проще для локального/dev деплоя
- Webhook — для VPS с HTTPS

### API patterns
- FastAPI + multipart upload — стандарт для STT
- OpenAI-compatible `/v1/audio/transcriptions` — опционально для совместимости с tooling

## Architecture Options

### Option A: API-first monolith (RECOMMENDED)
```
Telegram Bot ──┐
Web UI ────────┼──► FastAPI (core + queue) ──► faster-whisper singleton
External API ──┘
```
- **Pros**: один деплой, общая модель в памяти, простая отладка, CLI остаётся
- **Cons**: bot и API в одном процессе или docker-compose с 2 контейнерами на один API

### Option B: Separate microservices
```
Bot → API Gateway → Transcribe Worker (Redis queue)
Web → API Gateway
```
- **Pros**: масштабирование workers
- **Cons**: overkill для личного использования, сложнее ops

### Option C: Bot-only (без отдельного API)
```
Telegram Bot → faster-whisper directly
Web → static settings file
```
- **Pros**: минимум кода
- **Cons**: нет переиспользования API, дублирование логики, модель грузится в bot

**Selected**: **Option A** — API-first monolith с bot и web как thin clients. Соответствует цели «API для других сервисов» и решает проблему singleton модели.

## Presets (Speed ↔ Quality)

| Preset ID | Model | compute_type | VAD | Use case |
|-----------|-------|--------------|-----|----------|
| `fast` | `base` | int8 | on | Быстрые голосовые |
| `balanced` | `small` | int8 | on | Default (как CLI) |
| `quality` | `medium` | int8 | on, stricter | Длинные записи, важна точность |

Optional Phase 2: `quality_gpu` with float16 if CUDA available.
