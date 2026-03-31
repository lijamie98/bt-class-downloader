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

**Required:** subcommand `download` and the course URL.

```bash
python -m bt.cli download \
  "https://www.biblicaltraining.org/learn/institute/nt201-biblical-greek"
```

Default output: `transcripts/<course-slug>.md` (e.g. `transcripts/nt201-biblical-greek.md`).

The tool always writes `transcripts/<course-slug>.outline.md` (same slug as the transcript file). The file starts with the class title as `# …`, then each lesson is `## Lesson {n}: {lesson title}` with Markdown bullet outlines (HTML stripped). Embedded `__NEXT_DATA__` is used when present; otherwise lesson outlines come from JSON:API (`include=field_lessons`). If no outline can be obtained, **`download` exits with code 4** before any lesson pages are fetched.

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

## How it works

1. **`download`:** Fetches the **course** page and collects lesson links. Resolves the class outline from embedded JSON or JSON:API; if that fails, the command stops (exit code **4**) before downloading lesson transcripts.
2. Fetches each lesson page and extracts the **Transcription** section as plain text.
3. Writes one Markdown file with the **class title** (from the course page), a **table of contents**, then `# Lesson {n}: {title}` per lesson.

## Notes

- Respect BiblicalTraining’s terms of use; this tool is for personal study / accessibility-style copies of publicly available transcripts.
- Some lessons may use different page layouts; if extraction fails, try `--fetcher playwright` or provide cookies.
