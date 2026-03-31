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

**Required:** subcommand `download` and the course identifier (URL or slug-prefix).

```bash
python -m bt.cli download \
  "https://www.biblicaltraining.org/learn/institute/nt201-biblical-greek"

# Or use a slug-prefix from the local course index:
python -m bt.cli download nt201
```

Default output: `transcripts/<course-slug>.md` (e.g. `transcripts/nt201-biblical-greek.md`).

The tool always writes the class outline to **`outlines/<course-slug>.outline.md`** (same basename as the transcript file). The file starts with the class title as `# …`, then each lesson is `## Lesson {n}: {lesson title}` with Markdown bullet outlines (HTML stripped). Embedded `__NEXT_DATA__` is used when present; otherwise lesson outlines come from JSON:API (`include=field_lessons`). If no outline can be obtained, **`download` exits with code 4** before any lesson pages are fetched.

Custom output file:

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

### `paragraph-outline` — Gemini outline-paragraphing

Uses **`GEMINI_API_KEY`**. The CLI loads a **`.env`** file in the **current working directory** (via `python-dotenv`) if the variable is not already set in your environment. Keep your key in `.env` (already ignored by git):

```bash
# .env (one line, no quotes unless the value needs them)
GEMINI_API_KEY=your_key_here
```

**Shell options** (if you prefer not to use `.env`):

- **One-off:** `export GEMINI_API_KEY=your_key_here` then run the command in the same terminal session.
- **Load `.env` in the shell** (zsh/bash): `set -a && source .env && set +a` (requires `KEY=value` lines in `.env`).

Run from the project directory (or wherever `transcripts/`, `outlines/`, and `.env` live):

```bash
# One lesson (default: paragraph-outlined/<model>/<slug>.lessonNN.paragraph-outlined.md)
python -m bt.cli paragraph-outline nt203-greek-tools-for-bible-study --lesson 3

# All lessons (one Gemini request per lesson by default; one file: paragraph-outlined/<model>/<slug>.paragraph-outlined.md)
python -m bt.cli paragraph-outline nt203-greek-tools-for-bible-study

# Slug-prefix also works (must be unambiguous):
python -m bt.cli paragraph-outline nt203 --lesson 3

# Batch multiple lessons per request (e.g. 3 or 10)
python -m bt.cli paragraph-outline nt203-greek-tools-for-bible-study --batch-size 3
```

Reads **`transcripts/<course-slug>.md`** and **`outlines/<course-slug>.outline.md`**, pulls the **transcript body** and **outline section** for each lesson (or only the one given by `--lesson`), then calls Gemini with:

```text
Paragraph the lesson
Do not modify the contents
Inline the outline as headings to the output.
```

(plus the lesson transcription and outline text in the same prompt.) The lesson title is written as **heading 2** (`##`); the model is instructed to start outline sections at **heading 3** (`###`), with deeper levels as `####`, `#####`, … The tool normalizes heading depth so the shallowest heading in the body is `###`.

**Output:** **Markdown** (`.md`). The file starts with the **course title** as **heading 1** (`#`), taken from the first non-lesson `# …` line in the transcript (or a title derived from the slug if missing), then **`## Table of contents`** with links to each lesson, then a horizontal rule and the lesson bodies. Lesson headings use explicit HTML `<h2 id="…">` so ToC links resolve. With **`--lesson`**, default **`paragraph-outlined/<model>/<slug>.lessonNN.paragraph-outlined.md`**; without **`--lesson`**, all successful lessons are in **`paragraph-outlined/<model>/<slug>.paragraph-outlined.md`** (``<model>`` is the Gemini model id, sanitized for the filesystem). Each lesson block corresponds to `## Lesson N: …` from the transcript (promoted from `# Lesson N: …`), then the outline-paragraph body. Use **`--out path`** to override the output file (paths **without** an extension get `.md` appended) for either mode. Override inputs with `--transcript` / `--outline`, model with `--model` (default `gemini-3.1-flash-lite-preview`, Gemini 3.1 Flash-Lite). **`--batch-size N`** (default **1**) sets how many lessons are sent in one Gemini request when paragraphing the full course (ignored with **`--lesson`**). If any lesson fails (missing transcript/outline or Gemini error), the command exits non-zero after processing the rest; the combined file omits failed lessons.

## How it works

1. **`download`:** Fetches the **course** page and collects lesson links. Resolves the class outline from embedded JSON or JSON:API; if that fails, the command stops (exit code **4**) before downloading lesson transcripts.
2. Fetches each lesson page and extracts the **Transcription** section as plain text.
3. Writes transcript Markdown under **`transcripts/`**, outline under **`outlines/`**, with the **class title** (from the course page), a **table of contents**, then `# Lesson {n}: {title}` per lesson.

## Output layout

| Kind | Default path |
|------|----------------|
| Course transcript | `transcripts/<course-slug>.md` |
| Course outline | `outlines/<course-slug>.outline.md` |
| Outline-paragraph lesson (Gemini, `--lesson`) | `paragraph-outlined/<model>/<course-slug>.lessonNN.paragraph-outlined.md` |
| Outline-paragraph course (Gemini, all lessons) | `paragraph-outlined/<model>/<course-slug>.paragraph-outlined.md` |

## Notes

- Respect BiblicalTraining’s terms of use; this tool is for personal study / accessibility-style copies of publicly available transcripts.
- Some lessons may use different page layouts; if extraction fails, try `--fetcher playwright` or provide cookies.
