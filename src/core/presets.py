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
    beam_size: int = 5
    best_of: int = 1
    condition_on_previous_text: bool = True


# Silero VAD defaults used by faster-whisper examples.
DEFAULT_VAD = {"min_silence_duration_ms": 500, "speech_pad_ms": 400}

PRESETS: dict[str, Preset] = {
    "fast": Preset(
        id="fast",
        label="Быстро",
        model="base",
        compute_type="int8",
        description="base + greedy (beam 1) — черновик и короткие голосовые",
        vad_parameters={**DEFAULT_VAD},
        beam_size=1,
        best_of=1,
        condition_on_previous_text=False,
    ),
    "balanced": Preset(
        id="balanced",
        label="Баланс",
        model="small",
        compute_type="int8",
        description="small + beam 2 — рекомендуемый баланс для русского на CPU",
        vad_parameters={**DEFAULT_VAD},
        beam_size=2,
        best_of=1,
        condition_on_previous_text=True,
    ),
    "quality": Preset(
        id="quality",
        label="Качество",
        model="medium",
        compute_type="int8",
        description="medium + beam 5 — близко к дефолту OpenAI Whisper",
        vad_parameters={"min_silence_duration_ms": 700, "speech_pad_ms": 300},
        beam_size=5,
        best_of=1,
        condition_on_previous_text=True,
    ),
}


def get_preset(preset_id: str) -> Preset:
    if preset_id not in PRESETS:
        raise ValueError(f"Unknown preset: {preset_id}. Available: {', '.join(PRESETS)}")
    return PRESETS[preset_id]


def list_presets() -> list[Preset]:
    return list(PRESETS.values())
