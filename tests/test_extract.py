from lecture_downloader.extract import extract_all_uuids, extract_media_ids


SECTION_ID = "b1629672-6a5f-4824-abb7-b33fdf7e0e9c"


def test_extracts_media_download_id() -> None:
    ids = extract_media_ids(
        [
            "https://echo360.net.au/media/download/0a2feded-d16e-4aa7-976c-27dd3044175d/audio.mp3"
        ]
    )

    assert ids == ["0a2feded-d16e-4aa7-976c-27dd3044175d"]


def test_extracts_media_id_from_thumbnail_url() -> None:
    ids = extract_media_ids(
        [
            "https://thumbnails.echo360.net.au/0000.334fb942-9266-486b-b37f-3a806b7ff639/0a2feded-d16e-4aa7-976c-27dd3044175d/1/poster1.jpg"
        ]
    )

    assert ids == ["0a2feded-d16e-4aa7-976c-27dd3044175d"]


def test_extracts_ids_from_json_like_media_fields() -> None:
    ids = extract_media_ids(
        [
            '{"mediaId":"11111111-2222-3333-4444-555555555555"}',
            '{"lesson_id":"aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"}',
        ]
    )

    assert ids == [
        "11111111-2222-3333-4444-555555555555",
        "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    ]


def test_deduplicates_and_excludes_section_id() -> None:
    ids = extract_media_ids(
        [
            f"/section/{SECTION_ID}/home",
            "/media/download/0a2feded-d16e-4aa7-976c-27dd3044175d/audio.mp3",
            "/media/download/0a2feded-d16e-4aa7-976c-27dd3044175d/audio.mp3",
        ],
        excluded_ids=[SECTION_ID],
    )

    assert ids == ["0a2feded-d16e-4aa7-976c-27dd3044175d"]


def test_all_uuid_extractor_is_available_for_debugging() -> None:
    ids = extract_all_uuids(
        [
            f"/section/{SECTION_ID}/home",
            "/anything/99999999-8888-7777-6666-555555555555",
        ],
        excluded_ids=[SECTION_ID],
    )

    assert ids == ["99999999-8888-7777-6666-555555555555"]
