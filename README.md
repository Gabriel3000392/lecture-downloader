# Echo360 Lecture Downloader

Local CLI for opening authenticated Echo360 course pages, finding lecture/media IDs, and downloading lecture audio into one folder per lecture.

The intended OpenClaw flow is:

```text
OpenClaw asks for today's lectures
  -> runs lecture-downloader sync
  -> new audio is downloaded
  -> missing transcript.md files are created locally with Whisper
  -> lecture-downloader generate-study creates local study packages from transcripts
  -> later steps can upload reviewed packages to the public notes app
```

## Output Layout

Downloaded lectures are stored like this:

```text
lectures/
  CHEM114/
    2026-05-13_CHEM114-26S1-LecC-Foundations-of-Chemistry/
      audio.mp3
      transcript.md
      metadata.json
```

After transcription completes, `audio.mp3` is deleted and the transcript remains:

```text
lectures/
  CHEM114/
    2026-05-13_kinetics/
      transcript.md
      summary.md
      flashcards.json
      quiz.json
      lecture-package.json
      metadata.json
```

Existing `audio.mp3` files are skipped unless you pass `--force`.
Existing `transcript.md` files are also skipped unless you pass `--force`.
When a transcript exists, any leftover `audio.mp3` is deleted during the next transcription pass.

## Config

Courses are configured in `config.yaml`:

```yaml
courses:
  emth117: b1629672-6a5f-4824-abb7-b33fdf7e0e9c
  engr101: 9401f826-71d4-4c89-a842-a53fdd126d4a
  chem114: 80588a39-c705-44cc-972e-e0ab4b6997b3
base_url: https://echo360.net.au
auth_state_path: .auth/echo360-state.json
lectures_dir: lectures
headless: true
whisper_model: small
whisper_device: cpu
whisper_compute_type: int8
transcribe_on_sync: true
```

Course names can stay lowercase for commands, but folders are written uppercase, such as `lectures/CHEM114`.

If one course needs a different Echo360 login, keep the default login and add a per-course auth path:

```yaml
auth_state_path: .auth/echo360-state.json
auth_state_paths:
  emth118: .auth/echo360-emth118-state.json
```

Relative paths in `config.yaml` are resolved relative to the config file itself. This is important for OpenClaw: if `config.yaml` is inside OpenClaw's workspace, then `.auth/` and `lectures/` will also stay inside that workspace.

## Windows Setup

From `C:\Projects\lecture-downloader`:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
$env:PLAYWRIGHT_BROWSERS_PATH = ".playwright-browsers"
.\.venv\Scripts\python.exe -m playwright install chromium
```

If PowerShell blocks venv activation, you can ignore activation and run the `.exe` commands directly.

## Login On Your Computer

Echo360 uses Microsoft login, so do the browser login on your computer:

```powershell
.\.venv\Scripts\lecture-downloader.exe setup-login --course chem114
```

A browser opens. Log in normally, wait until the Echo360 course page is visible, then return to the terminal and press Enter.

This creates:

```text
.auth/echo360-state.json
```

Treat this file like a password. It contains your logged-in browser session.

## Local Smoke Tests

Find IDs for one course:

```powershell
.\.venv\Scripts\lecture-downloader.exe find-ids --course chem114 --headed --verbose --max-menus 5
```

Download/sync one course:

```powershell
.\.venv\Scripts\lecture-downloader.exe sync --course chem114 --verbose --max-menus 5
```

Sync every configured course:

```powershell
.\.venv\Scripts\lecture-downloader.exe sync --all-courses --verbose
```

`sync` prints progress logs and then a final JSON summary. OpenClaw should read the JSON summary as the source of truth.
The first transcription run may take longer because `faster-whisper` downloads the local Whisper model.

Generate local study packages from existing transcripts:

```powershell
.\.venv\Scripts\lecture-downloader.exe generate-study --course chem114 --verbose
```

`generate-study` writes `lecture-package.json`, `summary.md`, `flashcards.json`, and `quiz.json`
beside each lecture. By default it uses a deterministic local generator so the pipeline can
be tested without public upload or API keys.

Generate AI-drafted notes, flashcards, quizzes, tags, and an exam checklist with OpenAI:

```powershell
$env:OPENAI_API_KEY = "..."
.\.venv\Scripts\lecture-downloader.exe generate-study --course chem114 --provider openai --model gpt-5.2 --verbose
```

Use `--fallback-local` if you want the command to write the deterministic package when the
AI provider fails or returns invalid JSON. The OpenAI provider sends the transcript text to
the API, so only use it for lectures you are comfortable processing externally. All outputs
remain local drafts until a separate upload/import step publishes them.

## OpenClaw Workspace Layout

If OpenClaw cannot access files outside its workspace, use one of these layouts.

### Recommended: App And Data Inside The Workspace

Put the whole project inside an OpenClaw-visible workspace, for example:

```text
/opt/openclaw/workspace/lecture-downloader/
  config.yaml
  .auth/echo360-state.json
  lectures/
  src/
  skills/
  .venv/
```

Then OpenClaw can run:

```bash
cd /opt/openclaw/workspace/lecture-downloader
./.venv/bin/lecture-downloader --config config.yaml sync --all-courses --verbose
```

This is the simplest option because the app, config, auth file, and lecture files all live inside the workspace.

### Alternative: App Elsewhere, Files Inside The Workspace

If you want the app installed in `/opt/lecture-downloader` but lecture files inside OpenClaw's workspace, put a workspace-owned config somewhere like:

```text
/opt/openclaw/workspace/lecture-downloader-data/
  config.yaml
  .auth/echo360-state.json
  lectures/
```

The config can keep relative paths:

```yaml
auth_state_path: .auth/echo360-state.json
lectures_dir: lectures
```

Run the app with the workspace config:

```bash
/opt/lecture-downloader/.venv/bin/lecture-downloader \
  --config /opt/openclaw/workspace/lecture-downloader-data/config.yaml \
  sync --all-courses --verbose
```

Because paths are resolved relative to `config.yaml`, outputs go to:

```text
/opt/openclaw/workspace/lecture-downloader-data/lectures/
```

If OpenClaw cannot execute binaries outside the workspace either, use the recommended layout and keep the whole app inside the workspace.

## Copy Project To The LXC

Recommended destination on the LXC:

```text
/opt/lecture-downloader
```

If OpenClaw is restricted to a specific workspace directory, replace `/opt/lecture-downloader` below with that workspace path, such as `/opt/openclaw/workspace/lecture-downloader`.

### Option A: Copy With `scp`

From PowerShell on your computer, create an archive without the virtual environment or browser cache:

```powershell
Compress-Archive -Path pyproject.toml,config.yaml,src,tests,skills,README.md -DestinationPath lecture-downloader.zip -Force
scp .\lecture-downloader.zip USER@LXC_HOST:/tmp/lecture-downloader.zip
scp .\.auth\echo360-state.json USER@LXC_HOST:/tmp/echo360-state.json
```

On the LXC:

```bash
sudo mkdir -p /opt/lecture-downloader
sudo chown "$USER:$USER" /opt/lecture-downloader
cd /opt/lecture-downloader
unzip /tmp/lecture-downloader.zip
mkdir -p .auth
mv /tmp/echo360-state.json .auth/echo360-state.json
chmod 600 .auth/echo360-state.json
```

### Option B: Copy With `rsync`

If you have `rsync` available:

```bash
rsync -av \
  --exclude .venv \
  --exclude .playwright-browsers \
  --exclude __pycache__ \
  --exclude .pytest_cache \
  --exclude audio \
  --exclude lectures \
  ./ USER@LXC_HOST:/opt/lecture-downloader/
```

Then copy the auth file:

```bash
scp .auth/echo360-state.json USER@LXC_HOST:/opt/lecture-downloader/.auth/echo360-state.json
```

## Install On The LXC

These commands assume a Debian/Ubuntu-style LXC.

```bash
cd /opt/lecture-downloader
sudo apt update
sudo apt install -y python3 python3-venv python3-pip unzip
python3 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install -e ".[dev]"
./.venv/bin/python -m playwright install --with-deps chromium
```

If `playwright install --with-deps chromium` cannot install system packages in your LXC, install Chromium dependencies with your package manager, then run:

```bash
./.venv/bin/python -m playwright install chromium
```

## Test On The LXC

Check that the CLI works:

```bash
cd /opt/lecture-downloader
./.venv/bin/lecture-downloader sync --course chem114 --verbose --max-menus 2
```

Expected behavior:

- progress logs appear while it opens Echo360 and checks menus
- a final JSON object prints at the end
- `ok` is `true` when the run succeeds
- missing `transcript.md` files are created with local Whisper
- `audio.mp3` is deleted once its lecture has a completed transcript

If you see an error about `.auth/echo360-state.json`, refresh login on your computer and copy the new auth file to the LXC.

## OpenClaw Skill Setup

This repo includes a workspace skill:

```text
skills/echo360-lectures/SKILL.md
```

If OpenClaw uses `/opt/lecture-downloader` as its workspace, it should discover the skill from there.

If OpenClaw uses a different workspace, copy the skill into OpenClaw's shared skills folder:

```bash
mkdir -p ~/.openclaw/skills
cp -r /opt/lecture-downloader/skills/echo360-lectures ~/.openclaw/skills/
```

Set this environment variable for OpenClaw if the lecture workspace is not `/opt/lecture-downloader`:

```bash
export LECTURE_DOWNLOADER_DIR=/opt/openclaw/workspace/lecture-downloader
```

If the app binary is installed separately from the workspace config/data, also set:

```bash
export LECTURE_DOWNLOADER_BIN=/opt/lecture-downloader/.venv/bin/lecture-downloader
```

Restart OpenClaw or start a new session so it reloads skills.

The skill instructs OpenClaw to run:

```bash
PROJECT_DIR="${LECTURE_DOWNLOADER_DIR:-/opt/lecture-downloader}"
BIN="${LECTURE_DOWNLOADER_BIN:-$PROJECT_DIR/.venv/bin/lecture-downloader}"
"$BIN" --config "$PROJECT_DIR/config.yaml" sync --all-courses --verbose
```

## Useful Commands

Find lecture IDs:

```bash
./.venv/bin/lecture-downloader find-ids --course chem114 --verbose
```

Download/sync one course:

```bash
./.venv/bin/lecture-downloader sync --course chem114 --verbose
```

Download/sync all courses:

```bash
./.venv/bin/lecture-downloader sync --all-courses --verbose
```

Force re-download:

```bash
./.venv/bin/lecture-downloader sync --course chem114 --force --verbose
```

Transcribe local audio without scraping Echo360:

```bash
./.venv/bin/lecture-downloader transcribe --course chem114 --verbose
```

Transcribe all configured courses:

```bash
./.venv/bin/lecture-downloader transcribe --all-courses --verbose
```

## Run Tests

Windows:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

LXC:

```bash
./.venv/bin/python -m pytest
```
