from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TypeAlias

from lecture_downloader.browser import _load_playwright
from lecture_downloader.config import AppConfig
from lecture_downloader.extract import UUID_RE
from lecture_downloader.models import LectureMedia


MediaInput: TypeAlias = str | LectureMedia


@dataclass(frozen=True)
class DownloadResult:
    media_id: str
    path: Path
    status: str


@dataclass(frozen=True)
class _DownloadItem:
    media_id: str
    title: str | None = None
    date: str | None = None


def download_audio_files(
    config: AppConfig,
    media_ids: list[MediaInput],
    force: bool = False,
    verbose: bool = False,
) -> list[DownloadResult]:
    if not config.auth_state_path.exists():
        raise FileNotFoundError(
            f"Missing saved login session: {config.auth_state_path}. "
            "Run 'lecture-downloader setup-login' first."
        )

    items = _normalize_media_inputs(media_ids)
    if not items:
        return []

    config.lectures_dir.mkdir(parents=True, exist_ok=True)
    sync_playwright, _ = _load_playwright()
    results: list[DownloadResult] = []

    with sync_playwright() as playwright:
        request_context = playwright.request.new_context(
            storage_state=str(config.auth_state_path)
        )

        try:
            for index, item in enumerate(items, start=1):
                lecture_dir = _lecture_dir(config, item)
                audio_path = lecture_dir / "audio.mp3"
                if audio_path.exists() and not force:
                    _write_metadata(config, item, lecture_dir, downloaded=False)
                    _log(verbose, f"[{index}/{len(items)}] Skipping existing {audio_path}")
                    results.append(DownloadResult(item.media_id, audio_path, "skipped"))
                    continue

                url = config.audio_download_url(item.media_id)
                _log(verbose, f"[{index}/{len(items)}] Downloading {url}")
                response = request_context.get(url, timeout=60_000)
                if not response.ok:
                    raise RuntimeError(
                        f"Download failed for {item.media_id}: HTTP {response.status} {response.status_text}"
                    )

                body = response.body()
                if not body:
                    raise RuntimeError(f"Download failed for {item.media_id}: empty response body")

                lecture_dir.mkdir(parents=True, exist_ok=True)
                _write_bytes_atomically(audio_path, body)
                _write_metadata(config, item, lecture_dir, downloaded=True)
                results.append(DownloadResult(item.media_id, audio_path, "downloaded"))
        finally:
            request_context.dispose()

    return results


def _validate_media_ids(media_ids: list[str]) -> list[str]:
    seen: set[str] = set()
    validated: list[str] = []

    for media_id in media_ids:
        cleaned = media_id.strip().lower()
        if not UUID_RE.fullmatch(cleaned):
            raise ValueError(f"Invalid media ID: {media_id}")
        if cleaned in seen:
            continue
        seen.add(cleaned)
        validated.append(cleaned)

    return validated


def _normalize_media_inputs(media_inputs: list[MediaInput]) -> list[_DownloadItem]:
    seen: set[str] = set()
    items: list[_DownloadItem] = []

    for media_input in media_inputs:
        if isinstance(media_input, LectureMedia):
            media_id = media_input.media_id.strip().lower()
            title = media_input.title
            lecture_date = media_input.date
        else:
            media_id = media_input.strip().lower()
            title = None
            lecture_date = None

        if not UUID_RE.fullmatch(media_id):
            raise ValueError(f"Invalid media ID: {media_id}")
        if media_id in seen:
            continue

        seen.add(media_id)
        items.append(_DownloadItem(media_id=media_id, title=title, date=lecture_date))

    return items


def _lecture_dir(config: AppConfig, item: _DownloadItem) -> Path:
    base_name = _lecture_folder_name(item)
    lecture_dir = config.lectures_dir / base_name
    metadata_path = lecture_dir / "metadata.json"

    if not metadata_path.exists():
        return lecture_dir

    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return lecture_dir

    if metadata.get("media_id") in (None, item.media_id):
        return lecture_dir

    return config.lectures_dir / f"{base_name}_{item.media_id[:8]}"


def _lecture_folder_name(item: _DownloadItem) -> str:
    date_part = item.date or "unknown-date"
    title_part = _slugify(item.title) or "lecture"
    if title_part == "lecture":
        title_part = f"lecture_{item.media_id[:8]}"
    return f"{date_part}_{title_part}"


def _audio_filename(item: _DownloadItem) -> str:
    return str(Path(_lecture_folder_name(item)) / "audio.mp3")


def _slugify(value: str | None) -> str:
    if not value:
        return ""

    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", value)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = cleaned.replace(" ", "-")
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-._")
    return cleaned[:100].strip("-._")


def _write_bytes_atomically(path: Path, body: bytes) -> None:
    temp_path = path.with_suffix(path.suffix + ".part")
    temp_path.write_bytes(body)
    os.replace(temp_path, path)


def _write_metadata(
    config: AppConfig,
    item: _DownloadItem,
    lecture_dir: Path,
    downloaded: bool,
) -> None:
    lecture_dir.mkdir(parents=True, exist_ok=True)
    audio_path = lecture_dir / "audio.mp3"
    metadata_path = lecture_dir / "metadata.json"
    existing: dict[str, object] = {}

    if metadata_path.exists():
        try:
            existing = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            existing = {}

    metadata = {
        **existing,
        "course": config.course_name,
        "section_id": config.section_id,
        "media_id": item.media_id,
        "title": item.title,
        "date": item.date,
        "download_url": config.audio_download_url(item.media_id),
        "audio_path": str(audio_path),
        "transcript_path": str(lecture_dir / "transcript.md"),
        "summary_path": str(lecture_dir / "summary.md"),
        "flashcards_path": str(lecture_dir / "flashcards.json"),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if downloaded or "downloaded_at" not in metadata:
        metadata["downloaded_at"] = datetime.now(timezone.utc).isoformat()

    temp_path = metadata_path.with_suffix(".json.part")
    temp_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp_path, metadata_path)


def _log(verbose: bool, message: str) -> None:
    if verbose:
        print(message, file=sys.stderr, flush=True)
