import pytest

from lecture_downloader.config import AppConfig
from lecture_downloader.download import (
    _audio_filename,
    _lecture_dir,
    _lecture_folder_name,
    _normalize_media_inputs,
    _validate_media_ids,
)
from lecture_downloader.models import LectureMedia


def test_validate_media_ids_deduplicates_and_normalizes() -> None:
    ids = _validate_media_ids(
        [
            "0A2FEDED-D16E-4AA7-976C-27DD3044175D",
            "0a2feded-d16e-4aa7-976c-27dd3044175d",
        ]
    )

    assert ids == ["0a2feded-d16e-4aa7-976c-27dd3044175d"]


def test_validate_media_ids_rejects_invalid_id() -> None:
    with pytest.raises(ValueError, match="Invalid media ID"):
        _validate_media_ids(["not-a-real-id"])


def test_lecture_folder_includes_date_and_title() -> None:
    item = _normalize_media_inputs(
        [
            LectureMedia(
                media_id="0a2feded-d16e-4aa7-976c-27dd3044175d",
                title="EMTH117-26S1-LecA-Foundations of Engineering Mathematics",
                date="2026-03-04",
            )
        ]
    )[0]

    assert (
        _lecture_folder_name(item)
        == "2026-03-04_EMTH117-26S1-LecA-Foundations-of-Engineering-Mathematics"
    )
    assert _audio_filename(item).replace("\\", "/") == (
        "2026-03-04_EMTH117-26S1-LecA-Foundations-of-Engineering-Mathematics/audio.mp3"
    )


def test_lecture_folder_falls_back_when_title_and_date_are_unknown() -> None:
    item = _normalize_media_inputs(
        [LectureMedia(media_id="0a2feded-d16e-4aa7-976c-27dd3044175d")]
    )[0]

    assert _lecture_folder_name(item) == "unknown-date_lecture_0a2feded"


def test_lecture_dir_adds_short_id_when_folder_belongs_to_other_media(tmp_path) -> None:
    config = AppConfig(
        section_id="section-id",
        course_name="CHEM114",
        lectures_dir=tmp_path / "lectures" / "CHEM114",
    )
    item = _normalize_media_inputs(
        [
            LectureMedia(
                media_id="0a2feded-d16e-4aa7-976c-27dd3044175d",
                title="Kinetics",
                date="2026-05-13",
            )
        ]
    )[0]
    original_dir = config.lectures_dir / "2026-05-13_Kinetics"
    original_dir.mkdir(parents=True)
    (original_dir / "metadata.json").write_text('{"media_id": "other"}', encoding="utf-8")

    assert str(_lecture_dir(config, item)).replace("\\", "/").endswith(
        "lectures/CHEM114/2026-05-13_Kinetics_0a2feded"
    )
