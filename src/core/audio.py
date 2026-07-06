from __future__ import annotations

import json
import subprocess
from pathlib import Path

ALLOWED_EXTENSIONS = {".ogg", ".oga", ".opus", ".mp3", ".m4a", ".wav", ".webm", ".aac", ".flac"}


def validate_extension(path: Path) -> None:
    ext = path.suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
        raise ValueError(f"Unsupported format '{ext}'. Allowed: {allowed}")


def get_audio_duration(path: Path) -> float:
    """Return duration in seconds via ffprobe."""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_format",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("ffprobe not found; install ffmpeg") from exc
    except subprocess.CalledProcessError as exc:
        raise ValueError("Invalid or corrupt audio file") from exc

    data = json.loads(result.stdout)
    duration = data.get("format", {}).get("duration")
    if duration is None:
        raise ValueError("Could not determine audio duration")
    return float(duration)
