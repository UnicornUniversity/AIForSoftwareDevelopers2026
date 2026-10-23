---
name: thesis-book
description: Turn a folder of DOCX/PDF source documents into a formatted Word book or thesis, driven by a JSON settings file that describes the page, fonts, front matter and references. Use when the user asks to build a .docx from a corpus, add or revise a chapter, restyle or rebuild the document, or verify that every quotation is verbatim. Examples: "build the thesis from the corpus", "write chapter 3", "change the body font and rebuild", "check that the quotes are exact".
---

# Thesis Book

Build a single Word document from a corpus of source documents. You author the prose in your own
voice and quote the sources verbatim; a Python program extracts the text, checks every quotation,
and renders the `.docx`. You never parse a binary source by hand and never edit the output.

## Inputs

1. **Corpus folder** — the documents to draw on, normally listed in a `manifest.json` beside the
   settings file.
2. **Settings file** — JSON describing the document's appearance (page, fonts, margins, front
   matter, headers, references) and the book's metadata.

Defaults for this repository: the corpus is `week04/kangaroo-skill/coprus/` and the settings
file is `week04/kangaroo-skill/settings.json`. If the user names a different settings file or
corpus folder, use those instead; every relative path inside `settings.json` resolves against the
settings file's own directory, so the working directory does not matter.

## Preflight

The program lives inside this skill, at `python/build_book.py`. From the repository root that is
`.claude/skills/thesis-book/python/build_book.py`.

```bash
python -c "import docx, pdfplumber; print('ok')"
```

If that fails, install the pinned dependencies:

```bash
python -m pip install --user -r .claude/skills/thesis-book/requirements.txt
```

On Windows, prefix commands with `PYTHONIOENCODING=utf-8` when the console mangles source text.

## Commands

Run `python .claude/skills/thesis-book/python/build_book.py <command> --settings <file>` from
the repository root (or use the equivalent relative path from wherever you are). Every command
prints one JSON object on stdout and human diagnostics on stderr.

| Command | Purpose |
|---|---|
| `init` | Validate settings and corpus, extract every source, write a starter `book.json` and `frontmatter.json`. Refuses to overwrite existing files without `--force`. |
| `extract` | Refresh the text cache (`--refresh` ignores cached text). |
| `status` | Progress dashboard: chapters authored, word counts, `next_chapter`, `frontmatter_complete`, `ready_for_all`. Start here. |
| `context --chapter N` | The chapter's plan entry plus the full extracted text of its sources. This is what you author from. |
| `render --chapter N` | Validate chapters 1..N and the front matter, then rebuild the whole `.docx` from every authored chapter. |
| `render --all` | Final build; requires every planned chapter. |
| `validate [--all]` | All checks without rendering. |

Exit codes: `0` success, `2` usage/settings, `3` corpus/manifest, `4` content (plan, chapter,
quote), `5` render. An error names the file, line or settings key to fix.

## No settings file yet

The spec requires asking the user about appearance rather than inventing it. If the user has not
supplied a settings file, ask with `AskUserQuestion`, at most four questions at a time:

1. **Page** — A4 or Letter; margins (a 3.0–3.5 cm left margin is common for binding).
2. **Body text** — font, size, line spacing, alignment (thesis default: Times New Roman 12 pt,
   1.5, justified).
3. **Headings and quotes** — heading font (Arial), quote treatment, dash style.
4. **Structure** — title page, dedication, declaration, English abstract + keywords, Czech
   Anotace + klíčová slova, table of contents, page numbers, running header, reference style
   (Harvard or APA).

Offer the academic-thesis preset as the recommended answer to each. Write `settings.json`, run
`init`, and show the user the generated `book.json` outline for approval before authoring
anything. The full schema is in `reference.md`; unknown keys and out-of-range values are rejected
by name, so never guess a key.

## Chapter-by-chapter mode

1. `status` → take `next_chapter`, or the chapter the user names.
2. `context --chapter N` → read the source blocks.
3. Write `book/chapters/NN-slug.md` (see the chapter format below).
4. `validate`, then `render --chapter N`.
5. Report the output path, word count and warnings; invite review before the next chapter.

## Whole-book mode

Author the missing chapters in plan order, running `render --chapter N` after each so the document
grows visibly and a failure is caught on the chapter that caused it. Finish with
`validate --all` and `render --all`.

## Chapter format

```markdown
---
chapter: 3
title: Diet and Foraging
sources: doc05, doc12, doc23
---

Opening prose in your own words, citing sources parenthetically [doc05].

## Seasonal Shifts

Prose leading into a passage quoted exactly from the source:

> The highland diet was dominated by grey-tussock, Themeda umbralis, which contributed 38 percent of fecal fragments in the wet season and 31 percent in the dry season.
> — doc05

More prose. **Bold** and *italic* are available; `- item` makes a list item.
```

Rules the parser enforces, with line numbers:

- `chapter` and `title` must match `book.json`; `sources` must be a subset of that chapter's plan
  sources. To cite a document the plan does not list, add it to `book.json` first.
- A quote is one or more `>` lines ending with `— docNN`. The marker must be last. A quote without
  one, or one citing an undeclared source, is an error.
- `[docNN]` renders as the manifest's author–date citation, e.g. `(Voss and Kwan, 2019)`.
- Tables, images, links, code fences, `#` headings, footnotes, horizontal rules, HTML and
  indented blocks are hard errors. Only `##` headings exist, numbered `N.M` by the renderer.
- Quotes are checked verbatim against the extracted source after normalising quote glyphs,
  dashes and whitespace. Use `…` or `[...]` freely inside a quote: each segment either side of
  the elision must appear in order in the source.

## Hard rules

- **Copy quotations from `context` output.** Never retype from memory, and never paraphrase inside
  a `>` block. If validation says a quote is not verbatim, fix the quote.
- **Never hand-write provenance or reference entries.** The renderer builds them from
  `manifest.json`; inventing them would bypass the point of the check.
- **Never edit the generated `.docx`** and never patch it in place. Change settings or chapter
  Markdown and rebuild; the renderer always writes a fresh document atomically.
- **Never modify the corpus** or the manifest.
- **Preserve contradictions.** When sources disagree, state both claims and attribute each. Do not
  reconcile them into a smoother story.
- **Follow the settings for typography.** Use English smart quotes (“…”), never Czech „…“ or
  straight quotes, and place punctuation per `typography.quotes.punctuation`.
- **Write in your own voice.** Quotes support the argument; the chapter is not a collage of them.

## Appearance changes

Edit `settings.json` and rebuild. Useful knobs: `page.margins_cm`, `typography.body`,
`typography.headings`, `body.page_numbers`, `body.running_header`, `body.references.style`,
`body.captions`. A change to `body.captions` moves the reference-table caption accordingly.
Settings errors name the offending dotted key.

## Reference

Read `reference.md` (beside this file) when you need the complete settings schema, the
`book.json`/`frontmatter.json` formats, rendering details, or a fix for a validation error.
