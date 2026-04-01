# bt-class-downloader

Download **lesson transcription** text from [BiblicalTraining.org](https://www.biblicaltraining.org/) for **any class**, given the **course (class) overview URL**.

## What URL to use

Use the **class overview** page — the one that lists “Lessons” and shows “Number of lessons: …”, for example:

- `https://www.biblicaltraining.org/learn/institute/nt201-biblical-greek`
- `https://www.biblicaltraining.org/learn/institute/nt605-textual-criticism`
- `https://www.biblicaltraining.org/learn/foundations/nt101-essentials-of-the-new-testament`

Do **not** pass a single-lesson URL only; the tool needs the course page to discover all lesson links.

## Prerequisites

- Python 3.11+

## Install

```bash
cd /path/to/class-downloader
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
python -m playwright install chromium
```

## Commands

### `download` — fetch transcripts

**Required:** the `download` subcommand and one or more course identifiers (each a URL or slug-prefix from the index).

```bash
python -m bt.cli download \
  "https://www.biblicaltraining.org/learn/institute/nt201-biblical-greek"

# Or use a slug-prefix from the local course index:
python -m bt.cli download nt201

# Multiple courses (each writes transcripts/<slug>.md; do not use --out):
python -m bt.cli download nt201 nt203
```

Default output: `transcripts/<course-slug>.md` (e.g. `transcripts/nt201-biblical-greek.md`).

The tool always writes the class outline to **`outlines/<course-slug>.outline.md`** (same basename as the transcript file). The file starts with the class title as `# …`, then each lesson is `## Lesson {n}: {lesson title}` with Markdown bullet outlines (HTML stripped). Embedded `__NEXT_DATA__` is used when present; otherwise lesson outlines come from JSON:API (`include=field_lessons`). If no outline can be obtained, **`download` exits with code 4** before any lesson pages are fetched.

Custom transcript path (single course only; not available when downloading multiple courses):

```bash
python -m bt.cli download \
  "https://www.biblicaltraining.org/learn/institute/nt605-textual-criticism" \
  --out transcripts/nt605.md
```

After install, you can also use the console script:

```bash
biblicaltraining-transcripts download "https://www.biblicaltraining.org/learn/institute/nt201-biblical-greek"
```

#### Course index (used for slug-prefix lookup)

The CLI maintains a local **course index** fetched from `https://www.biblicaltraining.org/classes` and cached in your **user cache directory**:

- macOS: `~/Library/Caches/bt-class-downloader/course_index.json`
- others: `~/.cache/bt-class-downloader/course_index.json`

On startup, if the index file does not exist, the CLI will fetch it automatically. To force a refetch:

```bash
python -m bt.cli refresh-index
```

You can inspect the cached index:

```bash
python -m bt.cli list-index --limit 25
python -m bt.cli search-index nt201
```

Slug-prefix lookups (like `nt201`) must match **exactly one** course slug; if there are 0 matches or multiple matches, the command fails.

#### Cloudflare / login

If pages return a Cloudflare challenge or you need to be logged in, use cookies (Playwright export format) and `auto` fetcher:

```bash
python -m bt.cli download "COURSE_URL" --cookies-json /path/to/cookies.json --fetcher auto
```

#### Download options

- `--fail-fast` — stop on first lesson where transcript text cannot be extracted
- `--fetcher playwright` — always use a real browser (slower, more reliable on some sites)
- `--headless` — run Playwright headless (default is headed)

### `paragraph` — Gemini paragraphing (transcript only)

Uses **`GEMINI_API_KEY`**. The CLI loads a **`.env`** file in the **current working directory** (via `python-dotenv`) when the variable is not already set; behavior matches **`paragraph-outline`** below. Run from the project directory (or wherever `transcripts/` and `.env` live):

```bash
# One lesson (default: paragraph/<model>/<slug>.lessonNN.paragraph.md)
python -m bt.cli paragraph nt203-greek-tools-for-bible-study --lesson 3

python -m bt.cli paragraph nt203 --lesson 3

# All lessons (one Gemini request per lesson; one file: paragraph/<model>/<slug>.paragraph.md)
python -m bt.cli paragraph nt203-greek-tools-for-bible-study

# Multiple courses (default paths per slug; do not use --transcript or --out)
python -m bt.cli paragraph nt203 nt201
```

Reads **`transcripts/<course-slug>.md`**, extracts the lesson body (for **`--lesson`** only, or every `# Lesson N:` section when **`--lesson`** is omitted), and calls Gemini **without** the course outline (one request per lesson). The system prompt asks the model to paragraph the transcript without changing wording and not to add headings for paragraphs; the tool then prepends each lesson title as **`##`** (from the transcript’s `# Lesson N:` line) and wraps the file with the course **`#`** title and table of contents (same outer layout as `paragraph-outline`).

### `paragraph-outline` — Gemini outline-paragraphing

The legacy alias **`paragraph-lesson`** runs the same command.

Uses **`GEMINI_API_KEY`**. The CLI loads a **`.env`** file in the **current working directory** (via `python-dotenv`) if the variable is not already set in your environment. Keep your key in `.env` (already ignored by git):

```bash
# .env (one line, no quotes unless the value needs them)
GEMINI_API_KEY=your_key_here
```

**Shell options** (if you prefer not to use `.env`):

- **One-off:** `export GEMINI_API_KEY=your_key_here` then run the command in the same terminal session.
- **Load `.env` in the shell** (zsh/bash): `set -a && source .env && set +a` (requires `KEY=value` lines in `.env`).

Run from the project directory (or wherever `transcripts/`, `outlines/`, and `.env` live). For **`paragraph-outline`** specifically you also need **`outlines/`**:

```bash
# One lesson (default: paragraph-outlined/<model>/<slug>.lessonNN.paragraph-outlined.md)
python -m bt.cli paragraph-outline nt203-greek-tools-for-bible-study --lesson 3

# All lessons (one Gemini request per lesson; one file: paragraph-outlined/<model>/<slug>.paragraph-outlined.md)
python -m bt.cli paragraph-outline nt203-greek-tools-for-bible-study

# Slug-prefix also works (must be unambiguous):
python -m bt.cli paragraph-outline nt203 --lesson 3

# Multiple courses (default paths per slug; do not use --transcript, --outline, or --out)
python -m bt.cli paragraph-outline nt203 nt201
```

Reads **`transcripts/<course-slug>.md`** and **`outlines/<course-slug>.outline.md`**, pulls the **transcript body** and **outline section** for each lesson (or only the one given by `--lesson`), then calls Gemini. The system instructions (see `src/bt/lesson_paragraph.py`) tell the model to paragraph the lesson, keep wording, inline the outline as headings, avoid duplicating the lesson title, use **`###`** for the top outline level, and not use **`#`** / **`##`** in the model output. The user message includes the transcription and outline text.

The lesson title in the output file is written as **heading 2** (`##`); the tool normalizes heading depth so the shallowest heading in the model body is **`###`**.

**Output:** **Markdown** (`.md`). The file starts with the **course title** as **heading 1** (`#`), taken from the first non-lesson `# …` line in the transcript (or a title derived from the slug if missing), then **`## Table of contents`** with links to each lesson, then a horizontal rule and the lesson bodies. Lesson headings are Markdown `## …`; ToC links use slugs computed the same way as typical GitHub-style heading ids.

Default paths: with **`--lesson`**, **`paragraph-outlined/<model>/<slug>.lessonNN.paragraph-outlined.md`**; without **`--lesson`**, **`paragraph-outlined/<model>/<slug>.paragraph-outlined.md`**. Here ``<model>`` is the Gemini model id, sanitized for the filesystem. Each lesson uses one Gemini request. Each lesson block corresponds to `## Lesson N: …` from the transcript (promoted from `# Lesson N: …`), then the outline-paragraph body.

Use **`--out path`** to override the output file for a **single** course (paths **without** an extension get **`.md`** appended). With **multiple** courses, omit **`--out`** (and omit **`--transcript`** / **`--outline`**). Override inputs with **`--transcript`** / **`--outline`**, **model** with **`--model`** (default **`gemini-3.1-flash-lite-preview`**). If any lesson fails (missing transcript or outline, or a Gemini error), the command exits non-zero after processing the rest; the combined file omits failed lessons.

## How it works

1. **`download`:** Fetches the **course** page and collects lesson links. Resolves the class outline from embedded JSON or JSON:API; if that fails, the command stops (exit code **4**) before downloading lesson transcripts.
2. Fetches each lesson page and extracts the **Transcription** section as plain text.
3. Writes transcript Markdown under **`transcripts/`**, outline under **`outlines/`**, with the **class title** (from the course page), a **table of contents**, then `# Lesson {n}: {title}` per lesson.

## Output layout

| Kind | Default path |
|------|----------------|
| Course transcript | `transcripts/<course-slug>.md` |
| Course outline | `outlines/<course-slug>.outline.md` |
| Paragraph lesson (Gemini, transcript only, `--lesson`) | `paragraph/<model>/<course-slug>.lessonNN.paragraph.md` |
| Paragraph course (Gemini, transcript only, all lessons) | `paragraph/<model>/<course-slug>.paragraph.md` |
| Outline-paragraph lesson (Gemini, `--lesson`) | `paragraph-outlined/<model>/<course-slug>.lessonNN.paragraph-outlined.md` |
| Outline-paragraph course (Gemini, all lessons) | `paragraph-outlined/<model>/<course-slug>.paragraph-outlined.md` |

## Notes

- Respect BiblicalTraining’s terms of use; this tool is for personal study / accessibility-style copies of publicly available transcripts.
- Some lessons may use different page layouts; if extraction fails, try `--fetcher playwright` or provide cookies.
