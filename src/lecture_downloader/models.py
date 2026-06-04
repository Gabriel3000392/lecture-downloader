from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LectureMedia:
    media_id: str
    title: str | None = None
    date: str | None = None
