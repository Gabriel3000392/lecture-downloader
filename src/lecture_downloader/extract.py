from __future__ import annotations

import re
from collections.abc import Iterable


UUID_PATTERN = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
UUID_RE = re.compile(
    rf"\b{UUID_PATTERN}\b"
)

MEDIA_CONTEXT_RE = re.compile(
    r"""
    (?:
        /media/download/|
        /media/|
        /lesson/|
        /capture/|
        media[_-]?id["'\s:=]+|
        mediaId["'\s:=]+|
        mediaUuid["'\s:=]+|
        lesson[_-]?id["'\s:=]+|
        lessonId["'\s:=]+
    )
    (?P<id>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})
    """,
    re.IGNORECASE | re.VERBOSE,
)

THUMBNAIL_CONTEXT_RE = re.compile(
    rf"""
    thumbnails\.echo360[^\s"'<>)]*
    /
    [^/\s"'<>)]*
    /
    (?P<id>{UUID_PATTERN})
    (?=[/?#\s"'<>)]|$)
    """,
    re.IGNORECASE | re.VERBOSE,
)


def extract_media_ids(texts: Iterable[str], excluded_ids: Iterable[str] = ()) -> list[str]:
    excluded = {item.lower() for item in excluded_ids}
    seen: set[str] = set()
    ids: list[str] = []

    for text in texts:
        if not text:
            continue
        for match in _iter_media_matches(text):
            media_id = match.group("id").lower()
            if media_id in excluded or media_id in seen:
                continue
            seen.add(media_id)
            ids.append(media_id)

    return ids


def _iter_media_matches(text: str):
    yield from MEDIA_CONTEXT_RE.finditer(text)
    yield from THUMBNAIL_CONTEXT_RE.finditer(text)


def extract_all_uuids(texts: Iterable[str], excluded_ids: Iterable[str] = ()) -> list[str]:
    excluded = {item.lower() for item in excluded_ids}
    seen: set[str] = set()
    ids: list[str] = []

    for text in texts:
        if not text:
            continue
        for match in UUID_RE.finditer(text):
            item = match.group(0).lower()
            if item in excluded or item in seen:
                continue
            seen.add(item)
            ids.append(item)

    return ids
