from lecture_downloader.browser import _extract_date


def test_extract_date_from_day_month_year_text() -> None:
    assert _extract_date("Lecture Wed 4 Mar 2026 10:00 AM") == "2026-03-04"


def test_extract_date_from_numeric_au_style_text() -> None:
    assert _extract_date("Recorded 04/03/2026") == "2026-03-04"


def test_extract_date_from_iso_text() -> None:
    assert _extract_date("Recorded 2026-03-04") == "2026-03-04"
