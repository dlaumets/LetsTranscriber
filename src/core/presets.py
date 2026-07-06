from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Preset:
    id: str
    label: str
    model: str
    compute_type: str
    description: str
    vad_filter: bool = True
    vad_parameters: dict = field(default_factory=dict)


DEFAULT_VAD = {"min_silence_duration_ms": 500, "speech_pad_ms": 400}

PRESETS: dict[str, Preset] = {
    "fast": Preset(
        id="fast",
        label="Быстро",
        model="base",
        compute_type="int8",
        description="Быстрая транскрипция для коротких голосовых",
        vad_parameters={**DEFAULT_VAD},
    ),
    "balanced": Preset(
        id="balanced",
        label="Баланс",
        model="small",
        compute_type="int8",
        description="Оптимальный баланс скорости и качества (по умолчанию)",
        vad_parameters={**DEFAULT_VAD},
    ),
    "quality": Preset(
        id="quality",
        label="Качество",
        model="medium",
        compute_type="int8",
        description="Максимальное качество, медленнее на CPU",
        vad_parameters={"min_silence_duration_ms": 700, "speech_pad_ms": 300},
    ),
}


def get_preset(preset_id: str) -> Preset:
    if preset_id not in PRESETS:
        raise ValueError(f"Unknown preset: {preset_id}. Available: {', '.join(PRESETS)}")
    return PRESETS[preset_id]


def list_presets() -> list[Preset]:
    return list(PRESETS.values())
