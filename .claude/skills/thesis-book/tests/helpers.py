"""Shared fixtures: a tiny corpus, settings and chapter files in a temp folder."""

from __future__ import annotations

import json
from pathlib import Path

# The skill lives at .claude/skills/thesis-book/; the corpus it was written for
# lives in the assignment folder.  Tests that use the real corpus skip when it
# is absent, so the suite still runs if the skill is copied elsewhere.
SKILL = Path(__file__).resolve().parents[1]
PROJECT = SKILL.parents[2] / "week04" / "kangaroo-skill"


def typography() -> dict:
    return {
        "body": {
            "font": "Times New Roman",
            "size_pt": 12,
            "line_spacing": 1.5,
            "alignment": "justify",
            "space_before_pt": 0,
            "space_after_pt": 6,
            "first_line_indent_cm": 0,
        },
        "headings": {
            "font": "Arial",
            "bold": True,
            "color": "000000",
            "h1_size_pt": 16,
            "h2_size_pt": 13,
            "h1_space_before_pt": 18,
            "h1_space_after_pt": 12,
            "h2_space_before_pt": 12,
            "h2_space_after_pt": 6,
        },
        "front_titles": {"font": "Arial", "size_pt": 14, "bold": True, "align": "center"},
        "quote": {"size_pt": 11, "italic": True, "indent_cm": 1.0},
        "provenance": {"size_pt": 9, "italic": True, "color": "444444"},
        "quotes": {"style": "english_smart", "punctuation": "outside"},
        "dashes": {"sentence": "em", "range": "en"},
        "nbsp_for_single_letters": False,
    }


def settings_dict() -> dict:
    return {
        "schema_version": 1,
        "book": {
            "title": "Fixture Book",
            "subtitle": "A Tiny Thesis",
            "author": "Test Author",
            "institution": "Test University",
            "date": "2026-10-23",
            "language": "en-GB",
            "plan": "book/book.json",
            "frontmatter": "book/frontmatter.json",
            "output": "book/output/thesis.docx",
        },
        "page": {
            "size": "A4",
            "margins_cm": {"top": 2.5, "bottom": 2.5, "left": 3.5, "right": 2.5},
        },
        "typography": typography(),
        "front_matter": {
            "title_page": True,
            "dedication": True,
            "declaration": True,
            "abstract": {"enabled": True, "title": "Abstract", "keywords_title": "Key words"},
            "anotace": {"enabled": True, "title": "Anotace", "keywords_title": "Klíčová slova"},
            "table_of_contents": {"enabled": True, "depth": 2, "title": "Contents"},
        },
        "body": {
            "page_numbers": {
                "enabled": True,
                "position": "bottom_center",
                "start_at_introduction": True,
            },
            "running_header": {"enabled": True, "text": "book_title", "align": "right"},
            "chapter_start_new_page": True,
            "heading_numbering": {"enabled": True, "format": "decimal"},
            "references": {
                "enabled": True,
                "title": "References",
                "style": "harvard",
                "scope": "used",
                "sort": "id",
            },
            "captions": {"table": "above", "figure": "below", "numbering": "continuous"},
        },
        "corpus": {
            "folder": "corpus",
            "manifest": "corpus/manifest.json",
            "formats": ["docx", "pdf"],
        },
        "citations": {"in_text": "author_date"},
    }


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def make_fixture(root: Path) -> dict:
    """Create settings.json, corpus/doc01-fixture.docx and manifest.json."""

    import docx

    root.mkdir(parents=True, exist_ok=True)
    settings = settings_dict()
    write_json(root / "settings.json", settings)

    corpus = root / "corpus"
    corpus.mkdir(exist_ok=True)
    document = docx.Document()
    title = document.add_paragraph()
    run = title.add_run("Field Notes on a Fixture Kangaroo")
    run.bold = True
    run.font.size = docx.shared.Pt(16)
    summary = document.add_paragraph()
    summary_run = summary.add_run("Executive summary")
    summary_run.bold = True
    body_one = document.add_paragraph(
        "The alpha line runs east—west and covers 1810–1960 m. "
        "Twelve transects were walked at first light."
    )
    body_two = document.add_paragraph(
        "Troupe size ranged from 4 to 7 animals, and no stable harem was recorded."
    )
    body_one.runs[0].font.size = docx.shared.Pt(11)
    body_two.runs[0].font.size = docx.shared.Pt(11)
    heading = document.add_paragraph()
    heading_run = heading.add_run("References")
    heading_run.bold = True
    document.add_paragraph("Voss, E. M. (2018). A fixture study.")
    document.save(str(corpus / "doc01-fixture.docx"))

    manifest = {
        "count": 1,
        "documents": [
            {
                "id": "doc01",
                "filename": "doc01-fixture.docx",
                "format": "docx",
                "sub_topic": "ecology",
                "title": "Field Notes on a Fixture Kangaroo",
                "word_count": 30,
                "target_words": 30,
                "has_contradiction": True,
                "authors": ["E. M. Voss"],
                "year": 2018,
                "venue": "Fixture Station, FN-2018-01",
                "document_type": "Field notebook",
                "has_figure": False,
                "body_word_count": 20,
            }
        ],
    }
    write_json(corpus / "manifest.json", manifest)

    chapters = root / "book" / "chapters"
    chapters.mkdir(parents=True, exist_ok=True)
    write_json(
        root / "book" / "book.json",
        {
            "title": "Fixture Book",
            "chapters": [
                {
                    "number": 1,
                    "slug": "ecology",
                    "title": "Ecology",
                    "sources": ["doc01"],
                }
            ],
        },
    )
    write_json(
        root / "book" / "frontmatter.json",
        {
            "dedication": "For the fixture.",
            "declaration": "I declare that this fixture is my own work.",
            "abstract": {
                "text": "This thesis describes a fixture kangaroo.\n\nIt uses a tiny corpus.",
                "keywords": ["fixture", "kangaroo"],
            },
            "anotace": {
                "text": "Tato práce popisuje fiktivního klokana.",
                "keywords": ["fixture", "klokan"],
            },
        },
    )
    (chapters / "01-ecology.md").write_text(
        "---\nchapter: 1\ntitle: Ecology\nsources: doc01\n---\n\n"
        "The alpha line is the central feature of this fixture [doc01].\n\n"
        "## The Alpha Line\n\n"
        "A verbatim observation follows.\n\n"
        "> The alpha line runs east—west and covers 1810–1960 m.\n"
        "> — doc01\n\n"
        "A closing sentence with emphasis on *troupe size* and **transects**.\n",
        encoding="utf-8",
    )
    return {
        "root": root,
        "settings": root / "settings.json",
        "corpus": corpus,
        "manifest": corpus / "manifest.json",
        "book": root / "book",
        "chapters": chapters,
    }
