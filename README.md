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
- For **`outline`**: a [Google AI](https://aistudio.google.com/apikey) API key in **`GEMINI_API_KEY`**

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

**Required:** subcommand `download` and the course URL.

```bash
python -m bt.cli download \
  "https://www.biblicaltraining.org/learn/institute/nt201-biblical-greek"
```

Default output: `transcripts/<course-slug>.md` (e.g. `transcripts/nt201-biblical-greek.md`).

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

#### Cloudflare / login

If pages return a Cloudflare challenge or you need to be logged in, use cookies (Playwright export format) and `auto` fetcher:

```bash
python -m bt.cli download "COURSE_URL" --cookies-json /path/to/cookies.json --fetcher auto
```

#### Download options

- `--fail-fast` — stop on first lesson where transcript text cannot be extracted
- `--fetcher playwright` — always use a real browser (slower, more reliable on some sites)
- `--headless` — run Playwright headless (default is headed)

### `outline` — Gemini outlines + paragraph breaks

Enrich a **downloader** Markdown file: for each `# Lesson N: …` section, call **Google Gemini** with your transcript and insert a **two-layer outline** (`##` / `###`) directly under that heading, then the **paragraphed** transcript (wording preserved). There is no separate `## Outline` section. Set **`GEMINI_API_KEY`** in the environment (or pass **`--api-key`** once).

```bash
export GEMINI_API_KEY="your-key"
python -m bt.cli outline transcripts/nt201-biblical-greek.md
```

- **Default output:** `transcripts/nt201-biblical-greek.outlined.md` (same directory, `*.outlined.md` beside the input).
- **`--out PATH`** — write to a specific file.
- **`--in-place`** — overwrite the input file.
- **`--model`** — Gemini model id (default: `gemini-3-flash-preview`).
- **`--sleep-seconds`** — delay between lesson API calls (default: `1.0`).

## How it works

1. **`download`:** Fetches the **course** page and collects links whose path is exactly one segment under the course path (each **lesson** page).
2. Fetches each lesson page and extracts the **Transcription** section as plain text.
3. Writes one Markdown file with the **class title** (from the course page), a **table of contents**, then `# Lesson {n}: {title}` per lesson.
4. **`outline`:** Parses that Markdown, calls Gemini per lesson, and writes a new file with the outline (`##` / `###`) and paragraphed transcript under each `# Lesson` heading (no duplicate lesson heading, no `## Outline` wrapper).

## Notes

- Respect BiblicalTraining’s terms of use; this tool is for personal study / accessibility-style copies of publicly available transcripts.
- Some lessons may use different page layouts; if extraction fails, try `--fetcher playwright` or provide cookies.
- **`outline`** expects the standard downloader format (`# Lesson N:` headings). Re-running on an already outlined file may duplicate outlines; use the original transcript or edit manually.
