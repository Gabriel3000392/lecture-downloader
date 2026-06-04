from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from lecture_downloader.browser import find_lectures
from lecture_downloader.config import AppConfig
from lecture_downloader.download import DownloadResult, download_audio_files
from lecture_downloader.models import LectureMedia
from lecture_downloader.transcribe import TranscriptionResult, transcribe_course


LectureFinder = Callable[[AppConfig, bool, int | None, bool], list[LectureMedia]]
AudioDownloader = Callable[[AppConfig, list[LectureMedia], bool, bool], list[DownloadResult]]
Transcriber = Callable[[AppConfig, bool, bool], list[TranscriptionResult]]


@dataclass(frozen=True)
class SyncCourseSummary:
    course: str
    section_id: str
    section_url: str
    lecture_ids_found: list[str]
    downloaded: list[str]
    skipped: list[str]
    downloaded_paths: list[str]
    skipped_paths: list[str]
    transcribed: list[str | None]
    skipped_transcripts: list[str | None]
    transcript_paths: list[str]
    skipped_transcript_paths: list[str]
    output_paths: list[str]
    errors: list[str]


@dataclass(frozen=True)
class SyncSummary:
    ok: bool
    started_at: str
    finished_at: str
    courses_checked: list[str]
    total_ids_found: int
    total_downloaded: int
    total_skipped: int
    total_transcribed: int
    total_transcripts_skipped: int
    total_errors: int
    courses: list[SyncCourseSummary]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def sync_courses(
    configs: list[AppConfig],
    *,
    headed: bool = False,
    max_menus: int | None = None,
    force: bool = False,
    verbose: bool = False,
    lecture_finder: LectureFinder = find_lectures,
    audio_downloader: AudioDownloader = download_audio_files,
    transcriber: Transcriber = transcribe_course,
) -> SyncSummary:
    started_at = _utc_now()
    course_summaries: list[SyncCourseSummary] = []

    for config in configs:
        lecture_ids: list[str] = []
        downloaded: list[str] = []
        skipped: list[str] = []
        downloaded_paths: list[str] = []
        skipped_paths: list[str] = []
        transcribed: list[str | None] = []
        skipped_transcripts: list[str | None] = []
        transcript_paths: list[str] = []
        skipped_transcript_paths: list[str] = []
        output_paths: list[str] = []
        errors: list[str] = []

        try:
            lectures = lecture_finder(config, headed, max_menus, verbose)
            lecture_ids = [lecture.media_id for lecture in lectures]
            results = audio_downloader(config, lectures, force, verbose)

            for result in results:
                path = _path_string(result.path)
                output_paths.append(path)
                if result.status == "downloaded":
                    downloaded.append(result.media_id)
                    downloaded_paths.append(path)
                elif result.status == "skipped":
                    skipped.append(result.media_id)
                    skipped_paths.append(path)

            if config.transcribe_on_sync:
                transcription_results = transcriber(config, force=force, verbose=verbose)
                for result in transcription_results:
                    path = _path_string(result.path)
                    if result.status == "transcribed":
                        transcribed.append(result.media_id)
                        transcript_paths.append(path)
                    elif result.status == "skipped":
                        skipped_transcripts.append(result.media_id)
                        skipped_transcript_paths.append(path)
        except Exception as exc:
            errors.append(str(exc))

        course_summaries.append(
            SyncCourseSummary(
                course=config.course_name,
                section_id=config.section_id,
                section_url=config.section_url,
                lecture_ids_found=lecture_ids,
                downloaded=downloaded,
                skipped=skipped,
                downloaded_paths=downloaded_paths,
                skipped_paths=skipped_paths,
                transcribed=transcribed,
                skipped_transcripts=skipped_transcripts,
                transcript_paths=transcript_paths,
                skipped_transcript_paths=skipped_transcript_paths,
                output_paths=output_paths,
                errors=errors,
            )
        )

    total_errors = sum(len(course.errors) for course in course_summaries)
    return SyncSummary(
        ok=total_errors == 0,
        started_at=started_at,
        finished_at=_utc_now(),
        courses_checked=[config.course_name for config in configs],
        total_ids_found=sum(len(course.lecture_ids_found) for course in course_summaries),
        total_downloaded=sum(len(course.downloaded) for course in course_summaries),
        total_skipped=sum(len(course.skipped) for course in course_summaries),
        total_transcribed=sum(len(course.transcribed) for course in course_summaries),
        total_transcripts_skipped=sum(
            len(course.skipped_transcripts) for course in course_summaries
        ),
        total_errors=total_errors,
        courses=course_summaries,
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _path_string(path: Path) -> str:
    return str(path).replace("\\", "/")
