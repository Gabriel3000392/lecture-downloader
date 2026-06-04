from lecture_downloader.config import AppConfig, load_course_config, load_course_configs


def test_builds_audio_download_url() -> None:
    config = AppConfig(section_id="b1629672-6a5f-4824-abb7-b33fdf7e0e9c")

    assert (
        config.audio_download_url("0a2feded-d16e-4aa7-976c-27dd3044175d")
        == "https://echo360.net.au/media/download/0a2feded-d16e-4aa7-976c-27dd3044175d/audio.mp3"
    )


def test_loads_named_courses(tmp_path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
courses:
  engr101: b1629672-6a5f-4824-abb7-b33fdf7e0e9c
  emth117: 11111111-2222-3333-4444-555555555555
audio_dir: audio
""".strip(),
        encoding="utf-8",
    )

    courses = load_course_configs(config_path)
    emth117 = load_course_config(config_path, "emth117")

    assert [course.course_name for course in courses] == ["engr101", "emth117"]
    assert emth117.section_id == "11111111-2222-3333-4444-555555555555"
    assert str(emth117.lectures_dir).replace("\\", "/").endswith("/audio/EMTH117")
    assert emth117.lectures_dir == tmp_path / "audio" / "EMTH117"
    assert emth117.auth_state_path == tmp_path / ".auth" / "echo360-state.json"
    assert emth117.whisper_model == "small"
    assert emth117.whisper_device == "cpu"
    assert emth117.whisper_compute_type == "int8"
    assert emth117.transcribe_on_sync is True


def test_loads_transcription_options(tmp_path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
courses:
  chem114: 80588a39-c705-44cc-972e-e0ab4b6997b3
whisper_model: base
whisper_device: cpu
whisper_compute_type: float32
transcribe_on_sync: false
""".strip(),
        encoding="utf-8",
    )

    config = load_course_config(config_path, "chem114")

    assert config.whisper_model == "base"
    assert config.whisper_device == "cpu"
    assert config.whisper_compute_type == "float32"
    assert config.transcribe_on_sync is False


def test_absolute_paths_stay_absolute(tmp_path) -> None:
    auth_path = tmp_path / "auth" / "state.json"
    lectures_path = tmp_path / "course-data"
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f"""
courses:
  chem114: 80588a39-c705-44cc-972e-e0ab4b6997b3
auth_state_path: {auth_path}
lectures_dir: {lectures_path}
""".strip(),
        encoding="utf-8",
    )

    config = load_course_config(config_path, "chem114")

    assert config.auth_state_path == auth_path
    assert config.lectures_dir == lectures_path / "CHEM114"


def test_course_specific_auth_state_paths(tmp_path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
courses:
  chem114: 80588a39-c705-44cc-972e-e0ab4b6997b3
  emth118: 11111111-2222-3333-4444-555555555555
auth_state_path: .auth/echo360-state.json
auth_state_paths:
  emth118: .auth/echo360-emth118-state.json
""".strip(),
        encoding="utf-8",
    )

    chem114 = load_course_config(config_path, "chem114")
    emth118 = load_course_config(config_path, "emth118")

    assert chem114.auth_state_path == tmp_path / ".auth" / "echo360-state.json"
    assert emth118.auth_state_path == tmp_path / ".auth" / "echo360-emth118-state.json"


def test_legacy_section_id_still_loads(tmp_path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "section_id: b1629672-6a5f-4824-abb7-b33fdf7e0e9c",
        encoding="utf-8",
    )

    config = load_course_config(config_path)

    assert config.course_name == "default"
    assert config.section_id == "b1629672-6a5f-4824-abb7-b33fdf7e0e9c"
