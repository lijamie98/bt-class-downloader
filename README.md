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

## Run

**Required:** the course URL as the first argument.

```bash
python -m biblicaltraining.cli \
  "https://www.biblicaltraining.org/learn/institute/nt201-biblical-greek"
```

Default output: `transcripts/<course-slug>.md` (e.g. `transcripts/nt201-biblical-greek.md`).

Custom output file:

```bash
python -m biblicaltraining.cli \
  "https://www.biblicaltraining.org/learn/institute/nt605-textual-criticism" \
  --out transcripts/nt605.md
```

After install, you can also use the console script:

```bash
biblicaltraining-transcripts "https://www.biblicaltraining.org/learn/institute/nt201-biblical-greek"
```

### Cloudflare / login

If pages return a Cloudflare challenge or you need to be logged in, use cookies (Playwright export format) and `auto` fetcher:

```bash
python -m biblicaltraining.cli "COURSE_URL" --cookies-json /path/to/cookies.json --fetcher auto
```

### Options

- `--fail-fast` — stop on first lesson where transcript text cannot be extracted
- `--fetcher playwright` — always use a real browser (slower, more reliable on some sites)
- `--headless` — run Playwright headless (default is headed)

## How it works

1. Fetches the **course** page and collects links whose path is exactly one segment under the course path (each **lesson** page).
2. Fetches each lesson page and extracts the **Transcription** section as plain text.
3. Writes one Markdown file with `# Lesson {n}: {title}` per lesson.

## Notes

- Respect BiblicalTraining’s terms of use; this tool is for personal study / accessibility-style copies of publicly available transcripts.
- Some lessons may use different page layouts; if extraction fails, try `--fetcher playwright` or provide cookies.
