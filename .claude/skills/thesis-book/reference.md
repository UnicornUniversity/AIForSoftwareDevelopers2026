# thesis-book — reference

Everything the skill needs beyond the procedure in `SKILL.md`: the settings schema, the two
book files, the chapter format, what the renderer produces, and how to fix a failed command.

---

## 1. Files the tool reads and writes

Paths in `settings.json` resolve against **the settings file's directory**, so the tool works from
any current directory.

The program itself lives in this skill: `python/build_book.py` with the `bookbuild/` package
beside it, its tests in `tests/`, and its pinned dependencies in `requirements.txt`. Nothing in
`week04/kangaroo-skill` is needed to run the tool except the corpus, settings and book files.

| Path | Written by | Purpose |
|---|---|---|
| `settings.json` | you, or the user | Appearance and book metadata |
| `book/book.json` | `init`, then edited by hand | Chapter plan |
| `book/frontmatter.json` | `init`, then authored | Dedication, declaration, abstracts, keywords |
| `book/chapters/NN-slug.md` | Claude | Chapter text |
| `book/.work/sources/<id>.json` | `extract`/`context`/`validate` | Extraction cache (safe to delete) |
| `book/output/thesis.docx` | `render` | The deliverable |
| `<corpus>/manifest.json` or beside settings | corpus author | Document list and metadata |

The corpus folder is named `coprus/` in this repository. That is its real name, not a typo.

The cache is keyed on file hash, size and extractor version, so a replaced source re-extracts
automatically. `extract --refresh` forces it.

---

## 2. Commands

Run from the repository root; the program ships inside the skill:

```bash
python .claude/skills/thesis-book/python/build_book.py init      --settings settings.json [--corpus DIR] [--manifest FILE] [--force]
python .claude/skills/thesis-book/python/build_book.py extract   --settings settings.json [--refresh]
python .claude/skills/thesis-book/python/build_book.py status    --settings settings.json
python .claude/skills/thesis-book/python/build_book.py context   --settings settings.json --chapter N
python .claude/skills/thesis-book/python/build_book.py render    --settings settings.json --chapter N
python .claude/skills/thesis-book/python/build_book.py render    --settings settings.json --all
python .claude/skills/thesis-book/python/build_book.py validate  --settings settings.json [--all]
```

Every command prints JSON on stdout; diagnostics go to stderr.

`status` JSON: `chapters[]` (number, title, path, authored, words, sources, used_sources,
missing_sources), `missing`, `warnings`, `used_sources`, `frontmatter_complete`,
`next_chapter`, `ready_for_all`, plus `plan`, `output`, `total_words`, `output_exists`.

`context` JSON: `chapter` (number, slug, title, sources, path), `sources` (per document: title,
authors, year, venue, document_type, sub_topic, format, word_count, has_contradiction, citation,
`blocks[]`), a flat `blocks[]` of `{id, kind, text}`, and a `note` restating the provenance rule.

`render` JSON: `output`, `chapters`, `words`, `used_sources`, `warnings`.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 2 | Bad usage or invalid settings |
| 3 | Missing corpus, manifest or source file |
| 4 | Invalid plan, front matter, chapter, citation or quotation |
| 5 | The document could not be rendered |

---

## 3. `settings.json`

Strict schema. An unknown key, a wrong type, or a value outside its range is an error naming the
dotted key. Keys marked *optional* may be omitted; everything else is required.

### 3.1 `schema_version`

Must be the integer `1`.

### 3.2 `book`

| Key | Type | Notes |
|---|---|---|
| `title` | string | Required. Also used by the running header when set to `book_title`. |
| `subtitle` | string, optional | Omitted from the title page when empty. |
| `author` | string | Shown on the title page. |
| `institution` | string, optional | Omitted when empty. |
| `date` | string | Free text; use `23 October 2026` rather than an ISO date, which the dash rules would otherwise touch. |
| `language` | string | BCP 47 tag, e.g. `en-GB`; set on the document. |
| `plan` | string | Path to `book.json`. |
| `frontmatter` | string | Path to `frontmatter.json`. |
| `output` | string | Path to the `.docx` to write. |

### 3.3 `page`

| Key | Values |
|---|---|
| `size` | `A4` or `Letter` |
| `margins_cm` | object with `top`, `bottom`, `left`, `right`; each 0–10 cm |

A left margin of 3.0–3.5 cm leaves room for binding.

### 3.4 `typography`

`body`

| Key | Range / values |
|---|---|
| `font` | any font name |
| `size_pt` | 6–36 |
| `line_spacing` | 1–3 (1.5 = one-and-a-half) |
| `alignment` | `left`, `center`, `right`, `justify` |
| `space_before_pt`, `space_after_pt` | 0–72 |
| `first_line_indent_cm` | 0–5 |

`headings`

| Key | Range / values |
|---|---|
| `font` | any font name (Arial is the thesis default) |
| `bold` | boolean |
| `color` | six hex digits, e.g. `000000` or `444444` |
| `h1_size_pt`, `h2_size_pt` | 8–48 |
| `h1_space_before_pt`, `h1_space_after_pt`, `h2_space_before_pt`, `h2_space_after_pt` | 0–72 |

`front_titles` — the labels on front-matter pages (Dedication, Abstract, Contents): `font`,
`size_pt` 8–48, `bold`, `align` (`left`/`center`/`right`/`justify`).

`quote` — displayed quotations: `size_pt` 6–36, `italic`, `indent_cm` 0–5.

`provenance` — the line under each quote: `size_pt` 6–24, `italic`, `color`.

`quotes` — `style` must be `english_smart`; `punctuation` is `outside` (British: punctuation
belongs outside the closing quote unless it was in the original) or `inside` (American). The
setting is an authoring rule: the renderer cannot infer which punctuation the source owns.

`dashes` — `sentence` and `range`, each `em`, `en` or `hyphen`.
`--` always becomes an em dash; ` - ` becomes the configured sentence dash; digit-hyphen-digit
becomes the configured range dash; word-internal hyphens are untouched.

`nbsp_for_single_letters` — boolean. Recorded in the schema; the renderer does **not** insert
non-breaking spaces, and the default is `false`.

### 3.5 `front_matter`

| Key | Values |
|---|---|
| `title_page` | boolean |
| `dedication` | boolean; the dedication page is skipped when its text is empty |
| `declaration` | boolean; when true, `frontmatter.declaration` must be non-empty |
| `abstract` | `{enabled, title, keywords_title}` |
| `anotace` | `{enabled, title, keywords_title}` — the Czech abstract |
| `table_of_contents` | `{enabled, depth (1–3, integer), title}` |

### 3.6 `body`

`page_numbers` — `enabled`, `position` (`bottom_center` or `bottom_right`),
`start_at_introduction` (boolean). When true, numbering restarts at 1 on the Introduction and
front matter carries no visible number.

`running_header` — `enabled`, `text` (`book_title` or `chapter_title`), `align` (`left`, `center`,
`right`).

`chapter_start_new_page` — boolean; each chapter after the first starts a new page.

`heading_numbering` — `enabled`, `format` (`decimal`). Chapters render `N  Title`, sections
`N.M  Section`.

`references` — `enabled`, `title` (e.g. `References`), `style` (`harvard` or `apa`),
`scope` (`used` = only cited sources, `all` = every manifest entry), `sort` (`id` or `title`).
The current renderer emits the same author–date entry for both styles; see §7.

`captions` — `table` and `figure` are each `above` or `below`; `numbering` is `continuous`.
The table setting positions the reference-table caption. Chapters cannot contain figures or
tables, so the figure setting is reserved for future content.

### 3.7 `corpus`

`folder` (path), `manifest` (path), `formats` (non-empty list drawn from `docx`, `pdf`, no
repeats). A format left out is skipped by `init`/`extract`.

Manifest discovery, when the configured path is absent, also tries `<corpus>/manifest.json` and
`<corpus>/../manifest.json`. `--manifest` overrides it.

### 3.8 `citations`

`in_text` — `author_date` (e.g. `(Voss and Kwan, 2019)`) or `id` (e.g. `(doc06)`).

---

## 4. `book.json`

```json
{
  "title": "The Shadowtail Kangaroo",
  "chapters": [
    { "number": 1, "slug": "introduction", "title": "Introduction",
      "sources": ["doc01", "doc17"] }
  ]
}
```

- `title` is a non-empty string.
- `number` is an integer, contiguous from 1.
- `slug` is lowercase words joined by hyphens; it names the file `chapters/NN-slug.md`.
- `title` must match the chapter file's front-matter `title`.
- `sources` is a non-empty list of unique `docNN` ids that exist in the manifest.
- Unknown keys anywhere are errors.

The chapter file for entry *N* is `book/chapters/{NN}-{slug}.md`.

`init` writes a starter plan with one chapter per `sub_topic`. Treat it as a starting point:
propose a thematic outline that maps every document, and get the user's agreement before
authoring.

---

## 5. `frontmatter.json`

```json
{
  "dedication": "For ...",
  "declaration": "I declare that ...",
  "abstract": { "text": "...", "keywords": ["...", "..."] },
  "anotace":  { "text": "...", "keywords": ["...", "..."] }
}
```

Allowed keys only: `dedication`, `declaration`, `abstract`, `anotace`. Both abstract objects
take exactly `text` and `keywords`. Whenever a section is enabled in settings, its text and at
least one keyword must be non-empty. The declaration is mandatory when enabled; the dedication
may be empty and is then skipped. Czech text is allowed in `anotace`; English smart quotes still
apply.

---

## 6. Chapter Markdown

### 6.1 Front matter

The file must begin with `---` and close with `---`. Keys: `chapter`, `title`, `sources`.
`sources` is a comma-separated list of `docNN`.

### 6.2 Blocks

| Syntax | Result |
|---|---|
| `## Heading` | Heading 2, rendered `N.M  Heading` |
| blank-line-separated text | Body paragraph, justified |
| `**bold**`, `*italic*` | Inline formatting |
| `[docNN]` | Author–date citation from the manifest |
| `> text` … `> — docNN` | Quotation plus generated provenance line |
| `- item` | Bulleted list item |

### 6.3 Rejected syntax

Code fences, tables (`|`), `#` and `###` headings, images, links, footnotes, horizontal rules,
HTML and indented blocks are errors with a line number.

### 6.4 Quotations

- A quote is a run of `>` lines; its last line must be `— docNN`, naming a source declared in
  the chapter's front matter (and therefore in the plan).
- Quoted text is matched against the extracted source after normalising case, whitespace, quote
  glyphs, dashes and ellipsis characters.
- `…`, `...` or `[...]` split a quote into segments; every segment must appear in the source,
  in order.
- Quotes shorter than four words produce a warning, not an error.
- Source text is the *body* only: running headers, page numbers, DOIs, affiliations and reference
  lists are removed during extraction, so a quote from a reference list will not validate.

### 6.5 Citations

Every `[docNN]` and every quote marker must name a source declared in that chapter. To use a new
document, add it to the plan entry's `sources` and to the chapter front matter. Declared but
unused sources produce a warning.

---

## 7. What the renderer produces

One fresh document per run, saved atomically; the previous file is replaced, never patched.

1. **Page** — size and margins from settings; A4 is 21 × 29.7 cm.
2. **Styles** — Normal from `typography.body` (font with ascii/hAnsi/cs/eastAsia set, size, line
   spacing, alignment, spacing, indent); Heading 1/2 from `typography.headings`; dedicated
   styles for front titles, quotes, provenance, list items, captions and reference entries.
3. **Section 1 — front matter**, with an unlinked empty header and footer:
   title page → dedication → declaration → Abstract (Key words) → Anotace (Klíčová slova) →
   Contents.
4. **Section 2 — body**, starting on a new page. Its footer carries a `PAGE` field at the
   configured position; numbering restarts at 1 when `start_at_introduction` is true. Its header
   carries the running text at the configured alignment.
5. **Table of contents** — a `TOC \o "1-2"` field over Heading 1 and Heading 2, plus
   `w:updateFields` so Word offers to update it on open. Depth follows
   `front_matter.table_of_contents.depth`.
6. **Chapters** — Heading 1 `N  Title` (page break before, except the first); Heading 2
   `N.M  Heading`; paragraphs with inline runs and citations; quotes in the quote style followed
   by a provenance line:
   `docNN · Author (year) · Title (FORMAT, N words)`.
7. **References** — Heading 1 (unnumbered), page break before, caption
   `Table 1: Source documents cited in this thesis.` positioned per `captions.table`, then a
   Table Grid with a bold repeating header row (`ID`, `Reference`). Entries
   read `Surname, I., & Surname, I. (Year). Title. Venue.`; without manifest metadata the
   document id stands in for the author and `n.d.` for the year.
8. **Properties** — title, subject, author and language.

`style: apa` is accepted and validated but currently renders the same author–date entry as
`harvard`. The distinction between the two is a formatting convention (ampersand placement,
italics, DOI handling) that this renderer does not vary.

Fonts are referenced by name; a machine without Arial or Times New Roman will substitute them.

---

## 8. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `settings file not found` | Pass the correct `--settings` path. |
| `page.margins_cm.left: must be at most 10` | A settings value is out of range; the message names the dotted key. |
| `unknown key(s): …` | A typo in settings, plan or front matter. Keys are strict on purpose. |
| `settings file already exists` / plan exists | `init` refuses to overwrite; pass `--force` only when you mean to replace the plan and front matter. |
| `unknown source id 'doc31'` | The plan or chapter cites an id absent from the manifest. |
| `citation [docNN] is not listed in the chapter's sources` | Add the id to the chapter front matter and to `book.json`. |
| `quote source 'docNN' is not listed …` | Same fix; the `— docNN` marker counts as a use. |
| `quote not found verbatim in docNN` | Copy the sentence exactly from `context` output. Common causes: retyped punctuation, a paraphrase, or a quote that spans a removed header/table/reference list. |
| `chapter title '…' does not match the plan` | Make the front matter match `book.json`, or edit the plan. |
| `chapter number … does not match the plan` | Same. |
| `render requires every earlier chapter` | Author chapters 1..N in order, or render a lower N. |
| `the full build needs every planned chapter` | `--all` needs all of them; use `--chapter N` meanwhile. |
| `front matter is incomplete` | Fill `declaration`, both abstracts and both keyword lists. |
| `level-1 headings are reserved …` | Use `##`. |
| TOC is empty or says "Right-click to update field" | Word has not updated fields. Open the document, Ctrl+A then F9 (or F9 on the field), and allow the update. |
| Text looks stale after replacing a source | The cache keys on the file hash, so this should not happen; run `extract --refresh` if the file's timestamp and size were preserved artificially. |
| `UnicodeEncodeError: 'charmap' codec` | Set `PYTHONIOENCODING=utf-8` (Windows console). |
| Smart quotes or dashes absent | Prose is transformed by the renderer; check `typography.quotes` and `typography.dashes`. Raw Markdown is not rewritten. |
| A source title shows `â€”` | The manifest has UTF-8-read-as-cp1252 mojibake; the loader repairs it automatically. If a title is still wrong, fix it in the manifest. |
| Word refuses to open the output | Close Word first (a `~$thesis.docx` lock file can block the atomic replace), then rebuild. |
