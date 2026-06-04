from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Protocol

from lecture_downloader.config import AppConfig


@dataclass(frozen=True)
class TranscriptSegment:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class TranscriptionResult:
    media_id: str | None
    path: Path
    status: str


class WhisperModelLike(Protocol):
    def transcribe(self, audio_path: str) -> tuple[Iterable[Any], Any]:
        ...


ModelFactory = Callable[[AppConfig], WhisperModelLike]


def transcribe_course(
    config: AppConfig,
    *,
    force: bool = False,
    verbose: bool = False,
    model_factory: ModelFactory | None = None,
) -> list[TranscriptionResult]:
    to_transcribe, skipped_dirs = find_transcribed_or_skipped_lecture_dirs(config, force=force)
    if not to_transcribe and not skipped_dirs:
        return []

    results: list[TranscriptionResult] = []
    for lecture_dir in skipped_dirs:
        metadata = _read_metadata(lecture_dir)
        media_id = _optional_str(metadata.get("media_id"))
        transcript_path = lecture_dir / "transcript.md"
        _log(verbose, f"Skipping existing {transcript_path}")
        _delete_audio_after_transcript(lecture_dir, metadata, verbose=verbose)
        results.append(TranscriptionResult(media_id, transcript_path, "skipped"))

    if not to_transcribe:
        return results

    model = (model_factory or _load_faster_whisper_model)(config)

    for index, lecture_dir in enumerate(to_transcribe, start=1):
        audio_path = lecture_dir / "audio.mp3"
        transcript_path = lecture_dir / "transcript.md"
        metadata = _read_metadata(lecture_dir)
        media_id = _optional_str(metadata.get("media_id"))

        _log(verbose, f"[{index}/{len(to_transcribe)}] Transcribing {audio_path}")
        raw_segments, _ = model.transcribe(str(audio_path))
        segments = [_normalise_segment(segment) for segment in raw_segments]
        _write_transcript(config, lecture_dir, metadata, segments)
        _write_transcription_metadata(config, lecture_dir, metadata)
        _delete_audio_after_transcript(lecture_dir, _read_metadata(lecture_dir), verbose=verbose)
        results.append(TranscriptionResult(media_id, transcript_path, "transcribed"))

    return results


def find_lecture_dirs_needing_transcription(config: AppConfig, *, force: bool = False) -> list[Path]:
    if not config.lectures_dir.exists():
        return []

    lecture_dirs: list[Path] = []
    for child in sorted(config.lectures_dir.iterdir()):
        if not child.is_dir():
            continue
        audio_path = child / "audio.mp3"
        transcript_path = child / "transcript.md"
        if not audio_path.exists():
            continue
        if transcript_path.exists() and not force:
            continue
        lecture_dirs.append(child)

    return lecture_dirs


def find_transcribed_or_skipped_lecture_dirs(
    config: AppConfig,
    *,
    force: bool = False,
) -> tuple[list[Path], list[Path]]:
    if not config.lectures_dir.exists():
        return [], []

    to_transcribe: list[Path] = []
    skipped: list[Path] = []
    for child in sorted(config.lectures_dir.iterdir()):
        if not child.is_dir() or not (child / "audio.mp3").exists():
            continue
        if (child / "transcript.md").exists() and not force:
            skipped.append(child)
        else:
            to_transcribe.append(child)
    return to_transcribe, skipped


def render_transcript_markdown(
    config: AppConfig,
    metadata: dict[str, Any],
    segments: list[TranscriptSegment],
    *,
    generated_at: str,
) -> str:
    title = _optional_str(metadata.get("title")) or "Lecture transcript"
    lines = [
        "---",
        f"course: {_yaml_value(config.course_name)}",
        f"media_id: {_yaml_value(_optional_str(metadata.get('media_id')))}",
        f"title: {_yaml_value(_optional_str(metadata.get('title')))}",
        f"date: {_yaml_value(_optional_str(metadata.get('date')))}",
        f"whisper_model: {_yaml_value(config.whisper_model)}",
        f"whisper_device: {_yaml_value(config.whisper_device)}",
        f"whisper_compute_type: {_yaml_value(config.whisper_compute_type)}",
        f"generated_at: {_yaml_value(generated_at)}",
        "---",
        "",
        f"# {title}",
        "",
    ]

    for segment in segments:
        text = segment.text.strip()
        if not text:
            continue
        lines.append(f"[{_format_timestamp(segment.start)} --> {_format_timestamp(segment.end)}] {text}")

    lines.append("")
    return "\n".join(lines)


def _load_faster_whisper_model(config: AppConfig) -> WhisperModelLike:
    try:
        from faster_whisper import WhisperModel
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "faster-whisper is not installed. Run: python -m pip install -e ."
        ) from exc

    return WhisperModel(
        config.whisper_model,
        device=config.whisper_device,
        compute_type=config.whisper_compute_type,
    )


def _normalise_segment(segment: Any) -> TranscriptSegment:
    return TranscriptSegment(
        start=float(getattr(segment, "start")),
        end=float(getattr(segment, "end")),
        text=str(getattr(segment, "text")),
    )


def _write_transcript(
    config: AppConfig,
    lecture_dir: Path,
    metadata: dict[str, Any],
    segments: list[TranscriptSegment],
) -> None:
    generated_at = _utc_now()
    transcript_path = lecture_dir / "transcript.md"
    content = render_transcript_markdown(
        config,
        metadata,
        segments,
        generated_at=generated_at,
    )
    temp_path = transcript_path.with_suffix(".md.part")
    temp_path.write_text(content, encoding="utf-8")
    os.replace(temp_path, transcript_path)


def _write_transcription_metadata(
    config: AppConfig,
    lecture_dir: Path,
    metadata: dict[str, Any],
) -> None:
    metadata_path = lecture_dir / "metadata.json"
    transcript_path = lecture_dir / "transcript.md"
    updated = {
        **metadata,
        "transcript_path": str(transcript_path),
        "transcribed_at": _utc_now(),
        "transcription_status": "transcribed",
        "whisper_model": config.whisper_model,
        "whisper_device": config.whisper_device,
        "whisper_compute_type": config.whisper_compute_type,
        "updated_at": _utc_now(),
    }
    temp_path = metadata_path.with_suffix(".json.part")
    temp_path.write_text(json.dumps(updated, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp_path, metadata_path)


def _delete_audio_after_transcript(
    lecture_dir: Path,
    metadata: dict[str, Any],
    *,
    verbose: bool,
) -> None:
    audio_path = lecture_dir / "audio.mp3"
    transcript_path = lecture_dir / "transcript.md"
    if not audio_path.exists() or not transcript_path.exists():
        return

    audio_path.unlink()
    _log(verbose, f"Deleted transcribed audio {audio_path}")
    _write_audio_deleted_metadata(lecture_dir, metadata, audio_path)


def _write_audio_deleted_metadata(
    lecture_dir: Path,
    metadata: dict[str, Any],
    audio_path: Path,
) -> None:
    metadata_path = lecture_dir / "metadata.json"
    updated = {
        **metadata,
        "audio_deleted_at": _utc_now(),
        "audio_deleted_path": str(audio_path),
        "updated_at": _utc_now(),
    }
    temp_path = metadata_path.with_suffix(".json.part")
    temp_path.write_text(json.dumps(updated, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp_path, metadata_path)


def _read_metadata(lecture_dir: Path) -> dict[str, Any]:
    metadata_path = lecture_dir / "metadata.json"
    if not metadata_path.exists():
        return {}
    try:
        return json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _format_timestamp(seconds: float) -> str:
    total_ms = round(seconds * 1000)
    total_seconds, ms = divmod(total_ms, 1000)
    minutes, sec = divmod(total_seconds, 60)
    hours, minute = divmod(minutes, 60)
    return f"{hours:02}:{minute:02}:{sec:02}.{ms:03}"


def _yaml_value(value: str | None) -> str:
    if value is None:
        return "null"
    return json.dumps(value)


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log(verbose: bool, message: str) -> None:
    if verbose:
        print(message, file=sys.stderr, flush=True)
