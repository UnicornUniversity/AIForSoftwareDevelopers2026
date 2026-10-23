# image-forge

A small, generic batch picture generator for the OpenAI Image API. You describe
what you want in `settings.yaml` — tasks, prompt templates, subjects, quality
tier, image size, background, format, and post-processing — and run one Python
script.

The tool is self-contained: the plan → generate → post-process → resume loop
lives in these scripts, and every quality and appearance setting lives in
`settings.yaml` rather than in the code. Nothing about the subjects is baked in,
so it can drive any picture collection: sprites, icons, portraits, backdrops,
book covers, or one-off pieces.

## Layout

```
image-forge/
├── generate.py      # CLI: load settings, plan jobs, call the API, write files
├── config.py        # settings loading, merge order, validation
├── prompts.py       # subject lists, filename rules, prompt composition
├── postprocess.py   # key out, normalize, resize, pad, encode
├── settings.yaml    # every quality/appearance knob + example tasks
├── examples/        # sample subject files used by the example tasks
├── tests/           # offline unit tests (no API key needed)
└── output/          # generated pictures (gitignored)
```

## Quick start

```bash
cd week04/image-forge
python -m venv .venv
.venv/Scripts/activate              # Windows
# source .venv/bin/activate         # macOS/Linux
pip install -r requirements.txt

cp .env.example .env                # then fill in OPENAI_API_KEY
```

Check what is configured, then plan a run without spending anything:

```bash
python generate.py --list
python generate.py --dry-run
```

Generate a first task:

```bash
python generate.py --task postcards
```

Files land in `output/<task>/<name>.<format>`.

### API key

`gpt-image-1` is billed through the standard OpenAI API.

1. Sign in at <https://platform.openai.com/> and add billing.
2. Verify your organization for `gpt-image-1` under **Settings → Organization**.
   Without verification the API returns `403` even with a valid key.
3. Create a key at <https://platform.openai.com/api-keys>.
4. Put it in `.env` as `OPENAI_API_KEY=sk-...`. `.env` is gitignored; never put
   a key in `settings.yaml`, source code, or Markdown.

Set a monthly usage limit in the OpenAI dashboard before your first bulk run.
The OpenAI SDK also honours `OPENAI_BASE_URL`, so the tool can target an
OpenAI-compatible image endpoint; support for `images.generate`/`images.edit`
and the `quality`/`background` parameters depends on that endpoint.

## How a run works

```
settings.yaml
     │
     ▼
load + validate ──► merge appearance (defaults → global → task → subject)
     │
     ▼
collect subjects ──► build prompts ──► plan jobs (skip existing unless --force)
     │
     ▼
base images first ──► reference-edit jobs second
     │
     ▼
OpenAI image API ──► key out ──► normalize ──► resize ──► pad ──► encode
     │
     ▼
output/<task>/<stem>.<format>
```

Reruns are resumable: an existing output file is skipped unless `--force` is
passed. Planning is cheap, so `--dry-run` is the safe way to review a large run.

## The settings file

Everything visual is configured here. The root has five sections:

| Key | Purpose |
|---|---|
| `style` | Global art-direction text injected before every task prompt. |
| `appearance` | Defaults for model, quality, size, format and post-processing. |
| `appearance_presets` | Named bundles you can reference from tasks or subjects. |
| `runtime` | Output folder, concurrency, retries, resume behaviour. |
| `tasks` | What to generate. |

### Appearance

| Key | Values | Effect |
|---|---|---|
| `model` | `gpt-image-1` (default) | Image model. |
| `quality` | `low`, `medium`, `high`, `auto` | Cost/detail tier. `low` is for drafts. |
| `size` | `1024x1024`, `1024x1536`, `1536x1024`, `auto` | Native gpt-image-1 sizes; portrait, square, landscape. |
| `background` | `opaque`, `transparent`, `auto` | Ask the API for transparency, or key it locally. |
| `format` | `png`, `webp`, `jpeg` | Output encoding. JPEG cannot keep alpha. |
| `format_quality` | 1–100 | WebP/JPEG quality. |
| `key_out` | `enabled`, `mode`, `threshold` | Remove a flat painted backdrop and turn it transparent. |
| `normalize` | `enabled`, `canvas`, `fill` | Crop to the subject, center on a square canvas. |
| `resize` | `enabled`, `width`, `height`, `fit`, `background` | Fit the result into an exact frame. |
| `pad` | `enabled`, `all`/`top`/`right`/`bottom`/`left`, `color` | Add a border. |

Merge order, later wins:

```
built-in defaults → global `appearance` → task `appearance` → subject `appearance`
```

`appearance` at task or subject level accepts a preset name, an inline mapping,
or a list of either:

```yaml
appearance: sprite
appearance: [sprite, draft]           # sprite settings + quality: low
appearance: {size: 1024x1536, quality: high}
```

Presets themselves are partial; unspecified nested keys fall back to the global
value:

```yaml
appearance_presets:
  icon:
    size: 1024x1024
    background: opaque
    key_out: {enabled: true, mode: global, threshold: 70}
    normalize: {enabled: true, canvas: 512, fill: 0.82}
```

### Task fields

| Key | Meaning |
|---|---|
| `description` | Shown by `--list`; documentation only. |
| `prompt` | Template for each subject. Supports `{subject}`, `{name}`, `{stem}`, `{task}`. |
| `subjects` | Inline list of names, or mapping `name → description` / options. |
| `source` | Path (or list of paths) to a subject list file. |
| `output` | Subfolder under `runtime.output_dir`; defaults to the task name. |
| `naming` | `case: lower\|upper\|keep`, `separator: <one character>`. |
| `appearance` | Preset name, mapping, or list (see above). |
| `style` | Replaces the global `style` for this task. |
| `style_extra` | Appended to the (global or task) style. |

### Runtime

| Key | Default | Meaning |
|---|---|---|
| `output_dir` | `output` | Root for generated files, relative to the settings file. |
| `concurrency` | 3 | Parallel API calls. Keep low on lower rate tiers. |
| `retries` | 3 | Attempts per image. |
| `retry_backoff_seconds` | 1 | Wait is `backoff × 2**attempt` (2s, 4s, …). |
| `skip_existing` | true | Resume by skipping files that already exist. |

## Subjects

A subject becomes exactly one picture. There are three equivalent ways to
declare them.

**Inline list** — each string is both the subject text and the filename:

```yaml
subjects:
  - lighthouse-storm
  - desert-caravan
```

**Inline mapping** — the key is the filename; the value is the prompt text:

```yaml
subjects:
  lighthouse-storm: a lonely lighthouse on a rocky coast during a storm
  desert-caravan: a camel caravan crossing dunes at dusk
```

A mapping value can also be an options block:

```yaml
subjects:
  captain-vega-prime:
    subject: an older starship captain in an oxblood flight jacket
    base: captain-vega          # another subject, a generated stem, or an image path
    extra: Palette swap only; same pose and framing.
    appearance: {quality: high}
```

`base:` can name another subject in the task, the stem of a picture generated
by an earlier run in the same output folder, or a path to an image file
(relative to the settings file). The referenced picture is used as the
`images.edit` anchor, so the model keeps its pose, framing and style.

**Source file** — `source:` points at one file or a list:

- Markdown (`.md`) — the first two columns of a table are
  `name | description`. Header and separator rows are skipped.
- Plain text — one `name` or `name | description` per line. Blank lines and
  `#` comments are ignored; a leading `- ` bullet is allowed.

```markdown
| Name | Subject |
|---|---|
| captain-vega | a veteran starship captain, silver at the temples |
| smuggler-quill | a sharp-eyed smuggler with a crooked grin |
```

```text
ion-cell | a glowing blue energy cell with copper end caps
plasma-coil
```

Filenames are derived from the name using the task's `naming` rules. The
default is `lower` case and `_` as the single word separator; both whitespace
and hyphens become that separator, so `captain-vega` → `captain_vega`. Set
`separator: "-"` for kebab-case.

## Prompts

Unless a subject supplies a full `prompt`, the final prompt is assembled in
this order, separated by blank lines:

1. global `style` (or the task's `style` override)
2. task `style_extra`
3. task `prompt`
4. subject `extra`

`{subject}` (alias `{name}`) is replaced by the subject description, or by the
name when there is no description. `{stem}` is the filename stem and `{task}`
is the task name.

A subject-level `prompt:` is used verbatim and replaces all four parts. Keep the
style brief positive: naming a medium to avoid ("no 3D", "not a sculpture")
tends to make the model draw it.

## Post-processing

The steps run in this order, each only when enabled.

### `key_out` — painted backdrop to transparency

Best results come from asking for `background: opaque`, having the model paint
the subject on a flat white (or cream, or coloured) backdrop, and removing that
backdrop locally. The model's native `transparent` mode produces noticeably
coarser, figurine-like art.

- `mode: global` — removes every pixel within `threshold` RGB distance of the
  backdrop colour, including gaps trapped inside the silhouette.
- `mode: border` — removes only backdrop connected to the frame edge. Use it
  for pale subjects (skin, hair, white clothing) that sit close to the
  backdrop colour.
- The backdrop colour is estimated from the most common colour along the image
  border, so white, cream, and saturated backdrops all work.

### `normalize`

Crops to the visible subject and centers it on a `canvas × canvas` square, with
the subject filling `fill` of the frame. It needs alpha, so enable `key_out` or
use `background: transparent`.

### `resize` / `pad`

`resize` fits the image into an exact frame with `contain` (letterbox),
`cover` (center-crop), or `stretch`. `pad` adds a uniform or per-side border.
Both run after keying and normalization.

## Commands

```bash
python generate.py --list                     # tasks, subject counts, resolved look
python generate.py --dry-run                  # plan every task and print prompts
python generate.py --task postcards           # one task
python generate.py --task icons --task cover  # several tasks
python generate.py --id ion_cell              # one subject, across tasks
python generate.py --limit 3                  # first three planned images
python generate.py --task postcards --limit 2 # cheap draft
python generate.py --force                    # regenerate existing files
python generate.py --config other.yaml        # alternative settings file
python generate.py --concurrency 6            # override runtime.concurrency
```

| Flag | Meaning |
|---|---|
| `--config PATH` | Settings file. Default: `settings.yaml` next to `generate.py`. |
| `--task NAME` | Restrict to a task (repeatable). Default: all tasks. |
| `--id NAME` | One subject, matched by raw name or filename stem. |
| `--limit N` | Stop after N planned images. |
| `--concurrency N` | Parallel API calls. |
| `--force` | Ignore existing files. |
| `--dry-run` | Print the plan and prompts; no API calls, no key needed. |
| `--list` | Show tasks and resolved appearance; no API calls. |

`--id` may still need a base image on disk. For a subject with `base:`, run the
whole task once (or generate the base first); reference edits always run after
their base.

## Examples in `settings.yaml`

| Task | Demonstrates |
|---|---|
| `postcards` | Landscape preset, kebab-case naming, inline description mapping. |
| `inventory-icons` | Icon preset (key out + normalize), plain-text source file. |
| `character-portraits` | Markdown table source, border keying, `base` reference edit. |
| `cover` | Inline appearance override, `style_extra`, one high-quality image. |

Try the prompts without spending money:

```bash
python generate.py --task character-portraits --dry-run
```

## Cost and quality

- Start with `quality: low` and `--limit 3` when calibrating a new task.
- Promote to `medium` once composition is right; reserve `high` for one-off
  hero images such as the `cover` task.
- `--dry-run` costs nothing and shows exactly what each image will be asked
  for.
- Concurrency spends several calls at once. Keep it at 2–3 on lower tiers.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `401` | `OPENAI_API_KEY` is missing or wrong. |
| `403` | The organization is not verified for `gpt-image-1`. |
| `... contained no b64_json` | The configured model does not return base64 images. |
| `size ... is not supported` | gpt-image-1 accepts only 1024x1024, 1536x1024, 1024x1536, or auto. |
| `jpeg cannot store an alpha channel` | Disable key out/transparency or switch to png/webp. |
| `normalize: needs transparency to crop against` | Enable `key_out` or use `background: transparent`. |
| `base ... does not exist` | Generate the base subject first, or remove `--id`. |
| Keying eats part of the subject | Lower `key_out.threshold`, or use `mode: border`. |
| Halo around a keyed sprite | The subject was painted close to the backdrop colour; lower the threshold and regenerate. |

## Tests

The parsing, merge, and prompt logic is covered by offline tests:

```bash
python -m unittest discover -s tests -t . -v
```

No API key or network access is needed.
