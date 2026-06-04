from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_CONFIG_PATH = Path("config.yaml")


@dataclass(frozen=True)
class AppConfig:
    section_id: str
    course_name: str = "default"
    base_url: str = "https://echo360.net.au"
    auth_state_path: Path = Path(".auth/echo360-state.json")
    lectures_dir: Path = Path("lectures")
    headless: bool = True
    whisper_model: str = "small"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    transcribe_on_sync: bool = True

    @property
    def section_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/section/{self.section_id}/home"

    def audio_download_url(self, media_id: str) -> str:
        return f"{self.base_url.rstrip('/')}/media/download/{media_id}/audio.mp3"


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> AppConfig:
    return load_course_config(path)


def load_course_config(
    path: Path = DEFAULT_CONFIG_PATH,
    course_name: str | None = None,
) -> AppConfig:
    configs = load_course_configs(path)

    if course_name is None:
        if len(configs) == 1:
            return configs[0]
        names = ", ".join(config.course_name for config in configs)
        raise ValueError(f"Multiple courses configured. Choose one with --course. Available: {names}")

    for config in configs:
        if config.course_name == course_name:
            return config

    names = ", ".join(config.course_name for config in configs)
    raise ValueError(f"Unknown course '{course_name}'. Available: {names}")


def load_course_configs(path: Path = DEFAULT_CONFIG_PATH) -> list[AppConfig]:
    if not path.exists():
        raise FileNotFoundError(
            f"Missing config file: {path}. Create one with a courses block first."
        )

    config_dir = path.resolve().parent
    raw = _load_flat_yaml(path)

    base_url = str(raw.get("base_url", AppConfig.base_url)).strip()
    default_auth_state_path = _resolve_config_path(
        config_dir,
        raw.get("auth_state_path", AppConfig.auth_state_path),
    )
    auth_state_paths = _read_auth_state_paths(raw)
    lectures_root = _resolve_config_path(
        config_dir,
        raw.get("lectures_dir", raw.get("audio_dir", AppConfig.lectures_dir)),
    )
    headless = bool(raw.get("headless", AppConfig.headless))
    whisper_model = str(raw.get("whisper_model", AppConfig.whisper_model)).strip()
    whisper_device = str(raw.get("whisper_device", AppConfig.whisper_device)).strip()
    whisper_compute_type = str(
        raw.get("whisper_compute_type", AppConfig.whisper_compute_type)
    ).strip()
    transcribe_on_sync = bool(raw.get("transcribe_on_sync", AppConfig.transcribe_on_sync))
    courses = _read_courses(raw)

    return [
        AppConfig(
            section_id=section_id,
            course_name=course_name,
            base_url=base_url,
            auth_state_path=_resolve_config_path(
                config_dir,
                auth_state_paths.get(course_name, default_auth_state_path),
            ),
            lectures_dir=lectures_root / course_name.upper(),
            headless=headless,
            whisper_model=whisper_model,
            whisper_device=whisper_device,
            whisper_compute_type=whisper_compute_type,
            transcribe_on_sync=transcribe_on_sync,
        )
        for course_name, section_id in courses.items()
    ]


def _required_str(raw: dict[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Config value '{key}' is required and must be a string.")
    return value.strip()


def _load_flat_yaml(path: Path) -> dict[str, Any]:
    raw: dict[str, Any] = {}
    current_mapping: str | None = None

    with path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            line_without_comment = line.split("#", 1)[0].rstrip()
            clean = line_without_comment.strip()
            if not clean:
                continue
            if ":" not in clean:
                raise ValueError(
                    f"Invalid config line {line_number} in {path}: expected 'key: value'."
                )

            is_nested = line_without_comment[:1].isspace()
            key, value = clean.split(":", 1)
            key = key.strip()
            value = value.strip().strip("'\"")
            if not key:
                raise ValueError(f"Invalid config line {line_number} in {path}: empty key.")

            if is_nested:
                if current_mapping is None:
                    raise ValueError(
                        f"Invalid config line {line_number} in {path}: nested value without a parent."
                    )
                mapping = raw.setdefault(current_mapping, {})
                if not isinstance(mapping, dict):
                    raise ValueError(
                        f"Invalid config line {line_number} in {path}: parent is not a mapping."
                    )
                mapping[key] = _parse_scalar(value)
                continue

            current_mapping = key if value == "" else None
            raw[key] = {} if value == "" else _parse_scalar(value)

    return raw


def _parse_scalar(value: str) -> Any:
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    return value


def _read_courses(raw: dict[str, Any]) -> dict[str, str]:
    courses = raw.get("courses")
    if isinstance(courses, dict) and courses:
        parsed: dict[str, str] = {}
        for name, section_id in courses.items():
            if not isinstance(name, str) or not name.strip():
                raise ValueError("Course names in config must be non-empty strings.")
            if not isinstance(section_id, str) or not section_id.strip():
                raise ValueError(f"Course '{name}' must have a section ID.")
            parsed[name.strip()] = section_id.strip()
        return parsed

    section_id = raw.get("section_id")
    if isinstance(section_id, str) and section_id.strip():
        return {"default": section_id.strip()}

    raise ValueError("Config must contain either 'courses:' or 'section_id:'.")


def _read_auth_state_paths(raw: dict[str, Any]) -> dict[str, str]:
    paths = raw.get("auth_state_paths")
    if paths is None:
        return {}
    if not isinstance(paths, dict):
        raise ValueError("Config value 'auth_state_paths' must be a mapping.")

    parsed: dict[str, str] = {}
    for course_name, auth_state_path in paths.items():
        if not isinstance(course_name, str) or not course_name.strip():
            raise ValueError("Course names in auth_state_paths must be non-empty strings.")
        if not isinstance(auth_state_path, str) or not auth_state_path.strip():
            raise ValueError(f"Auth state path for course '{course_name}' must be non-empty.")
        parsed[course_name.strip()] = auth_state_path.strip()
    return parsed


def _resolve_config_path(config_dir: Path, value: object) -> Path:
    path = Path(str(value))
    if path.is_absolute():
        return path
    return config_dir / path
