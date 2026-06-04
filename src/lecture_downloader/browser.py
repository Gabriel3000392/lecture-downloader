from __future__ import annotations

import os
import re
import sys
from collections.abc import Iterable
from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.sync_api import Page

from lecture_downloader.config import AppConfig
from lecture_downloader.extract import extract_media_ids
from lecture_downloader.models import LectureMedia


def save_login_session(config: AppConfig) -> None:
    sync_playwright, _ = _load_playwright()
    config.auth_state_path.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(config.section_url, wait_until="domcontentloaded")

        print("A browser window is open for Echo360 login.")
        print("Log in with Microsoft and wait until the section page is visible.")
        input("Press Enter here when you are fully logged in...")

        context.storage_state(path=str(config.auth_state_path))
        browser.close()

    print(f"Saved login session to {config.auth_state_path}")


def find_ids(
    config: AppConfig,
    headed: bool = False,
    max_menus: int | None = None,
    verbose: bool = False,
) -> list[str]:
    return [
        lecture.media_id
        for lecture in find_lectures(
            config,
            headed=headed,
            max_menus=max_menus,
            verbose=verbose,
        )
    ]


def find_lectures(
    config: AppConfig,
    headed: bool = False,
    max_menus: int | None = None,
    verbose: bool = False,
) -> list[LectureMedia]:
    sync_playwright, _ = _load_playwright()
    if not config.auth_state_path.exists():
        raise FileNotFoundError(
            f"Missing saved login session: {config.auth_state_path}. "
            "Run 'lecture-downloader setup-login' first."
        )

    observed_texts: list[str] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False if headed else config.headless)
        context = browser.new_context(storage_state=str(config.auth_state_path))
        page = context.new_page()

        _collect_network_urls(page, observed_texts)
        _log(verbose, f"Opening {config.section_url}")
        page.goto(config.section_url, wait_until="domcontentloaded")
        _wait_for_page_to_settle(page, verbose)
        _collect_page_text(page, observed_texts)
        lectures = _open_video_menus(
            page,
            observed_texts,
            excluded_ids=[config.section_id],
            max_menus=max_menus,
            verbose=verbose,
        )

        browser.close()

    seen = {lecture.media_id for lecture in lectures}
    for media_id in extract_media_ids(observed_texts, excluded_ids=[config.section_id]):
        if media_id not in seen:
            lectures.append(LectureMedia(media_id=media_id))
            seen.add(media_id)

    _log(verbose, f"Found {len(lectures)} lecture/media ID(s).")
    return lectures


def _collect_network_urls(page: "Page", observed_texts: list[str]) -> None:
    page.on("request", lambda request: observed_texts.append(request.url))
    page.on("response", lambda response: _collect_response_text(response, observed_texts))


def _collect_response_text(response, observed_texts: list[str]) -> None:
    observed_texts.append(response.url)

    content_type = response.headers.get("content-type", "").lower()
    if not any(
        item in content_type
        for item in ("application/json", "text/", "javascript", "application/xml")
    ):
        return

    try:
        observed_texts.append(response.text())
    except Exception:
        return


def _wait_for_page_to_settle(page: "Page", verbose: bool) -> None:
    _, playwright_timeout_error = _load_playwright()
    _log(verbose, "Waiting briefly for the lecture page to load...")
    try:
        page.wait_for_load_state("networkidle", timeout=8_000)
    except playwright_timeout_error:
        _log(verbose, "Page is still making requests; continuing anyway.")

    try:
        page.wait_for_timeout(1_000)
    except playwright_timeout_error:
        pass


def _collect_page_text(page: "Page", observed_texts: list[str]) -> None:
    observed_texts.append(page.url)
    observed_texts.append(page.content())
    observed_texts.extend(_evaluate_string_list(page, _LINKS_SCRIPT))
    observed_texts.extend(_evaluate_string_list(page, _SCRIPT_TEXT_SCRIPT))


def _open_video_menus(
    page: "Page",
    observed_texts: list[str],
    excluded_ids: list[str],
    max_menus: int | None,
    verbose: bool,
) -> list[LectureMedia]:
    menu_buttons = page.locator(_VIDEO_MENU_SELECTOR)
    lectures: list[LectureMedia] = []
    seen_ids: set[str] = set()

    try:
        count = menu_buttons.count()
    except Exception:
        _log(verbose, "Could not count video menu buttons.")
        return lectures

    if count == 0:
        _log(verbose, "No video menu buttons found on the page.")
        return lectures

    limit = min(count, max_menus) if max_menus is not None else count
    _log(verbose, f"Found {count} video menu button(s); opening {limit}.")

    for index in range(limit):
        button = menu_buttons.nth(index)
        try:
            _log(verbose, f"Opening video menu {index + 1}/{limit}...")
            metadata = _read_menu_metadata(button)
            start_index = len(observed_texts)
            button.scroll_into_view_if_needed(timeout=2_000)
            _click_video_menu_button(button)
            page.wait_for_timeout(700)
            _collect_page_text(page, observed_texts)
            new_texts = observed_texts[start_index:]
            for media_id in extract_media_ids(new_texts, excluded_ids=excluded_ids):
                if media_id in seen_ids:
                    continue
                lectures.append(
                    LectureMedia(
                        media_id=media_id,
                        title=metadata.get("title") or None,
                        date=_extract_date(metadata.get("rowText", "")),
                    )
                )
                seen_ids.add(media_id)
            page.keyboard.press("Escape")
        except Exception as exc:
            _log(verbose, f"Skipped video menu {index + 1}; it could not be opened: {exc}")
            continue

    return lectures


def _evaluate_string_list(page: "Page", script: str) -> Iterable[str]:
    try:
        value = page.evaluate(script)
    except Exception:
        return []

    if not isinstance(value, list):
        return []

    return [item for item in value if isinstance(item, str)]


def _click_video_menu_button(button) -> None:
    try:
        button.click(timeout=2_000)
        return
    except Exception:
        pass

    button.evaluate(
        """
        (element) => {
          element.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
          element.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
          element.dispatchEvent(new MouseEvent('click', { bubbles: true }));
        }
        """
    )


def _read_menu_metadata(button) -> dict[str, str]:
    try:
        value = button.evaluate(
            """
            (element) => {
              const menu =
                element.closest('[aria-label^="Open Video Menu"]') ||
                element.closest('[aria-label]');
              const label = menu ? (menu.getAttribute('aria-label') || '') : '';
              const title = label.replace(/^Open Video Menu for\\s+/i, '').trim();
              const chunks = [];
              let current = element;
              for (let index = 0; index < 8 && current; index += 1) {
                const text = (current.innerText || '').trim().replace(/\\s+/g, ' ');
                if (text && text.length <= 1000) {
                  chunks.push(text);
                }
                current = current.parentElement;
              }
              return { title, rowText: chunks.join('\\n') };
            }
            """
        )
    except Exception:
        return {}

    if not isinstance(value, dict):
        return {}

    return {
        str(key): str(item)
        for key, item in value.items()
        if isinstance(key, str) and isinstance(item, str)
    }


def _extract_date(text: str) -> str | None:
    if not text:
        return None

    iso_match = re.search(r"\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b", text)
    if iso_match:
        return _format_date(
            int(iso_match.group(1)),
            int(iso_match.group(2)),
            int(iso_match.group(3)),
        )

    numeric_match = re.search(r"\b(\d{1,2})[/-](\d{1,2})[/-](20\d{2}|\d{2})\b", text)
    if numeric_match:
        year = int(numeric_match.group(3))
        if year < 100:
            year += 2000
        return _format_date(year, int(numeric_match.group(2)), int(numeric_match.group(1)))

    day_month_match = re.search(
        r"\b(\d{1,2})\s+"
        r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
        r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
        r"\s+(20\d{2})\b",
        text,
        re.IGNORECASE,
    )
    if day_month_match:
        return _format_date(
            int(day_month_match.group(3)),
            _month_number(day_month_match.group(2)),
            int(day_month_match.group(1)),
        )

    month_day_match = re.search(
        r"\b"
        r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
        r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
        r"\s+(\d{1,2}),?\s+(20\d{2})\b",
        text,
        re.IGNORECASE,
    )
    if month_day_match:
        return _format_date(
            int(month_day_match.group(3)),
            _month_number(month_day_match.group(1)),
            int(month_day_match.group(2)),
        )

    return None


def _format_date(year: int, month: int, day: int) -> str | None:
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def _month_number(month: str) -> int:
    return {
        "jan": 1,
        "feb": 2,
        "mar": 3,
        "apr": 4,
        "may": 5,
        "jun": 6,
        "jul": 7,
        "aug": 8,
        "sep": 9,
        "sept": 9,
        "oct": 10,
        "nov": 11,
        "dec": 12,
    }[month[:4].lower().rstrip("t") if month.lower().startswith("sept") else month[:3].lower()]


def _load_playwright():
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", ".playwright-browsers")
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Playwright is not installed. Run: python -m pip install -e ."
        ) from exc

    return sync_playwright, PlaywrightTimeoutError


def _log(verbose: bool, message: str) -> None:
    if verbose:
        print(message, file=sys.stderr, flush=True)


_LINKS_SCRIPT = """
() => Array.from(document.querySelectorAll('a[href], source[src], video[src], audio[src], img[src], [data-src], [data-thumbnail-url]'))
  .flatMap((el) => [
    el.href,
    el.src,
    el.getAttribute && el.getAttribute('data-src'),
    el.getAttribute && el.getAttribute('data-thumbnail-url')
  ])
  .filter(Boolean)
"""

_SCRIPT_TEXT_SCRIPT = """
() => Array.from(document.querySelectorAll('script'))
  .map((el) => el.textContent || '')
  .filter(Boolean)
"""

_VIDEO_MENU_SELECTOR = """
[data-test-id="open-class-video-menu"]
"""
