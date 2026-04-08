# bt-class-downloader

**Languages / 語言 / 语言:** **English** · [繁體中文](README.zh-TW.md) · [简体中文](README.zh-CN.md)

---

Download **lesson transcription** text from [BiblicalTraining.org](https://www.biblicaltraining.org/) for **any class**, given either a **course overview URL** or an unambiguous **slug-prefix** resolved through the local course index (see **`download`** below).

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

Run the tool with **`python -m bt`** (the package’s `__main__`). After install, the **`bt`** command is also on your `PATH` (same as **`biblicaltraining-transcripts`**).

## Examples

Run from the project directory (or wherever **`courses/`** and **`.env`** live). **`GEMINI_API_KEY`** is required for **`paragraph`**, **`paragraph-outline`**, **`study-note-zh`**, **`study-note-cn`**, **`translate-zh`**, and **`translate-cn`** (see **`paragraph-outline`** below for **`.env`**).

### `download`

The course index is fetched on the first CLI run if it is missing. A **slug-prefix** must match exactly one course in the index.

```bash
python -m bt download nt201
# or: bt download nt201
```

Writes **`courses/<slug>/<slug>.md`** (transcript) and **`courses/<slug>/<slug>.outline.md`** (outline; exact paths depend on the resolved slug, e.g. `nt201-biblical-greek`).

```bash
python -m bt download "https://www.biblicaltraining.org/learn/institute/nt201-biblical-greek"

# Multiple courses (do not use --out):
python -m bt download nt201 nt203
```

### `paragraph`

Transcript only (no outline). Uses Gemini; one request per lesson.

```bash
python -m bt paragraph nt203 --lesson 3

# All lessons in one file:
python -m bt paragraph nt203

python -m bt paragraph nt203 nt201
```

### `study-note` (`study-note-zh` / `study-note-cn`)

Uses the same transcript + outline files as **`paragraph-outline`**. **`study-note-zh`** is Traditional Chinese; **`study-note-cn`** is Simplified Chinese. The commands **`explain-zh`** and **`explain-cn`** remain as deprecated aliases.

```bash
python -m bt study-note-zh nt203 --lesson 1
python -m bt study-note-zh nt203

python -m bt study-note-cn nt203 --lesson 1
python -m bt study-note-cn nt203
```

### `translate` (`translate-zh` / `translate-cn`)

Reads English Markdown from **`courses/<slug>/paragraph/<model>/…`** (output of **`paragraph`**). **`translate-zh`** → **`courses/<slug>/translate-zh/…`**; **`translate-cn`** → **`courses/<slug>/translate-cn/…`**. Without **`--lesson`**, the combined **`…/<slug>.paragraph.md`** is used and **each lesson** is translated in its **own** Gemini request; the **course title** uses a **separate** request. With **`--lesson`**, the default input is **`…/<slug>.lessonNN.paragraph.md`**, or that lesson is sliced from the combined file if the per-lesson file is missing. Optional **`--paragraph`** overrides the input path (single course only).

```bash
python -m bt translate-zh nt310
python -m bt translate-cn nt310

python -m bt translate-zh nt310 --lesson 1
```

## Which course identifier to use

**`download`** needs the **course overview** page: a URL whose path ends at the **course slug** (for example `…/learn/<segment>/<course-slug>`), so the HTML contains links to each lesson under that path. The tool does not look for specific headings or labels on the page.

Do **not** pass a **single-lesson** URL as the course URL (paths with an extra segment after the course slug). Those pages are not used to enumerate all lessons.

**Overview URL examples:**

- `https://www.biblicaltraining.org/learn/institute/nt201-biblical-greek`
- `https://www.biblicaltraining.org/learn/institute/nt605-textual-criticism`
- `https://www.biblicaltraining.org/learn/foundations/nt101-essentials-of-the-new-testament`

**Or** pass a **slug-prefix** instead of a URL (for example `nt201`), as long as it matches exactly one course in the index—same rules as in the **`download`** section and **Course index** below.

## Commands

### `download` — fetch transcripts

**Required:** the `download` subcommand and one or more course identifiers (each a URL or slug-prefix from the index).

```bash
python -m bt download \
  "https://www.biblicaltraining.org/learn/institute/nt201-biblical-greek"

# Or use a slug-prefix from the local course index:
python -m bt download nt201

# Multiple courses (each writes courses/<slug>/<slug>.md; do not use --out):
python -m bt download nt201 nt203
```

Default output: `courses/<course-slug>/<course-slug>.md` (e.g. `courses/nt201-biblical-greek/nt201-biblical-greek.md`).

The tool always writes the class outline to **`courses/<course-slug>/<course-slug>.outline.md`** (same directory as the transcript). The file starts with the class title as `# …`, then each lesson is `## Lesson {n}: {lesson title}` with Markdown bullet outlines (HTML stripped). Embedded `__NEXT_DATA__` is used when present; otherwise lesson outlines come from JSON:API (`include=field_lessons`). If no outline can be obtained, **`download` exits with code 4** before any lesson pages are fetched.

Custom transcript path (single course only; not available when downloading multiple courses):

```bash
python -m bt download \
  "https://www.biblicaltraining.org/learn/institute/nt605-textual-criticism" \
  --out courses/nt605-textual-criticism/nt605-textual-criticism.md
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
python -m bt refresh-index
```

You can inspect the cached index:

```bash
python -m bt list-index --limit 25
python -m bt search-index nt201
```

Slug-prefix lookups (like `nt201`) must match **exactly one** course slug; if there are 0 matches or multiple matches, the command fails.

#### Cloudflare / login

If pages return a Cloudflare challenge or you need to be logged in, use cookies (Playwright export format) and `auto` fetcher:

```bash
python -m bt download "COURSE_URL" --cookies-json /path/to/cookies.json --fetcher auto
```

#### Download options

- `--fail-fast` — stop on first lesson where transcript text cannot be extracted
- `--fetcher playwright` — always use a real browser (slower, more reliable on some sites)
- `--headless` — run Playwright headless (default is headed)

### `paragraph` — Gemini paragraphing (transcript only)

Uses **`GEMINI_API_KEY`**. The CLI loads a **`.env`** file in the **current working directory** (via `python-dotenv`) when the variable is not already set; behavior matches **`paragraph-outline`** below. Run from the project directory (or wherever `courses/` and `.env` live):

```bash
# One lesson (default: courses/<slug>/paragraph/<model>/<slug>.lessonNN.paragraph.md)
python -m bt paragraph nt203-greek-tools-for-bible-study --lesson 3

python -m bt paragraph nt203 --lesson 3

# All lessons (one Gemini request per lesson; one file: courses/<slug>/paragraph/<model>/<slug>.paragraph.md)
python -m bt paragraph nt203-greek-tools-for-bible-study

# Multiple courses (default paths per slug; do not use --transcript or --out)
python -m bt paragraph nt203 nt201
```

Reads **`courses/<course-slug>/<course-slug>.md`**, extracts the lesson body (for **`--lesson`** only, or every `# Lesson N:` section when **`--lesson`** is omitted), and calls Gemini **without** the course outline (one request per lesson). The system prompt asks the model to paragraph the transcript without changing wording and not to add headings for paragraphs; the tool then prepends each lesson title as **`##`** (from the transcript’s `# Lesson N:` line) and wraps the file with the course **`#`** title and a **Table of contents** that links to **every** `##`–`######` heading in the document (nested by depth), same outer layout as `paragraph-outline`.

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

Run from the project directory (or wherever `courses/` and `.env` live). For **`paragraph-outline`** you need the transcript and outline files next to each other under **`courses/<slug>/`**:

```bash
# One lesson (default: courses/<slug>/paragraph-outlined/<model>/<slug>.lessonNN.paragraph-outlined.md)
python -m bt paragraph-outline nt203-greek-tools-for-bible-study --lesson 3

# All lessons (one Gemini request per lesson; one file: courses/<slug>/paragraph-outlined/<model>/<slug>.paragraph-outlined.md)
python -m bt paragraph-outline nt203-greek-tools-for-bible-study

# Slug-prefix also works (must be unambiguous):
python -m bt paragraph-outline nt203 --lesson 3

# Multiple courses (default paths per slug; do not use --transcript, --outline, or --out)
python -m bt paragraph-outline nt203 nt201
```

Reads **`courses/<course-slug>/<course-slug>.md`** and **`courses/<course-slug>/<course-slug>.outline.md`**, pulls the **transcript body** and **outline section** for each lesson (or only the one given by `--lesson`), then calls Gemini. The system instructions (see `src/bt/lesson_paragraph.py`) tell the model to paragraph the lesson, keep wording, inline the outline as headings, avoid duplicating the lesson title, use **`###`** for the top outline level, and not use **`#`** / **`##`** in the model output. The user message includes the transcription and outline text.

The lesson title in the output file is written as **heading 2** (`##`); the tool normalizes heading depth so the shallowest heading in the model body is **`###`**.

**Output:** **Markdown** (`.md`). The file starts with the **course title** as **heading 1** (`#`), taken from the first non-lesson `# …` line in the transcript (or a title derived from the slug if missing), then **`## Table of contents`** with nested links to **every** `##`–`######` heading in the combined document (not only lesson titles), then a horizontal rule and the bodies. Link targets use GitHub-style heading ids, with numeric suffixes when the same heading text repeats.

Default paths: with **`--lesson`**, **`courses/<slug>/paragraph-outlined/<model>/<slug>.lessonNN.paragraph-outlined.md`**; without **`--lesson`**, **`courses/<slug>/paragraph-outlined/<model>/<slug>.paragraph-outlined.md`**. Here ``<model>`` is the Gemini model id, sanitized for the filesystem. Each lesson uses one Gemini request. Each lesson block corresponds to `## Lesson N: …` from the transcript (promoted from `# Lesson N: …`), then the outline-paragraph body.

Use **`--out path`** to override the output file for a **single** course (paths **without** an extension get **`.md`** appended). With **multiple** courses, omit **`--out`** (and omit **`--transcript`** / **`--outline`**). Override inputs with **`--transcript`** / **`--outline`**, **model** with **`--model`** (default **`gemini-3.1-flash-lite-preview`**). If any lesson fails (missing transcript or outline, or a Gemini error), the command exits non-zero after processing the rest; the combined file omits failed lessons.

**`study-note-zh`** (Traditional Chinese) and **`study-note-cn`** (Simplified Chinese) use the same transcript + outline inputs as **`paragraph-outline`** and **`GEMINI_API_KEY`**, but produce study-guide Markdown under **`courses/<slug>/study-note-zh/…`** or **`courses/<slug>/study-note-cn/…`** (see **Output layout**). The model emits a short outline-alignment blockquote and an HTML comment (`study-note-zh-h2` / `study-note-cn-h2`; legacy `explain-zh-h2` / `explain-cn-h2` are still accepted) for a bilingual **`##`** lesson line; prompts favor **Reformed-theology** wording for Bible terms in Chinese. Example: `python -m bt study-note-cn nt203 --lesson 1`.

## How it works

1. **`download`:** Fetches the **course** page and collects lesson links. Resolves the class outline from embedded JSON or JSON:API; if that fails, the command stops (exit code **4**) before downloading lesson transcripts.
2. Fetches each lesson page and extracts the **Transcription** section as plain text.
3. Writes transcript Markdown and outline under **`courses/<course-slug>/`** (flat: `<slug>.md` and `<slug>.outline.md`), with the **class title** (from the course page), a **table of contents**, then `# Lesson {n}: {title}` per lesson.

## Output layout

All paths are under **`courses/<course-slug>/`**. Gemini outputs include a **`/<model>/`** directory segment (sanitized model id).

| Kind | Default path |
|------|----------------|
| Course transcript | `courses/<course-slug>/<course-slug>.md` |
| Course outline | `courses/<course-slug>/<course-slug>.outline.md` |
| Paragraph lesson (Gemini, transcript only, `--lesson`) | `courses/<course-slug>/paragraph/<model>/<course-slug>.lessonNN.paragraph.md` |
| Paragraph course (Gemini, transcript only, all lessons) | `courses/<course-slug>/paragraph/<model>/<course-slug>.paragraph.md` |
| Outline-paragraph lesson (Gemini, `--lesson`) | `courses/<course-slug>/paragraph-outlined/<model>/<course-slug>.lessonNN.paragraph-outlined.md` |
| Outline-paragraph course (Gemini, all lessons) | `courses/<course-slug>/paragraph-outlined/<model>/<course-slug>.paragraph-outlined.md` |
| Chinese study-note lesson, Traditional (`study-note-zh`, `--lesson`) | `courses/<course-slug>/study-note-zh/<model>/<course-slug>.lessonNN.zh.md` |
| Chinese study-note course, Traditional (`study-note-zh`, all lessons) | `courses/<course-slug>/study-note-zh/<model>/<course-slug>.zh.md` |
| Chinese study-note lesson, Simplified (`study-note-cn`, `--lesson`) | `courses/<course-slug>/study-note-cn/<model>/<course-slug>.lessonNN.cn.md` |
| Chinese study-note course, Simplified (`study-note-cn`, all lessons) | `courses/<course-slug>/study-note-cn/<model>/<course-slug>.cn.md` |
| Chinese translation lesson, Traditional (`translate-zh`, `--lesson`) | `courses/<course-slug>/translate-zh/<model>/<course-slug>.lessonNN.zh.md` |
| Chinese translation course, Traditional (`translate-zh`, all lessons) | `courses/<course-slug>/translate-zh/<model>/<course-slug>.zh.md` |
| Chinese translation lesson, Simplified (`translate-cn`, `--lesson`) | `courses/<course-slug>/translate-cn/<model>/<course-slug>.lessonNN.cn.md` |
| Chinese translation course, Simplified (`translate-cn`, all lessons) | `courses/<course-slug>/translate-cn/<model>/<course-slug>.cn.md` |

### Migrating from `data/`

If you have an older tree under **`data/transcripts/`**, **`data/outlines/`**, and **`data/<command>/<model>/…`**, move files into the layout above, for example:

- `data/transcripts/<slug>.md` → `courses/<slug>/<slug>.md`
- `data/outlines/<slug>.outline.md` → `courses/<slug>/<slug>.outline.md`
- `data/paragraph/<model>/…` → `courses/<slug>/paragraph/<model>/…` (same filenames), and similarly for `paragraph-outlined`, `study-note-zh`, `study-note-cn`, `translate-zh`, `translate-cn` (older trees may use `explain-zh` / `explain-cn` directories—rename those to `study-note-zh` / `study-note-cn` to match current defaults).

## Notes

- Respect BiblicalTraining’s terms of use; this tool is for personal study / accessibility-style copies of publicly available transcripts.
- Some lessons may use different page layouts; if extraction fails, try `--fetcher playwright` or provide cookies.
- The installable Python distribution is named **`biblicaltraining-class-transcripts`** on PyPI; the repository folder is often **`bt-class-downloader`**. The CLI module is **`bt`** (`python -m bt`, console scripts **`bt`** and **`biblicaltraining-transcripts`**).
