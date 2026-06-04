from pathlib import Path

from lecture_downloader.config import AppConfig
from lecture_downloader.download import DownloadResult
from lecture_downloader.models import LectureMedia
from lecture_downloader.sync import sync_courses
from lecture_downloader.transcribe import TranscriptionResult


def test_sync_summary_counts_downloaded_and_skipped() -> None:
    config = AppConfig(
        section_id="section-id",
        course_name="chem114",
        lectures_dir=Path("lectures") / "CHEM114",
    )

    def fake_finder(config, headed, max_menus, verbose):
        return [
            LectureMedia(
                media_id="0a2feded-d16e-4aa7-976c-27dd3044175d",
                title="Kinetics",
                date="2026-05-13",
            ),
            LectureMedia(
                media_id="f4696157-d8ae-4c10-af11-9e32cca5ef1a",
                title="Equilibrium",
                date="2026-05-14",
            ),
        ]

    def fake_downloader(config, lectures, force, verbose):
        return [
            DownloadResult(
                media_id=lectures[0].media_id,
                path=Path("lectures/CHEM114/2026-05-13_Kinetics/audio.mp3"),
                status="downloaded",
            ),
            DownloadResult(
                media_id=lectures[1].media_id,
                path=Path("lectures/CHEM114/2026-05-14_Equilibrium/audio.mp3"),
                status="skipped",
            ),
        ]

    def fake_transcriber(config, force, verbose):
        return [
            TranscriptionResult(
                media_id="0a2feded-d16e-4aa7-976c-27dd3044175d",
                path=Path("lectures/CHEM114/2026-05-13_Kinetics/transcript.md"),
                status="transcribed",
            ),
            TranscriptionResult(
                media_id="f4696157-d8ae-4c10-af11-9e32cca5ef1a",
                path=Path("lectures/CHEM114/2026-05-14_Equilibrium/transcript.md"),
                status="skipped",
            ),
        ]

    summary = sync_courses(
        [config],
        lecture_finder=fake_finder,
        audio_downloader=fake_downloader,
        transcriber=fake_transcriber,
    )
    data = summary.to_dict()

    assert data["ok"] is True
    assert data["courses_checked"] == ["chem114"]
    assert data["total_ids_found"] == 2
    assert data["total_downloaded"] == 1
    assert data["total_skipped"] == 1
    assert data["total_transcribed"] == 1
    assert data["total_transcripts_skipped"] == 1
    assert data["total_errors"] == 0
    assert data["courses"][0]["downloaded"] == ["0a2feded-d16e-4aa7-976c-27dd3044175d"]
    assert data["courses"][0]["skipped"] == ["f4696157-d8ae-4c10-af11-9e32cca5ef1a"]
    assert data["courses"][0]["downloaded_paths"] == [
        "lectures/CHEM114/2026-05-13_Kinetics/audio.mp3"
    ]
    assert data["courses"][0]["skipped_paths"] == [
        "lectures/CHEM114/2026-05-14_Equilibrium/audio.mp3"
    ]
    assert data["courses"][0]["transcribed"] == ["0a2feded-d16e-4aa7-976c-27dd3044175d"]
    assert data["courses"][0]["skipped_transcripts"] == [
        "f4696157-d8ae-4c10-af11-9e32cca5ef1a"
    ]


def test_sync_succeeds_when_no_lectures_are_found() -> None:
    config = AppConfig(section_id="section-id", course_name="chem114")

    def fake_finder(config, headed, max_menus, verbose):
        return []

    def fake_downloader(config, lectures, force, verbose):
        return []

    summary = sync_courses(
        [config],
        lecture_finder=fake_finder,
        audio_downloader=fake_downloader,
        transcriber=lambda config, force, verbose: [],
    )

    assert summary.ok is True
    assert summary.total_ids_found == 0
    assert summary.total_errors == 0


def test_sync_reports_failed_downloads_and_still_transcribes_available_audio() -> None:
    config = AppConfig(
        section_id="section-id",
        course_name="chem114",
        lectures_dir=Path("lectures") / "CHEM114",
    )

    def fake_finder(config, headed, max_menus, verbose):
        return [
            LectureMedia(media_id="0a2feded-d16e-4aa7-976c-27dd3044175d"),
            LectureMedia(media_id="f4696157-d8ae-4c10-af11-9e32cca5ef1a"),
        ]

    def fake_downloader(config, lectures, force, verbose):
        return [
            DownloadResult(
                media_id=lectures[0].media_id,
                path=Path("lectures/CHEM114/lecture/audio.mp3"),
                status="downloaded",
            ),
            DownloadResult(
                media_id=lectures[1].media_id,
                path=Path("lectures/CHEM114/failed/audio.mp3"),
                status="failed",
                error="Download failed for f4696157-d8ae-4c10-af11-9e32cca5ef1a: HTTP 500",
            ),
        ]

    def fake_transcriber(config, force, verbose):
        return [
            TranscriptionResult(
                media_id="0a2feded-d16e-4aa7-976c-27dd3044175d",
                path=Path("lectures/CHEM114/lecture/transcript.md"),
                status="transcribed",
            )
        ]

    summary = sync_courses(
        [config],
        lecture_finder=fake_finder,
        audio_downloader=fake_downloader,
        transcriber=fake_transcriber,
    )
    data = summary.to_dict()

    assert data["ok"] is False
    assert data["total_downloaded"] == 1
    assert data["total_transcribed"] == 1
    assert data["total_errors"] == 1
    assert "HTTP 500" in data["courses"][0]["errors"][0]


def test_sync_reports_course_error_without_crashing() -> None:
    config = AppConfig(section_id="section-id", course_name="chem114")

    def fake_finder(config, headed, max_menus, verbose):
        raise FileNotFoundError(
            "Missing saved login session: .auth/echo360-state.json. "
            "Run 'lecture-downloader setup-login' first."
        )

    summary = sync_courses([config], lecture_finder=fake_finder)
    data = summary.to_dict()

    assert data["ok"] is False
    assert data["total_errors"] == 1
    assert "Missing saved login session" in data["courses"][0]["errors"][0]
