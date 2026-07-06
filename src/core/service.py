from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path

from src.core.config import get_settings
from src.core.presets import Preset, get_preset


@dataclass
class TranscriptionResult:
    text: str
    segments: list[dict]
    meta: dict


class TranscribeService:
    _instance: TranscribeService | None = None
    _instance_lock = threading.Lock()

    def __init__(self) -> None:
        self._settings = get_settings()
        self._model = None
        self._current_preset_id: str | None = None
        self._model_lock = threading.Lock()
        self._queue_lock = threading.Lock()
        self._queue_size = 0

    @classmethod
    def get_instance(cls) -> TranscribeService:
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @property
    def model_loaded(self) -> bool:
        return self._model is not None

    @property
    def current_preset_id(self) -> str | None:
        return self._current_preset_id

    @property
    def queue_size(self) -> int:
        with self._queue_lock:
            return self._queue_size

    def _ensure_model(self, preset: Preset):
        from faster_whisper import WhisperModel

        if self._current_preset_id == preset.id and self._model is not None:
            return self._model

        with self._model_lock:
            if self._current_preset_id == preset.id and self._model is not None:
                return self._model

            self._model = WhisperModel(
                preset.model,
                device=self._settings.device,
                compute_type=preset.compute_type,
            )
            self._current_preset_id = preset.id
            return self._model

    def transcribe(
        self,
        audio_path: Path,
        *,
        preset_id: str = "balanced",
        language: str | None = "ru",
        task: str = "transcribe",
    ) -> TranscriptionResult:
        preset = get_preset(preset_id)
        started = time.perf_counter()

        with self._queue_lock:
            if self._queue_size >= self._settings.queue_max_size:
                raise RuntimeError("Queue is full, try again later")
            self._queue_size += 1

        try:
            model = self._ensure_model(preset)
            segments_iter, info = model.transcribe(
                str(audio_path),
                language=language,
                task=task,
                vad_filter=preset.vad_filter,
                vad_parameters=preset.vad_parameters,
            )

            segments: list[dict] = []
            parts: list[str] = []
            for segment in segments_iter:
                parts.append(segment.text)
                segments.append(
                    {
                        "start": segment.start,
                        "end": segment.end,
                        "text": segment.text,
                    }
                )

            elapsed_ms = int((time.perf_counter() - started) * 1000)
            text = "".join(parts).strip()
            meta = {
                "language": info.language,
                "language_probability": info.language_probability,
                "duration": info.duration,
                "preset": preset.id,
                "processing_time_ms": elapsed_ms,
            }
            return TranscriptionResult(text=text, segments=segments, meta=meta)
        finally:
            with self._queue_lock:
                self._queue_size -= 1


def get_transcribe_service() -> TranscribeService:
    return TranscribeService.get_instance()
