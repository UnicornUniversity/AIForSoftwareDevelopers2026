# Thesis Book — a corpus-to-Word skill

A project-scoped Claude Code skill that turns a folder of source documents into one formatted
Word document, driven by a JSON settings file that describes its appearance. Claude writes the
chapters; a Python program extracts the sources, checks every quotation against them, and renders
the `.docx`.

It answers `spec.md`: a local skill, a settings file that describes the document's appearance,
a Python program doing the file work, and two inputs — a corpus folder and a settings file.

- **Skill:** [`../../.claude/skills/thesis-book/SKILL.md`](../../.claude/skills/thesis-book/SKILL.md)
- **Settings schema and chapter syntax:** [`../../.claude/skills/thesis-book/reference.md`](../../.claude/skills/thesis-book/reference.md)
- **The program:** [`../../.claude/skills/thesis-book/python/`](../../.claude/skills/thesis-book/python/),
  entry point `build_book.py` beside the `bookbuild/` package

The corpus is the committed folder `coprus/` (30 documents, 15 DOCX and 15 PDF) with
`manifest.json`. The folder name is misspelled; it is the name the assignment gives it and is not
changed.

## Install

Python 3.12+ is required; the deliverable was built and tested on 3.13.

```bash
python -m pip install -r .claude/skills/thesis-book/requirements.txt
```

Run that from the repository root. Everything else is the standard library. No API keys and no
network calls are involved: Claude authors in the session, and Python only touches local files.

## Quick start

The program ships inside the skill; run these from `week04/kangaroo-skill`. Paths inside
`settings.json` resolve against the settings file, so the working directory is not critical.

```bash
BOOK=../../.claude/skills/thesis-book/python/build_book.py

# 1. Validate settings and corpus, extract every source, write the plan and front matter
python $BOOK init --settings settings.json

# 2. See what is planned and what is still missing
python $BOOK status --settings settings.json

# 3. Fetch the source text for the chapter you are authoring
python $BOOK context --settings settings.json --chapter 3

# 4. After writing book/chapters/03-diet-and-foraging.md
python $BOOK validate --settings settings.json
python $BOOK render --settings settings.json --chapter 3

# Final build
python $BOOK validate --settings settings.json --all
python $BOOK render --settings settings.json --all
```

On PowerShell, use the full path in place of `$BOOK`, for example:

```powershell
python ..\..\.claude\skills\thesis-book\python\build_book.py status --settings settings.json
```

The output is `book/output/thesis.docx`.

On Windows, prefix commands with `PYTHONIOENCODING=utf-8` if the console mangles source text.

## The two modes

**Chapter by chapter.** `status` reports `next_chapter`. `context --chapter N` prints that
chapter's plan entry and the full extracted text of its sources. Claude writes
`book/chapters/NN-slug.md`, `validate` checks it, and `render --chapter N` rebuilds the whole
document from chapters 1..N. The user reviews between chapters; a later rebuild never loses an
earlier chapter.

**Whole book.** The same loop over every missing chapter in plan order, rendering after each so
the document grows visibly and a failure is attributed to the chapter that caused it. `render
--all` is the final build and refuses to run while a planned chapter is missing.

## Using the skill

Start a Claude Code session at the repository root. The skill lives at
`.claude/skills/thesis-book/` and is available as `/thesis-book` (a session that was already
running when the skill was created may need to be restarted). Then ask for what you want:

- “Build the thesis from the corpus in week04/kangaroo-skill.”
- “Add the next chapter.”
- “Set the body font to 11 pt and rebuild.”
- “Check that the quotations are exact.”

If no settings file exists, the skill asks about page size, margins, body font, spacing,
alignment, headings, and which front-matter sections to include, then writes `settings.json`.
`settings.json` in this folder is a completed academic-thesis preset and is a usable starting
point.

## How it works

```
settings.json ──> validation ──┐
manifest.json ──> extraction ──┴─> cache ──> context ──> Claude authors chapters
                                                            │
book.json (plan) ───────────────────────────────────────────┤
frontmatter.json ───────────────────────────────────────────┤
                                                            ▼
                                              validate (quotes, citations, plan)
                                                            │
                                                            ▼
                                                   python-docx renderer
                                                            │
                                                            ▼
                                                 book/output/thesis.docx
```

- **Extraction** (`extract.py`) reads DOCX paragraphs and tables in document order, and PDF
  pages through line positions: it removes running headers, page numbers, DOIs and affiliations,
  rejoins hyphenated line breaks, stitches paragraphs across page boundaries, and marks title and
  front matter separately so quotes cannot accidentally match them. Results are cached under
  `book/.work/sources/`, keyed on file hash, size and extractor version.
- **Authoring** uses a constrained Markdown subset (`markdown.py`): front matter, `##` headings,
  paragraphs, `**bold**`, `*italic*`, `[docNN]` citations, `-` lists, and block quotes ending in
  `— docNN`. Anything else — tables, images, links, code fences, `#` headings — is a hard error
  with a line number rather than silently dropped content.
- **Validation** (`validate.py`) checks the plan against the chapters, every citation against the
  declared sources, and every quotation against the extracted source text, after normalising
  quote glyphs, dashes, whitespace and case. Ellipses split a quotation into segments that must
  occur in order, so elided quotes are checked too.
- **Rendering** (`render.py`) builds a fresh document every time and saves it atomically. Front
  matter and body are separate sections so the front matter carries no page numbers, the body
  restarts at 1 on the Introduction, and the running header belongs to the body only.

## What the document contains

Per `settings.json`: A4, margins 2.5 cm top/bottom/right and 3.5 cm left; title page, dedication,
declaration; an English Abstract and a Czech Anotace, each with its keyword list; a table of
contents; page numbers at bottom centre starting at the Introduction; a running header; numbered
chapters and sections; verbatim quotations with generated provenance lines; and a Harvard-style
reference table captioned above.

Body text is Times New Roman 12 pt, exactly 1.5 line spacing, fully justified. Headings are
Arial. English smart quotes (“…”), never Czech „…“ or straight quotes; unspaced em dashes for
sentence breaks, unspaced en dashes for ranges, hyphens for compounds; no non-breaking spaces
around single-letter words.

Every appearance option is a settings key, not a constant. Change the file and rebuild; the
renderer never patches the binary.

## The book plan

`book/book.json` maps all 30 documents to nine thematic chapters: Introduction; Ecology and
Habitat; Diet and Foraging; Behaviour and Communication; Movement and Migration; Physiology and
Adaptation; Predators and Mortality; Mythology and Folklore; Conservation, Policy and Conclusion.

Two chapters are committed as a worked example — `01-introduction.md` and
`02-ecology-and-habitat.md` — and `book/output/thesis.docx` is their two-chapter build. They
demonstrate the whole pipeline: prose by Claude, verbatim quotes checked against the sources,
provenance and references generated from the manifest. The remaining chapters are authored on
request in either mode; the plan already lists their sources.

## Design notes

- **Model output is checked, not trusted.** A quote is not “probably right”: it is matched
  against the extracted source, and provenance and reference entries are generated, never
  hand-written. The authoring rules alone would not prove anything.
- **Strict settings.** Unknown keys and out-of-range values fail with the dotted key. A silent
  fallback in a document's appearance is a bug the user discovers in Word.
- **Contradictions are preserved.** The corpus names the animal *M. umbracauda*,
  *Notamacropus penumbra*, *Notamacropus umbrica* and *Umbracauda nocturna*, and disagrees on
  juvenile diet. Chapters state the claims and attribute them; they never reconcile them into a
  smoother story.
- **No LLM, no network.** The skill is a procedure for Claude plus a deterministic local tool.
  The only non-stdlib dependencies are `python-docx` and `pdfplumber`.
- **Exit codes carry meaning** — 2 settings/usage, 3 corpus, 4 content, 5 render — so the skill
  can tell a wrong path from a wrong quote without reading prose.

## Tests

```bash
cd .claude/skills/thesis-book
python -m unittest discover -s tests -t .
```

53 tests, about one second, no network and no real corpus required: fixtures build a tiny DOCX
corpus in a temporary directory. They cover settings validation, manifest repair, typography,
Markdown parsing, DOCX/PDF extraction and caching, verbatim checking, the renderer's XML (page
size, margins, fonts, fields, section layout, caption order), and CLI exit codes. The three tests
that read the real corpus and settings skip when `week04/kangaroo-skill` is absent.

## Limitations

- The table of contents and page fields are computed by Word, not by Python. `updateFields` makes
  Word offer to update on open; the tests assert the field XML, not laid-out pages. If the TOC is
  empty, press Ctrl+A then F9 in Word.
- Harvard entries are built from the manifest's `authors`, `year` and `venue`. Where those are
  absent the document id stands in for the author and `n.d.` for the year. `style: "apa"` is
  accepted but currently produces the same author–date entry.
- Chapters cannot contain tables, images or figures. Source tables are preserved as extracted
  text and can be described, not embedded. The only generated table is the reference list.
- Quotations are checked on normalised wording, not original glyphs: smart quotes and dashes are
  applied to quoted text too, so the guarantee is the words, not the typesetting of the source.
- The renderer references fonts by name; a machine without Times New Roman and Arial substitutes
  them.
- Not in scope: PDF/EPUB/LaTeX output, source-style preservation, incremental editing of the
  `.docx`, global skill installation, or automatic resolution of contradictions.
