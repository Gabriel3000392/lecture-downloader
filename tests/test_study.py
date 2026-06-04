import json

from lecture_downloader.config import AppConfig
from lecture_downloader.study import (
    build_lecture_package,
    generate_study_packages,
    validate_lecture_package,
)


TRANSCRIPT_TEXT = """
---
course: "chem114"
media_id: "0a2feded-d16e-4aa7-976c-27dd3044175d"
title: "Kinetics"
date: "2026-05-13"
---

# Kinetics

[00:00:00.000 --> 00:00:05.000] Reaction rates describe how quickly reactants are consumed and products are formed during a chemical process.
[00:00:05.000 --> 00:00:10.000] The rate law connects concentration to the observed rate, and the exponents must be determined experimentally.
[00:00:10.000 --> 00:00:15.000] A catalyst changes the reaction pathway and lowers activation energy without being consumed by the overall reaction.
[00:00:15.000 --> 00:00:20.000] Temperature changes affect rate constants because more particles have enough energy to react successfully.
[00:00:20.000 --> 00:00:25.000] Students should connect the graph, the equation, and the particle-level explanation before choosing a calculation method.
[00:00:25.000 --> 00:00:30.000] Initial rates can be compared between experiments to infer reaction order for each reactant in the rate law.
[00:00:30.000 --> 00:00:35.000] Units on the rate constant depend on the overall order of the reaction and should be checked after solving.
"""


def test_build_lecture_package_from_transcript(tmp_path) -> None:
    config = AppConfig(
        section_id="section-id",
        course_name="chem114",
        lectures_dir=tmp_path / "lectures" / "CHEM114",
    )
    lecture_dir = config.lectures_dir / "2026-05-13_Kinetics"
    lecture_dir.mkdir(parents=True)
    (lecture_dir / "transcript.md").write_text(TRANSCRIPT_TEXT, encoding="utf-8")
    metadata = {
        "media_id": "0a2feded-d16e-4aa7-976c-27dd3044175d",
        "title": "Kinetics",
        "date": "2026-05-13",
    }

    package = build_lecture_package(config, lecture_dir, metadata)

    assert validate_lecture_package(package) == []
    assert package["course"]["code"] == "CHEM114"
    assert package["lecture"]["title"] == "Kinetics"
    assert "Reaction rates" in package["notes"]["contentHtml"]
    assert package["studyAssets"]["flashcards"]
    assert package["studyAssets"]["quizzes"][0]["questions"]


def test_build_lecture_package_with_openai_provider_and_fake_client(tmp_path) -> None:
    config = AppConfig(
        section_id="section-id",
        course_name="chem114",
        lectures_dir=tmp_path / "lectures" / "CHEM114",
    )
    lecture_dir = config.lectures_dir / "2026-05-13_Kinetics"
    lecture_dir.mkdir(parents=True)
    (lecture_dir / "transcript.md").write_text(TRANSCRIPT_TEXT, encoding="utf-8")
    metadata = {
        "media_id": "0a2feded-d16e-4aa7-976c-27dd3044175d",
        "title": "Kinetics",
        "date": "2026-05-13",
    }

    def fake_client(prompt: str, model: str) -> str:
        assert "Reaction rates" in prompt
        assert model == "test-model"
        return json.dumps(
            {
                "notes": {
                    "contentHtml": "<h2>Overview</h2><p>Reaction rates connect concentration, catalysts, and temperature to observable chemical change.</p>",
                    "contentMarkdown": "# Kinetics\n\nReaction rates connect concentration, catalysts, and temperature.",
                },
                "studyAssets": {
                    "tags": ["kinetics", "rate laws"],
                    "flashcards": [
                        {
                            "front": "What does a rate law connect?",
                            "back": "It connects reactant concentration to the observed reaction rate.",
                            "difficultySeed": "core",
                        }
                    ],
                    "quizzes": [
                        {
                            "title": "Kinetics check",
                            "questions": [
                                {
                                    "type": "short_answer",
                                    "prompt": "Why are rate-law exponents determined experimentally?",
                                    "options": [],
                                    "correctAnswer": "They come from measured rate data, not directly from the balanced equation.",
                                    "explanation": "Initial-rate comparisons reveal how concentration changes affect rate.",
                                }
                            ],
                        }
                    ],
                    "studyGuides": [
                        {
                            "title": "Kinetics exam checklist",
                            "content": "Explain rate laws, catalysts, and temperature effects.",
                        }
                    ],
                },
            }
        )

    package = build_lecture_package(
        config,
        lecture_dir,
        metadata,
        provider="openai",
        model="test-model",
        llm_client=fake_client,
    )

    assert validate_lecture_package(package) == []
    assert package["promptVersion"] == "openai-study-v1"
    assert "Reaction rates" in package["notes"]["contentHtml"]
    assert package["studyAssets"]["flashcards"][0]["front"] == "What does a rate law connect?"


def test_generate_study_packages_writes_sidecars_and_metadata(tmp_path) -> None:
    config = AppConfig(
        section_id="section-id",
        course_name="chem114",
        lectures_dir=tmp_path / "lectures" / "CHEM114",
    )
    lecture_dir = config.lectures_dir / "2026-05-13_Kinetics"
    lecture_dir.mkdir(parents=True)
    (lecture_dir / "transcript.md").write_text(TRANSCRIPT_TEXT, encoding="utf-8")
    (lecture_dir / "metadata.json").write_text(
        json.dumps(
            {
                "media_id": "0a2feded-d16e-4aa7-976c-27dd3044175d",
                "title": "Kinetics",
                "date": "2026-05-13",
            }
        ),
        encoding="utf-8",
    )

    results = generate_study_packages(config)
    package = json.loads((lecture_dir / "lecture-package.json").read_text(encoding="utf-8"))
    metadata = json.loads((lecture_dir / "metadata.json").read_text(encoding="utf-8"))

    assert results[0].status == "generated"
    assert (lecture_dir / "summary.md").exists()
    assert (lecture_dir / "flashcards.json").exists()
    assert (lecture_dir / "quiz.json").exists()
    assert package["source"]["id"] == "0a2feded-d16e-4aa7-976c-27dd3044175d"
    assert metadata["study_generation_status"] == "generated"


def test_generate_study_packages_skips_existing_package(tmp_path) -> None:
    config = AppConfig(
        section_id="section-id",
        course_name="chem114",
        lectures_dir=tmp_path / "lectures" / "CHEM114",
    )
    lecture_dir = config.lectures_dir / "2026-05-13_Kinetics"
    lecture_dir.mkdir(parents=True)
    (lecture_dir / "transcript.md").write_text(TRANSCRIPT_TEXT, encoding="utf-8")
    (lecture_dir / "lecture-package.json").write_text("{}", encoding="utf-8")

    results = generate_study_packages(config)

    assert results[0].status == "skipped"


def test_generate_study_packages_filters_by_match(tmp_path) -> None:
    config = AppConfig(
        section_id="section-id",
        course_name="chem114",
        lectures_dir=tmp_path / "lectures" / "CHEM114",
    )
    first_dir = config.lectures_dir / "2026-05-12_First"
    second_dir = config.lectures_dir / "2026-05-13_Kinetics"
    first_dir.mkdir(parents=True)
    second_dir.mkdir(parents=True)
    (first_dir / "transcript.md").write_text(TRANSCRIPT_TEXT, encoding="utf-8")
    (second_dir / "transcript.md").write_text(TRANSCRIPT_TEXT, encoding="utf-8")

    results = generate_study_packages(config, match="Kinetics")

    assert len(results) == 1
    assert results[0].path == second_dir / "lecture-package.json"
    assert not (first_dir / "lecture-package.json").exists()
    assert (second_dir / "lecture-package.json").exists()
