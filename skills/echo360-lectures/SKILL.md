---
name: echo360_lectures
description: Use when the user asks OpenClaw to check, sync, download, transcribe, summarize, make flashcards for, or report on Echo360 university lecture recordings, including today's lectures and newly available lectures.
---

# Echo360 Lectures

Use the lecture downloader CLI. Do not manually scrape Echo360 in the agent.

## Command Pattern

Run commands against a lecture downloader workspace directory. Prefer `$LECTURE_DOWNLOADER_DIR` when set, otherwise use the current workspace if it contains `config.yaml`, otherwise use `/opt/lecture-downloader`.

Use `$LECTURE_DOWNLOADER_BIN` when set. Otherwise use `./.venv/bin/lecture-downloader` inside the project directory.

For a normal check across all courses:

```bash
PROJECT_DIR="${LECTURE_DOWNLOADER_DIR:-/opt/lecture-downloader}"
BIN="${LECTURE_DOWNLOADER_BIN:-$PROJECT_DIR/.venv/bin/lecture-downloader}"
"$BIN" --config "$PROJECT_DIR/config.yaml" sync --all-courses --verbose
```

For one course, only pass a course name already present in `config.yaml`:

```bash
PROJECT_DIR="${LECTURE_DOWNLOADER_DIR:-/opt/lecture-downloader}"
BIN="${LECTURE_DOWNLOADER_BIN:-$PROJECT_DIR/.venv/bin/lecture-downloader}"
"$BIN" --config "$PROJECT_DIR/config.yaml" sync --course chem114 --verbose
```

Relative `auth_state_path` and `lectures_dir` values in `config.yaml` resolve relative to `config.yaml`, so OpenClaw-visible files can stay inside the workspace even when `$LECTURE_DOWNLOADER_BIN` points to an install outside the workspace.

## Interpreting Output

The command writes progress logs to stderr and a final JSON summary to stdout. Use the JSON summary as the source of truth for:

- courses checked
- lecture IDs found
- downloaded IDs and downloaded audio paths
- skipped IDs and skipped audio paths
- transcribed IDs and transcript paths
- skipped transcript IDs and skipped transcript paths
- errors

If `ok` is false or `total_errors` is greater than zero, report the error clearly. If the error mentions `.auth/echo360-state.json` or another `.auth/*.json` path, tell the user to refresh the Echo360 login on their computer and copy the auth file to the LXC.

## Files

Lecture outputs live under:

```text
lectures/<COURSE>/<date>_<title>/
  audio.mp3
  transcript.md
  metadata.json
```

`audio.mp3` is deleted automatically once `transcript.md` exists. Future study outputs should be written beside the transcript:

```text
summary.md
flashcards.json
quiz.json
lecture-package.json
```

When the user asks to summarize today's lectures, first run `sync`. It downloads missing audio and creates missing `transcript.md` files with local Whisper. Then use existing `summary.md` files if present; if summaries are missing, summarize from `transcript.md` and write `summary.md` beside the transcript when filesystem access allows it.
