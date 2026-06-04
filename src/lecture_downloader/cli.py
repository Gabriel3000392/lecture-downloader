from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from lecture_downloader.browser import find_ids, find_lectures, save_login_session
from lecture_downloader.config import DEFAULT_CONFIG_PATH, load_course_config, load_course_configs
from lecture_downloader.download import download_audio_files
from lecture_downloader.study import generate_study_packages
from lecture_downloader.sync import sync_courses
from lecture_downloader.transcribe import transcribe_course


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="lecture-downloader",
        description="Find Echo360 lecture/media IDs from a logged-in section page.",
    )
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help="Path to config.yaml.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)
    setup_parser = subparsers.add_parser(
        "setup-login",
        help="Open Echo360 in a browser and save the authenticated session.",
    )
    setup_parser.add_argument(
        "--course",
        default=None,
        help="Course name from config.yaml, such as engr101 or emth117.",
    )

    find_parser = subparsers.add_parser(
        "find-ids",
        help="Open the configured Echo360 section page and print lecture/media IDs.",
    )
    find_parser.add_argument(
        "--headed",
        action="store_true",
        help="Show the browser while finding IDs.",
    )
    find_parser.add_argument(
        "--max-menus",
        type=int,
        default=None,
        help="Only open this many video menus. Useful for debugging.",
    )
    find_parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print progress while loading the page and opening video menus.",
    )
    find_parser.add_argument(
        "--all-courses",
        action="store_true",
        help="Find IDs for every configured course.",
    )
    find_parser.add_argument(
        "--course",
        default=None,
        help="Course name from config.yaml, such as engr101 or emth117.",
    )

    download_parser = subparsers.add_parser(
        "download-audio",
        help="Download MP3 audio for given IDs, or scrape the page first if no IDs are passed.",
    )
    download_parser.add_argument(
        "media_ids",
        nargs="*",
        help="Lecture/media IDs to download. If omitted, IDs are scraped from the section page.",
    )
    download_parser.add_argument(
        "--headed",
        action="store_true",
        help="Show the browser while scraping IDs before downloading.",
    )
    download_parser.add_argument(
        "--max-menus",
        type=int,
        default=None,
        help="Only open this many video menus when scraping IDs.",
    )
    download_parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download audio even if the MP3 already exists.",
    )
    download_parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print progress while scraping and downloading.",
    )
    download_parser.add_argument(
        "--all-courses",
        action="store_true",
        help="Scrape and download audio for every configured course.",
    )
    download_parser.add_argument(
        "--course",
        default=None,
        help="Course name from config.yaml, such as engr101 or emth117.",
    )

    sync_parser = subparsers.add_parser(
        "sync",
        help="Scrape courses, download missing audio, transcribe missing transcripts, and print a JSON run summary.",
    )
    sync_parser.add_argument(
        "--headed",
        action="store_true",
        help="Show the browser while scraping IDs.",
    )
    sync_parser.add_argument(
        "--max-menus",
        type=int,
        default=None,
        help="Only open this many video menus when scraping IDs.",
    )
    sync_parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download audio even if audio.mp3 already exists.",
    )
    sync_parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print progress while scraping, downloading, and transcribing.",
    )
    sync_parser.add_argument(
        "--all-courses",
        action="store_true",
        help="Sync every configured course.",
    )
    sync_parser.add_argument(
        "--course",
        default=None,
        help="Course name from config.yaml, such as engr101 or emth117.",
    )

    transcribe_parser = subparsers.add_parser(
        "transcribe",
        help="Transcribe local lecture audio files into transcript.md files.",
    )
    transcribe_parser.add_argument(
        "--force",
        action="store_true",
        help="Re-transcribe even if transcript.md already exists.",
    )
    transcribe_parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print progress while transcribing.",
    )
    transcribe_parser.add_argument(
        "--all-courses",
        action="store_true",
        help="Transcribe every configured course.",
    )
    transcribe_parser.add_argument(
        "--course",
        default=None,
        help="Course name from config.yaml, such as engr101 or emth117.",
    )

    study_parser = subparsers.add_parser(
        "generate-study",
        help="Generate local lecture-package.json, summary.md, flashcards.json, and quiz.json from transcript.md files.",
    )
    study_parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate even if lecture-package.json already exists.",
    )
    study_parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print progress while generating study packages.",
    )
    study_parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only process this many transcript folders per selected course.",
    )
    study_parser.add_argument(
        "--match",
        default=None,
        help="Only process transcript folders whose path or metadata contains this text.",
    )
    study_parser.add_argument(
        "--provider",
        choices=("local", "openai"),
        default="local",
        help="Study generation provider. local is deterministic; openai sends transcripts to the OpenAI API.",
    )
    study_parser.add_argument(
        "--model",
        default=None,
        help="Model to use with --provider openai. Defaults to OPENAI_MODEL or the downloader default.",
    )
    study_parser.add_argument(
        "--fallback-local",
        action="store_true",
        help="Fall back to the deterministic local generator if OpenAI generation fails validation.",
    )
    study_parser.add_argument(
        "--all-courses",
        action="store_true",
        help="Generate study packages for every configured course.",
    )
    study_parser.add_argument(
        "--course",
        default=None,
        help="Course name from config.yaml, such as engr101 or emth117.",
    )

    args = parser.parse_args(argv)
    try:
        if args.command == "setup-login":
            config = load_course_config(Path(args.config), args.course)
            save_login_session(config)
            return 0

        if args.command == "find-ids":
            configs = _selected_configs(Path(args.config), args.course, args.all_courses)
            found_any = False
            for config in configs:
                ids = find_ids(
                    config,
                    headed=args.headed,
                    max_menus=args.max_menus,
                    verbose=args.verbose,
                )
                if len(configs) > 1:
                    print(f"[{config.course_name}]")
                for media_id in ids:
                    print(media_id)
                found_any = found_any or bool(ids)

            if not found_any:
                print("No lecture/media IDs found.")
                return 1
            return 0

        if args.command == "download-audio":
            configs = _selected_configs(Path(args.config), args.course, args.all_courses)
            if args.media_ids and len(configs) > 1:
                raise ValueError("Pass --course when downloading explicit media IDs.")

            for config in configs:
                media_inputs = list(args.media_ids)
                if not media_inputs:
                    media_inputs = find_lectures(
                        config,
                        headed=args.headed,
                        max_menus=args.max_menus,
                        verbose=args.verbose,
                    )
                    if not media_inputs:
                        print(f"No lecture/media IDs found for {config.course_name}.")
                        continue

                results = download_audio_files(
                    config,
                    media_inputs,
                    force=args.force,
                    verbose=args.verbose,
                )
                for result in results:
                    print(f"{config.course_name}: {result.status}: {result.path}")
            return 0

        if args.command == "sync":
            configs = _selected_configs(Path(args.config), args.course, args.all_courses)
            summary = sync_courses(
                configs,
                headed=args.headed,
                max_menus=args.max_menus,
                force=args.force,
                verbose=args.verbose,
            )
            print(json.dumps(summary.to_dict(), indent=2, sort_keys=True))
            return 0 if summary.ok else 1

        if args.command == "transcribe":
            configs = _selected_configs(Path(args.config), args.course, args.all_courses)
            summary: dict[str, object] = {
                "ok": True,
                "courses_checked": [config.course_name for config in configs],
                "courses": [],
                "total_transcribed": 0,
                "total_skipped": 0,
                "total_errors": 0,
            }
            for config in configs:
                course_summary: dict[str, object] = {
                    "course": config.course_name,
                    "transcribed": [],
                    "skipped": [],
                    "transcript_paths": [],
                    "skipped_paths": [],
                    "errors": [],
                }
                try:
                    results = transcribe_course(
                        config,
                        force=args.force,
                        verbose=args.verbose,
                    )
                    for result in results:
                        if result.status == "transcribed":
                            course_summary["transcribed"].append(result.media_id)
                            course_summary["transcript_paths"].append(str(result.path))
                            summary["total_transcribed"] += 1
                        elif result.status == "skipped":
                            course_summary["skipped"].append(result.media_id)
                            course_summary["skipped_paths"].append(str(result.path))
                            summary["total_skipped"] += 1
                except Exception as exc:
                    summary["ok"] = False
                    summary["total_errors"] += 1
                    course_summary["errors"].append(str(exc))
                summary["courses"].append(course_summary)

            print(json.dumps(summary, indent=2, sort_keys=True))
            return 0 if summary["ok"] else 1

        if args.command == "generate-study":
            configs = _selected_configs(Path(args.config), args.course, args.all_courses)
            summary: dict[str, object] = {
                "ok": True,
                "courses_checked": [config.course_name for config in configs],
                "courses": [],
                "total_generated": 0,
                "total_skipped": 0,
                "total_errors": 0,
            }
            for config in configs:
                course_summary: dict[str, object] = {
                    "course": config.course_name,
                    "generated": [],
                    "skipped": [],
                    "package_paths": [],
                    "skipped_paths": [],
                    "errors": [],
                }
                results = generate_study_packages(
                    config,
                    force=args.force,
                    verbose=args.verbose,
                    limit=args.limit,
                    match=args.match,
                    provider=args.provider,
                    model=args.model,
                    fallback_local=args.fallback_local,
                )
                for result in results:
                    if result.status == "generated":
                        course_summary["generated"].append(result.media_id)
                        course_summary["package_paths"].append(str(result.path))
                        summary["total_generated"] += 1
                    elif result.status == "skipped":
                        course_summary["skipped"].append(result.media_id)
                        course_summary["skipped_paths"].append(str(result.path))
                        summary["total_skipped"] += 1
                    elif result.status == "error":
                        summary["ok"] = False
                        summary["total_errors"] += 1
                        course_summary["errors"].append(
                            f"{result.path}: {result.error or 'unknown error'}"
                        )
                summary["courses"].append(course_summary)

            print(json.dumps(summary, indent=2, sort_keys=True))
            return 0 if summary["ok"] else 1
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    parser.error(f"Unknown command: {args.command}")
    return 2


def _selected_configs(config_path: Path, course_name: str | None, all_courses: bool):
    if all_courses:
        if course_name is not None:
            raise ValueError("Use either --course or --all-courses, not both.")
        return load_course_configs(config_path)

    return [load_course_config(config_path, course_name)]


if __name__ == "__main__":
    raise SystemExit(main())
