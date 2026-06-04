import json
from dataclasses import dataclass

from lecture_downloader.config import AppConfig
from lecture_downloader.transcribe import (
    TranscriptSegment,
    find_lecture_dirs_needing_transcription,
    render_transcript_markdown,
    transcribe_course,
)


@dataclass(frozen=True)
class FakeSegment:
    start: float
    end: float
    text: str


class FakeModel:
    def transcribe(self, audio_path: str):
        return (
            [
                FakeSegment(0.0, 2.5, "Welcome to kinetics."),
                FakeSegment(2.5, 5.0, "Reaction rates depend on concentration."),
            ],
            None,
        )


def test_finds_lecture_dirs_needing_transcription(tmp_path) -> None:
    config = AppConfig(
        section_id="section-id",
        course_name="chem114",
        lectures_dir=tmp_path / "lectures" / "CHEM114",
    )
    needs_transcript = config.lectures_dir / "2026-05-13_Kinetics"
    already_done = config.lectures_dir / "2026-05-14_Equilibrium"
    no_audio = config.lectures_dir / "2026-05-15_NoAudio"

    needs_transcript.mkdir(parents=True)
    already_done.mkdir()
    no_audio.mkdir()
    (needs_transcript / "audio.mp3").write_bytes(b"fake")
    (already_done / "audio.mp3").write_bytes(b"fake")
    (already_done / "transcript.md").write_text("done", encoding="utf-8")

    assert find_lecture_dirs_needing_transcription(config) == [needs_transcript]
    assert find_lecture_dirs_needing_transcription(config, force=True) == [
        needs_transcript,
        already_done,
    ]


def test_render_transcript_markdown_contains_metadata_and_segments() -> None:
    config = AppConfig(section_id="section-id", course_name="chem114")
    markdown = render_transcript_markdown(
        config,
        {
            "media_id": "0a2feded-d16e-4aa7-976c-27dd3044175d",
            "title": "Kinetics",
            "date": "2026-05-13",
        },
        [TranscriptSegment(0.0, 2.5, "Welcome to kinetics.")],
        generated_at="2026-05-13T00:00:00+00:00",
    )

    assert 'course: "chem114"' in markdown
    assert 'title: "Kinetics"' in markdown
    assert "[00:00:00.000 --> 00:00:02.500] Welcome to kinetics." in markdown


def test_transcribe_course_writes_transcript_and_updates_metadata(tmp_path) -> None:
    config = AppConfig(
        section_id="section-id",
        course_name="chem114",
        lectures_dir=tmp_path / "lectures" / "CHEM114",
        whisper_model="small",
        whisper_device="cpu",
        whisper_compute_type="int8",
    )
    lecture_dir = config.lectures_dir / "2026-05-13_Kinetics"
    lecture_dir.mkdir(parents=True)
    (lecture_dir / "audio.mp3").write_bytes(b"fake")
    (lecture_dir / "metadata.json").write_text(
        json.dumps(
            {
                "course": "chem114",
                "media_id": "0a2feded-d16e-4aa7-976c-27dd3044175d",
                "title": "Kinetics",
                "date": "2026-05-13",
                "downloaded_at": "already-here",
            }
        ),
        encoding="utf-8",
    )

    results = transcribe_course(config, model_factory=lambda config: FakeModel())
    transcript = (lecture_dir / "transcript.md").read_text(encoding="utf-8")
    metadata = json.loads((lecture_dir / "metadata.json").read_text(encoding="utf-8"))

    assert results[0].status == "transcribed"
    assert results[0].path == lecture_dir / "transcript.md"
    assert "Welcome to kinetics." in transcript
    assert metadata["downloaded_at"] == "already-here"
    assert metadata["transcription_status"] == "transcribed"
    assert metadata["whisper_model"] == "small"


def test_transcribe_course_skips_existing_transcript_without_loading_model(tmp_path) -> None:
    config = AppConfig(
        section_id="section-id",
        course_name="chem114",
        lectures_dir=tmp_path / "lectures" / "CHEM114",
    )
    lecture_dir = config.lectures_dir / "2026-05-13_Kinetics"
    lecture_dir.mkdir(parents=True)
    (lecture_dir / "audio.mp3").write_bytes(b"fake")
    (lecture_dir / "transcript.md").write_text("done", encoding="utf-8")
    (lecture_dir / "metadata.json").write_text(
        '{"media_id": "0a2feded-d16e-4aa7-976c-27dd3044175d"}',
        encoding="utf-8",
    )

    def fail_factory(config):
        raise AssertionError("model should not load when all transcripts already exist")

    results = transcribe_course(config, model_factory=fail_factory)

    assert results[0].status == "skipped"
    assert results[0].media_id == "0a2feded-d16e-4aa7-976c-27dd3044175d"
