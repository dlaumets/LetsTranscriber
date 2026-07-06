#!/usr/bin/env python3
"""Transcribe voice messages with faster-whisper."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.core.presets import get_preset
from src.core.service import get_transcribe_service


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Transcribe voice messages (faster-whisper)",
        epilog="Example: transcribe C:\\path\\voice.ogg",
    )
    parser.add_argument("audio", help="Path to audio file (.ogg, .mp3, .wav, ...)")
    parser.add_argument(
        "-l",
        "--language",
        default="ru",
        help="Language code (default: ru). Use 'auto' to detect.",
    )
    parser.add_argument(
        "-p",
        "--preset",
        default="balanced",
        choices=["fast", "balanced", "quality"],
        help="Speed/quality preset (default: balanced)",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Output file (.txt or .json). Default: <audio>.txt next to source",
    )
    parser.add_argument("--json", action="store_true", help="Save segments with timestamps")
    parser.add_argument(
        "--translate",
        action="store_true",
        help="Translate to English instead of transcribing",
    )
    args = parser.parse_args()

    audio_path = Path(args.audio).expanduser().resolve()
    if not audio_path.exists():
        print(f"File not found: {audio_path}", file=sys.stderr)
        return 1

    language = None if args.language == "auto" else args.language
    task = "translate" if args.translate else "transcribe"

    preset = get_preset(args.preset)
    print(f"Loading preset '{preset.id}' (model={preset.model})...", file=sys.stderr)
    print(f"Transcribing: {audio_path}", file=sys.stderr)

    service = get_transcribe_service()
    result = service.transcribe(
        audio_path,
        preset_id=preset.id,
        language=language,
        task=task,
    )

    if args.json:
        payload = {"text": result.text, "meta": result.meta, "segments": result.segments}
        out_path = Path(args.output) if args.output else audio_path.with_suffix(".json")
        out_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        out_path = Path(args.output) if args.output else audio_path.with_suffix(".txt")
        out_path.write_text(result.text, encoding="utf-8")
        print(result.text)

    print(f"\nSaved: {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
