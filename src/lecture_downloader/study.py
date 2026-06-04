from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any, Callable

from lecture_downloader.config import AppConfig

DEFAULT_OPENAI_MODEL = "gpt-5.2"
StudyProvider = str
LLMClient = Callable[[str, str], str]


@dataclass(frozen=True)
class StudyGenerationResult:
    media_id: str | None
    path: Path
    status: str
    error: str | None = None


def generate_study_packages(
    config: AppConfig,
    *,
    force: bool = False,
    verbose: bool = False,
    limit: int | None = None,
    match: str | None = None,
    provider: StudyProvider = "local",
    model: str | None = None,
    fallback_local: bool = False,
) -> list[StudyGenerationResult]:
    lecture_dirs = find_lecture_dirs_with_transcripts(config)
    if match:
        needle = match.lower()
        lecture_dirs = [
            lecture_dir
            for lecture_dir in lecture_dirs
            if needle in lecture_dir.name.lower()
            or needle in json.dumps(_read_metadata(lecture_dir), sort_keys=True).lower()
        ]
    if limit is not None:
        lecture_dirs = lecture_dirs[:limit]

    results: list[StudyGenerationResult] = []
    for index, lecture_dir in enumerate(lecture_dirs, start=1):
        package_path = lecture_dir / "lecture-package.json"
        metadata = _read_metadata(lecture_dir)
        media_id = _optional_str(metadata.get("media_id"))

        if package_path.exists() and not force:
            _log(verbose, f"[{index}/{len(lecture_dirs)}] Skipping existing {package_path}")
            results.append(StudyGenerationResult(media_id, package_path, "skipped"))
            continue

        try:
            _log(verbose, f"[{index}/{len(lecture_dirs)}] Generating study package {package_path}")
            package = build_lecture_package(
                config,
                lecture_dir,
                metadata,
                provider=provider,
                model=model,
                fallback_local=fallback_local,
            )
            _write_json_atomically(package_path, package)
            _write_sidecar_outputs(lecture_dir, package)
            _write_generation_metadata(lecture_dir, metadata, package)
            results.append(StudyGenerationResult(media_id, package_path, "generated"))
        except Exception as exc:
            results.append(
                StudyGenerationResult(media_id, package_path, "error", error=str(exc))
            )

    return results


def find_lecture_dirs_with_transcripts(config: AppConfig) -> list[Path]:
    if not config.lectures_dir.exists():
        return []

    return [
        child
        for child in sorted(config.lectures_dir.iterdir())
        if child.is_dir() and (child / "transcript.md").exists()
    ]


def build_lecture_package(
    config: AppConfig,
    lecture_dir: Path,
    metadata: dict[str, Any] | None = None,
    *,
    provider: StudyProvider = "local",
    model: str | None = None,
    fallback_local: bool = False,
    llm_client: LLMClient | None = None,
) -> dict[str, Any]:
    metadata = metadata or _read_metadata(lecture_dir)
    transcript = (lecture_dir / "transcript.md").read_text(encoding="utf-8")
    transcript_text = _transcript_body_text(transcript)
    if len(transcript_text.split()) < 80:
        raise ValueError("Transcript is too short for reliable study package generation.")

    title = _optional_str(metadata.get("title")) or _title_from_transcript(transcript) or lecture_dir.name
    date = _optional_str(metadata.get("date")) or _date_from_folder(lecture_dir.name)
    slug = _slugify(f"{date or 'undated'}-{title}")

    if provider == "openai":
        try:
            package = _build_openai_lecture_package(
                config,
                lecture_dir,
                metadata,
                transcript_text,
                title,
                date,
                slug,
                model=model,
                llm_client=llm_client,
            )
            errors = validate_lecture_package(package)
            if errors:
                raise ValueError("; ".join(errors))
            return package
        except Exception:
            if not fallback_local:
                raise

    if provider != "local" and provider != "openai":
        raise ValueError(f"Unsupported study package provider: {provider}")

    return _build_local_lecture_package(
        config,
        lecture_dir,
        metadata,
        transcript_text,
        title,
        date,
        slug,
    )


def _build_local_lecture_package(
    config: AppConfig,
    lecture_dir: Path,
    metadata: dict[str, Any],
    transcript_text: str,
    title: str,
    date: str | None,
    slug: str,
) -> dict[str, Any]:
    key_sentences = _key_sentences(transcript_text)
    learning_points = key_sentences[:8]

    content_html = _render_notes_html(title, transcript_text, learning_points)
    flashcards = _build_flashcards(learning_points)
    quizzes = _build_quizzes(title, learning_points)
    tags = _build_tags(config, title, transcript_text)
    study_guides = [_build_study_guide(title, learning_points)]

    return {
        "source": {
            "system": "echo360",
            "id": _optional_str(metadata.get("media_id")) or lecture_dir.name,
            "downloadedAt": _optional_str(metadata.get("downloaded_at")),
        },
        "promptVersion": "local-extractive-v1",
        "course": {
            "code": config.course_name.upper(),
            "title": _course_title(config.course_name),
            "term": _optional_str(metadata.get("term")) or "Unknown term",
        },
        "lecture": {
            "slug": slug,
            "title": title,
            "date": date,
            "subtitle": f"AI-drafted study package generated locally from the transcript for {title}.",
        },
        "notes": {
            "contentHtml": content_html,
            "contentMarkdown": _render_notes_markdown(title, learning_points),
        },
        "studyAssets": {
            "tags": tags,
            "flashcards": flashcards,
            "quizzes": quizzes,
            "studyGuides": study_guides,
        },
    }


def _build_openai_lecture_package(
    config: AppConfig,
    lecture_dir: Path,
    metadata: dict[str, Any],
    transcript_text: str,
    title: str,
    date: str | None,
    slug: str,
    *,
    model: str | None = None,
    llm_client: LLMClient | None = None,
) -> dict[str, Any]:
    model_name = model or os.environ.get("OPENAI_MODEL") or DEFAULT_OPENAI_MODEL
    prompt = _build_study_prompt(config, metadata, transcript_text, title, date, slug)
    raw_output = (llm_client or _call_openai_responses_api)(prompt, model_name)
    package = _parse_json_object(raw_output)
    return _normalize_ai_package(config, lecture_dir, metadata, package, title, date, slug)


def _build_study_prompt(
    config: AppConfig,
    metadata: dict[str, Any],
    transcript_text: str,
    title: str,
    date: str | None,
    slug: str,
) -> str:
    payload = {
        "course": {
            "code": config.course_name.upper(),
            "title": _course_title(config.course_name),
            "term": _optional_str(metadata.get("term")) or "Unknown term",
        },
        "lecture": {
            "slug": slug,
            "title": title,
            "date": date,
            "sourceId": _optional_str(metadata.get("media_id")) or slug,
        },
        "transcript": transcript_text,
    }
    return (
        "Create a draft lecture study package from this Echo360 transcript.\n"
        "Return only valid JSON. Do not wrap it in Markdown.\n\n"
        "Rules:\n"
        "- Treat the transcript as the only source of truth.\n"
        "- Ignore greetings, microphone checks, schedule/admin chatter, and jokes unless they explain course content.\n"
        "- Correct obvious transcription errors only when context makes the correction clear.\n"
        "- Notes should be useful study notes, not a transcript summary.\n"
        "- Prefer lecture-specific topic headings over generic course titles.\n"
        "- Preserve named examples, equations, units, formulas, naming patterns, and definitions when present.\n"
        "- Include worked-example steps and common mistakes when the lecture demonstrates calculations, drawing, or naming.\n"
        "- Flashcards should test concepts, definitions, methods, and common mistakes.\n"
        "- Quiz questions should mix recall, application, and mistake-spotting; multiple-choice distractors should be plausible.\n"
        "- Quiz questions need explanations and a clear correct answer.\n"
        "- Do not prefix titles, flashcards, or quiz prompts with 'DRAFT'. Draft status is handled by the app.\n\n"
        "JSON shape:\n"
        "{\n"
        '  "notes": {"contentHtml": "...", "contentMarkdown": "..."},\n'
        '  "studyAssets": {\n'
        '    "tags": ["tag"],\n'
        '    "flashcards": [{"front": "...", "back": "...", "difficultySeed": "intro|core|exam"}],\n'
        '    "quizzes": [{"title": "...", "questions": [{"type": "multiple_choice|short_answer", "prompt": "...", "options": [], "correctAnswer": "...", "explanation": "..."}]}],\n'
        '    "studyGuides": [{"title": "...", "content": "..."}]\n'
        "  }\n"
        "}\n\n"
        "Target counts: 10-16 flashcards, 8-12 quiz questions, 6-10 tags, 1 exam checklist.\n\n"
        f"Lecture payload:\n{json.dumps(payload, ensure_ascii=False)}"
    )


def _call_openai_responses_api(prompt: str, model: str) -> str:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required for --provider openai.")

    request_body = {
        "model": model,
        "input": [
            {
                "role": "system",
                "content": (
                    "You are a careful study-material drafting agent. "
                    "You create structured draft notes, flashcards, quizzes, tags, and study guides."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "lecture_study_package",
                "schema": _study_package_response_schema(),
                "strict": False,
            }
        },
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(request_body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            response_data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI generation failed: HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"OpenAI generation failed: {exc}") from exc

    output_text = _extract_openai_output_text(response_data)
    if not output_text:
        raise RuntimeError("OpenAI generation returned no output text.")
    return output_text


def _study_package_response_schema() -> dict[str, Any]:
    question_schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["type", "prompt", "options", "correctAnswer", "explanation"],
        "properties": {
            "type": {"type": "string"},
            "prompt": {"type": "string"},
            "options": {"type": "array", "items": {"type": "string"}},
            "correctAnswer": {"type": "string"},
            "explanation": {"type": "string"},
        },
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["notes", "studyAssets"],
        "properties": {
            "notes": {
                "type": "object",
                "additionalProperties": False,
                "required": ["contentHtml", "contentMarkdown"],
                "properties": {
                    "contentHtml": {"type": "string"},
                    "contentMarkdown": {"type": "string"},
                },
            },
            "studyAssets": {
                "type": "object",
                "additionalProperties": False,
                "required": ["tags", "flashcards", "quizzes", "studyGuides"],
                "properties": {
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "flashcards": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["front", "back", "difficultySeed"],
                            "properties": {
                                "front": {"type": "string"},
                                "back": {"type": "string"},
                                "difficultySeed": {"type": "string"},
                            },
                        },
                    },
                    "quizzes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["title", "questions"],
                            "properties": {
                                "title": {"type": "string"},
                                "questions": {"type": "array", "items": question_schema},
                            },
                        },
                    },
                    "studyGuides": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["title", "content"],
                            "properties": {
                                "title": {"type": "string"},
                                "content": {"type": "string"},
                            },
                        },
                    },
                },
            },
        },
    }


def _extract_openai_output_text(response_data: dict[str, Any]) -> str | None:
    if isinstance(response_data.get("output_text"), str):
        return response_data["output_text"]

    chunks: list[str] = []
    for item in response_data.get("output", []):
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []):
            if isinstance(content, dict) and isinstance(content.get("text"), str):
                chunks.append(content["text"])
    return "\n".join(chunks).strip() or None


def _parse_json_object(raw_output: str) -> dict[str, Any]:
    try:
        value = json.loads(raw_output)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw_output, flags=re.DOTALL)
        if not match:
            raise
        value = json.loads(match.group(0))
    if not isinstance(value, dict):
        raise ValueError("AI generator did not return a JSON object.")
    return value


def _normalize_ai_package(
    config: AppConfig,
    lecture_dir: Path,
    metadata: dict[str, Any],
    package: dict[str, Any],
    title: str,
    date: str | None,
    slug: str,
) -> dict[str, Any]:
    notes = package.get("notes", {})
    assets = package.get("studyAssets", {})
    normalized_assets = _clean_study_assets(assets if isinstance(assets, dict) else {})
    return {
        "source": {
            "system": "echo360",
            "id": _optional_str(metadata.get("media_id")) or lecture_dir.name,
            "downloadedAt": _optional_str(metadata.get("downloaded_at")),
        },
        "promptVersion": "openai-study-v1",
        "course": {
            "code": config.course_name.upper(),
            "title": _course_title(config.course_name),
            "term": _optional_str(metadata.get("term")) or "Unknown term",
        },
        "lecture": {
            "slug": slug,
            "title": title,
            "date": date,
            "subtitle": f"AI-drafted study package generated from the transcript for {title}.",
        },
        "notes": notes if isinstance(notes, dict) else {},
        "studyAssets": normalized_assets,
    }


def _clean_study_assets(assets: dict[str, Any]) -> dict[str, Any]:
    flashcards = []
    for card in assets.get("flashcards", []):
        if not isinstance(card, dict):
            continue
        flashcards.append(
            {
                **card,
                "front": _strip_draft_prefix(str(card.get("front", ""))),
                "back": _strip_draft_prefix(str(card.get("back", ""))),
            }
        )

    quizzes = []
    for quiz in assets.get("quizzes", []):
        if not isinstance(quiz, dict):
            continue
        questions = []
        for question in quiz.get("questions", []):
            if not isinstance(question, dict):
                continue
            questions.append(
                {
                    **question,
                    "prompt": _strip_draft_prefix(str(question.get("prompt", ""))),
                    "correctAnswer": _strip_draft_prefix(str(question.get("correctAnswer", ""))),
                    "explanation": _strip_draft_prefix(str(question.get("explanation", ""))),
                }
            )
        quizzes.append(
            {
                **quiz,
                "title": _strip_draft_prefix(str(quiz.get("title", ""))),
                "questions": questions,
            }
        )

    study_guides = []
    for guide in assets.get("studyGuides", []):
        if not isinstance(guide, dict):
            continue
        study_guides.append(
            {
                **guide,
                "title": _strip_draft_prefix(str(guide.get("title", ""))),
                "content": str(guide.get("content", "")),
            }
        )

    return {
        "tags": [str(tag) for tag in assets.get("tags", []) if str(tag).strip()],
        "flashcards": flashcards,
        "quizzes": quizzes,
        "studyGuides": study_guides,
    }


def validate_lecture_package(package: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for key in ("source", "course", "lecture", "notes", "studyAssets"):
        if not isinstance(package.get(key), dict):
            errors.append(f"Missing object: {key}")

    if not _nested_str(package, "course", "code"):
        errors.append("Missing course.code")
    if not _nested_str(package, "lecture", "slug"):
        errors.append("Missing lecture.slug")
    if not _nested_str(package, "lecture", "title"):
        errors.append("Missing lecture.title")
    if not _nested_str(package, "notes", "contentHtml"):
        errors.append("Missing notes.contentHtml")

    assets = package.get("studyAssets")
    if isinstance(assets, dict):
        flashcards = assets.get("flashcards", [])
        if not isinstance(flashcards, list):
            errors.append("studyAssets.flashcards must be an array")
        else:
            for index, card in enumerate(flashcards):
                if not isinstance(card, dict) or not card.get("front") or not card.get("back"):
                    errors.append(f"Invalid flashcard at index {index}")

        quizzes = assets.get("quizzes", [])
        if not isinstance(quizzes, list):
            errors.append("studyAssets.quizzes must be an array")
        else:
            for quiz_index, quiz in enumerate(quizzes):
                if not isinstance(quiz, dict) or not quiz.get("title"):
                    errors.append(f"Invalid quiz at index {quiz_index}")
                    continue
                questions = quiz.get("questions", [])
                if not isinstance(questions, list) or not questions:
                    errors.append(f"Quiz {quiz_index} has no questions")

    return errors


def _transcript_body_text(transcript: str) -> str:
    body = transcript
    if transcript.startswith("---"):
        parts = transcript.split("---", 2)
        if len(parts) == 3:
            body = parts[2]
    body = re.sub(r"^\s*# .*$", " ", body, flags=re.MULTILINE)
    body = re.sub(
        r"\[\d{2}:\d{2}:\d{2}\.\d{3}\s+-->\s+\d{2}:\d{2}:\d{2}\.\d{3}\]",
        " ",
        body,
    )
    return re.sub(r"\s+", " ", body).strip()


def _key_sentences(text: str) -> list[str]:
    sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+", text)
        if len(sentence.split()) >= 8
    ]
    deduped: list[str] = []
    seen: set[str] = set()
    for sentence in sentences:
        key = sentence.lower()[:120]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(sentence)
    return deduped[:14] or [text[:320]]


def _render_notes_html(title: str, transcript_text: str, learning_points: list[str]) -> str:
    overview = learning_points[0] if learning_points else transcript_text[:260]
    point_items = "".join(f"<li>{escape(point)}</li>" for point in learning_points[:6])
    checklist_items = "".join(
        f"<li>Explain: {escape(_shorten(point, 120))}</li>"
        for point in learning_points[:5]
    )
    return (
        "<h2>Overview</h2>"
        f"<p>{escape(overview)}</p>"
        "<h2>Key Points</h2>"
        f"<ul>{point_items}</ul>"
        "<h2>Study Checklist</h2>"
        f"<ul>{checklist_items}</ul>"
        "<h2>Source Note</h2>"
        "<p>This package was generated locally from the transcript. Review before publishing.</p>"
    )


def _render_notes_markdown(title: str, learning_points: list[str]) -> str:
    lines = [f"# {title}", "", "## Key Points", ""]
    lines.extend(f"- {point}" for point in learning_points[:8])
    lines.extend(["", "## Study Checklist", ""])
    lines.extend(f"- Explain: {_shorten(point, 120)}" for point in learning_points[:5])
    lines.append("")
    return "\n".join(lines)


def _build_flashcards(learning_points: list[str]) -> list[dict[str, str]]:
    return [
        {
            "front": f"What is the main idea in key point {index + 1}?",
            "back": point,
            "difficultySeed": "intro" if index < 2 else "core" if index < 5 else "exam",
        }
        for index, point in enumerate(learning_points[:8])
    ]


def _build_quizzes(title: str, learning_points: list[str]) -> list[dict[str, Any]]:
    questions: list[dict[str, Any]] = []
    for index, point in enumerate(learning_points[:6]):
        if index % 2:
            questions.append(
                {
                    "type": "multiple_choice",
                    "prompt": f"Which statement best matches this part of {title}?",
                    "options": [
                        point,
                        "A related but unsupported statement not found in the generated notes.",
                        "A definition from a different topic.",
                        "A vague statement with no lecture-specific detail.",
                    ],
                    "correctAnswer": point,
                    "explanation": "The correct answer is the statement extracted from the lecture transcript.",
                }
            )
        else:
            questions.append(
                {
                    "type": "short_answer",
                    "prompt": f"Explain this idea from {title}: {_shorten(point, 140)}",
                    "options": [],
                    "correctAnswer": point,
                    "explanation": "A strong answer should include the same specific idea in your own words.",
                }
            )
    return [{"title": f"{title} revision quiz", "questions": questions}]


def _build_tags(config: AppConfig, title: str, transcript_text: str) -> list[str]:
    candidates = [config.course_name.upper(), *re.findall(r"\b[A-Z][A-Za-z0-9]{3,}\b", title)]
    common_terms = re.findall(r"\b[a-zA-Z][a-zA-Z-]{5,}\b", transcript_text.lower())
    stop = {
        "because",
        "lecture",
        "really",
        "actually",
        "should",
        "through",
        "things",
        "something",
        "different",
        "example",
    }
    for term in common_terms:
        if term not in stop:
            candidates.append(term)
    tags: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        tag = candidate.strip("- ").lower()
        if not tag or tag in seen:
            continue
        seen.add(tag)
        tags.append(tag)
        if len(tags) >= 8:
            break
    return tags


def _build_study_guide(title: str, learning_points: list[str]) -> dict[str, str]:
    content = "\n".join(
        ["Before moving on, make sure you can:", *[f"- {point}" for point in learning_points[:6]]]
    )
    return {"title": f"{title} exam checklist", "content": content}


def _write_sidecar_outputs(lecture_dir: Path, package: dict[str, Any]) -> None:
    _write_text_atomically(lecture_dir / "summary.md", package["notes"]["contentMarkdown"])
    _write_json_atomically(
        lecture_dir / "flashcards.json", package["studyAssets"]["flashcards"]
    )
    _write_json_atomically(lecture_dir / "quiz.json", package["studyAssets"]["quizzes"])


def _write_generation_metadata(
    lecture_dir: Path,
    metadata: dict[str, Any],
    package: dict[str, Any],
) -> None:
    metadata_path = lecture_dir / "metadata.json"
    updated = {
        **metadata,
        "summary_path": str(lecture_dir / "summary.md"),
        "flashcards_path": str(lecture_dir / "flashcards.json"),
        "quiz_path": str(lecture_dir / "quiz.json"),
        "lecture_package_path": str(lecture_dir / "lecture-package.json"),
        "study_generation_status": "generated",
        "study_generated_at": _utc_now(),
        "study_prompt_version": package.get("promptVersion", "unknown"),
        "updated_at": _utc_now(),
    }
    _write_json_atomically(metadata_path, updated)


def _write_json_atomically(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".part")
    temp_path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp_path, path)


def _write_text_atomically(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".part")
    temp_path.write_text(value, encoding="utf-8")
    os.replace(temp_path, path)


def _read_metadata(lecture_dir: Path) -> dict[str, Any]:
    metadata_path = lecture_dir / "metadata.json"
    if not metadata_path.exists():
        return {}
    try:
        return json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _title_from_transcript(transcript: str) -> str | None:
    match = re.search(r"^\s*#\s+(.+)$", transcript, flags=re.MULTILINE)
    return match.group(1).strip() if match else None


def _date_from_folder(name: str) -> str | None:
    match = re.match(r"^(\d{4}-\d{2}-\d{2})", name)
    return match.group(1) if match else None


def _course_title(course_name: str) -> str:
    titles = {
        "chem114": "Foundations of Chemistry",
        "emth117": "Foundations of Engineering Mathematics",
        "engr101": "Foundations of Engineering",
    }
    return titles.get(course_name.lower(), course_name.upper())


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return slug or "lecture"


def _shorten(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def _strip_draft_prefix(value: str) -> str:
    return re.sub(r"^\s*draft\s*:\s*", "", value, flags=re.IGNORECASE).strip()


def _nested_str(package: dict[str, Any], section: str, key: str) -> str | None:
    value = package.get(section)
    if not isinstance(value, dict):
        return None
    nested = value.get(key)
    return nested if isinstance(nested, str) and nested.strip() else None


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log(verbose: bool, message: str) -> None:
    if verbose:
        print(message, file=sys.stderr, flush=True)
