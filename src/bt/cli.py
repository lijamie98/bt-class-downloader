"""
Download lesson transcription text for any BiblicalTraining.org class given the class (course) URL.

Course URLs look like:
  https://www.biblicaltraining.org/learn/institute/nt201-biblical-greek
  https://www.biblicaltraining.org/learn/foundations/nt101-essentials-of-the-new-testament
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from typing import Iterable, Optional
from urllib.parse import urlparse, urlunparse

import requests
from bs4 import BeautifulSoup


@dataclass(frozen=True)
class Lesson:
    order: int
    title: str
    url: str


def normalize_course_url(url: str) -> str:
    """Return canonical https URL with path (no trailing slash except root)."""
    u = url.strip()
    if not u:
        raise ValueError("Empty course URL")
    if not re.match(r"^https?://", u, re.I):
        u = "https://" + u
    p = urlparse(u)
    if not p.netloc:
        raise ValueError(f"Invalid URL: {url!r}")
    path = (p.path or "/").rstrip("/")
    if not path:
        path = ""
    return urlunparse((p.scheme or "https", p.netloc, path, "", "", ""))


def default_output_path(course_url: str) -> str:
    slug = urlparse(course_url).path.rstrip("/").split("/")[-1] or "class"
    safe = re.sub(r"[^\w.-]+", "-", slug).strip("-") or "transcripts"
    return os.path.join("transcripts", f"{safe}.md")


def _is_cloudflare_challenge(html: str) -> bool:
    h = html.lower()
    return "just a moment" in h or "cf-browser-verification" in h or "cloudflare" in h


def _ensure_dir(path: str) -> None:
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)


def _fetch_html_requests(url: str, cookies_json: Optional[str], timeout_s: int) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    sess = requests.Session()
    if cookies_json:
        cookies = json.loads(open(cookies_json, "r", encoding="utf-8").read())
        for c in cookies:
            name = c.get("name")
            value = c.get("value")
            domain = c.get("domain")
            path = c.get("path", "/")
            if name and value and domain:
                sess.cookies.set(name=name, value=value, domain=domain, path=path)

    r = sess.get(url, headers=headers, timeout=timeout_s)
    r.raise_for_status()
    return r.text


def _fetch_html_playwright(url: str, cookies_json: Optional[str], timeout_ms: int, headless: bool) -> str:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:  # pragma: no cover
        raise RuntimeError("playwright not available. Install deps with pip.") from e

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            )
        )

        if cookies_json:
            cookies = json.loads(open(cookies_json, "r", encoding="utf-8").read())
            context.add_cookies(cookies)

        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        page.wait_for_timeout(4000)
        html = page.content()
        context.close()
        browser.close()
        return html


def fetch_html(
    url: str,
    *,
    cookies_json: Optional[str],
    timeout_s: int,
    fetcher: str,
    playwright_timeout_ms: int,
    headless: bool,
) -> str:
    fetcher = fetcher.lower()
    if fetcher not in {"requests", "playwright", "auto"}:
        raise ValueError("fetcher must be one of: requests, playwright, auto")

    if fetcher == "playwright":
        return _fetch_html_playwright(
            url,
            cookies_json=cookies_json,
            timeout_ms=playwright_timeout_ms,
            headless=headless,
        )

    try:
        html = _fetch_html_requests(url, cookies_json=cookies_json, timeout_s=timeout_s)
    except Exception:
        if fetcher == "requests":
            raise
        return _fetch_html_playwright(
            url,
            cookies_json=cookies_json,
            timeout_ms=playwright_timeout_ms,
            headless=headless,
        )

    if fetcher == "requests":
        return html

    if _is_cloudflare_challenge(html):
        return _fetch_html_playwright(
            url,
            cookies_json=cookies_json,
            timeout_ms=playwright_timeout_ms,
            headless=headless,
        )
    return html


def _order_from_lesson_slug(slug: str) -> int:
    """Infer lesson order from URL path segment (e.g. nt605-01-foo -> 1)."""
    m = re.match(r"^[a-z0-9]+-(\d+)-", slug, re.I)
    if m:
        return int(m.group(1))
    m = re.search(r"-(\d+)(?:-|$)", slug)
    if m:
        return int(m.group(1))
    return 9999


# Course pages often link the same lesson twice (e.g. hero "Attend this class" + lesson list
# "1. Title"). Prefer the numbered lesson title over generic CTAs.
_GENERIC_LESSON_LINK_LABELS = frozenset(
    {
        "attend this class",
        "attending the class",
        "attend the class",
        "take this class",
        "start class",
        "watch now",
        "watch lesson",
    }
)


def _lesson_link_text_priority(raw_text: str) -> tuple[int, int]:
    """Higher tuple sorts later; prefer '1. Lesson title' over marketing link text."""
    t = (raw_text or "").strip()
    if not t:
        return (-1, 0)
    if re.match(r"^\s*\d+\.\s+", t):
        return (2, len(t))
    if t.lower() in _GENERIC_LESSON_LINK_LABELS:
        return (0, 0)
    return (1, len(t))


def _lesson_from_link(raw_text: str, suffix: str, full_url: str) -> Lesson:
    m2 = re.match(r"^\s*(\d+)\.\s*(.+?)\s*$", raw_text)
    if m2:
        order = int(m2.group(1))
        title = m2.group(2).strip()
    else:
        order = _order_from_lesson_slug(suffix)
        title = raw_text.strip() or suffix.replace("-", " ").title()
    return Lesson(order=order, title=title, url=full_url)


def parse_lessons_from_course_html(html: str, course_url: str) -> list[Lesson]:
    """
    Find lesson links: same host, path must be /{course_path}/{lesson_slug}
    with exactly one extra path segment after the course page.
    """
    soup = BeautifulSoup(html, "lxml")
    parsed = urlparse(course_url)
    course_path = (parsed.path or "/").rstrip("/")
    if not course_path:
        course_path = "/"
    origin = f"{parsed.scheme}://{parsed.netloc}"

    # Same lesson URL can appear multiple times (hero CTA vs lesson list). Keep best title.
    best: dict[str, tuple[Lesson, tuple[int, int]]] = {}

    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").split("#", 1)[0].split("?", 1)[0].strip()
        if not href:
            continue

        if href.startswith("http://") or href.startswith("https://"):
            hp = urlparse(href)
            if hp.netloc != parsed.netloc:
                continue
            path = (hp.path or "").rstrip("/")
        else:
            path = href if href.startswith("/") else "/" + href
            path = path.rstrip("/")

        if not path.startswith(course_path + "/"):
            continue

        suffix = path[len(course_path) + 1 :]
        if not suffix or "/" in suffix:
            continue

        full_url = f"{origin}{path}"
        raw_text = a.get_text(" ", strip=True)
        pri = _lesson_link_text_priority(raw_text)
        lesson = _lesson_from_link(raw_text, suffix, full_url)
        prev = best.get(full_url)
        if prev is None or pri > prev[1]:
            best[full_url] = (lesson, pri)

    lessons = [pair[0] for pair in best.values()]
    lessons.sort(key=lambda x: (x.order, x.title))
    return lessons


def parse_course_title_from_course_html(html: str) -> Optional[str]:
    """Class display name from the course overview page (primary: first main heading)."""
    soup = BeautifulSoup(html, "lxml")
    h1 = soup.find("h1")
    if h1:
        t = h1.get_text(" ", strip=True)
        if t:
            return t
    if soup.title and soup.title.string:
        raw = soup.title.string.strip()
        if raw and "just a moment" not in raw.lower():
            # "Title - Professor | Site" -> title only
            if " - " in raw:
                raw = raw.split(" - ", 1)[0].strip()
            return raw or None
    return None


def extract_transcription_from_lesson_html(html: str) -> Optional[str]:
    """
    Extract transcript after a 'Transcription' marker until lesson nav (markdown links) or section headings.
    """
    soup = BeautifulSoup(html, "lxml")
    full_text = soup.get_text("\n", strip=True)
    lines = [ln.strip() for ln in full_text.splitlines() if ln.strip()]

    nav_link_md_re = re.compile(r"^\[\d+\.\s*.+\]\(https?://")
    end_section_re = re.compile(
        r"^(##\s+(Lessons|Class Resources|Links)\b|##\s+About\b)", re.IGNORECASE
    )

    start_idx: Optional[int] = None
    for i, ln in enumerate(lines):
        if ln.lower() == "transcription":
            start_idx = i
            break
    if start_idx is None:
        return None

    i = start_idx + 1
    while i < len(lines) and lines[i].lower() in {"transcription", "lessons"}:
        i += 1

    if i >= len(lines):
        return None

    end_idx = len(lines)
    for j in range(i, len(lines)):
        ln = lines[j]
        if nav_link_md_re.match(ln) or end_section_re.match(ln) or ln.lower().startswith("class resources"):
            end_idx = j
            break

    transcript_lines = lines[i:end_idx]
    transcript = "\n".join(transcript_lines).strip()
    return transcript or None


def iter_progress(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _gfm_heading_anchor(heading_plain: str) -> str:
    """Slug for GitHub-style heading anchors (ASCII titles)."""
    s = heading_plain.strip().lower()
    parts: list[str] = []
    prev_hyphen = True
    for ch in s:
        if ch.isalnum():
            parts.append(ch)
            prev_hyphen = False
        elif ch in " \t\n\r-_":
            if not prev_hyphen and parts:
                parts.append("-")
                prev_hyphen = True
    anchor = "".join(parts).strip("-")
    anchor = re.sub(r"-+", "-", anchor)
    return anchor


def _lesson_heading_plain(lesson: Lesson) -> str:
    return f"Lesson {lesson.order}: {lesson.title}"


def _assign_heading_anchors(lessons: list[Lesson]) -> list[tuple[Lesson, str]]:
    """Return each lesson with a unique GFM-style anchor for its H1."""
    counts: dict[str, int] = {}
    out: list[tuple[Lesson, str]] = []
    for lesson in lessons:
        base = _gfm_heading_anchor(_lesson_heading_plain(lesson))
        if not base:
            base = f"lesson-{lesson.order}"
        n = counts.get(base, 0)
        # Match GitHub slugger: foo, foo-1, foo-2, ...
        anchor = base if n == 0 else f"{base}-{n}"
        counts[base] = n + 1
        out.append((lesson, anchor))
    return out


def write_markdown(
    lessons: Iterable[Lesson],
    transcripts: dict[str, str],
    outpath: str,
    *,
    course_title: Optional[str] = None,
) -> None:
    _ensure_dir(outpath)
    lesson_list = list(lessons)
    with_anchors = _assign_heading_anchors(lesson_list)
    with open(outpath, "w", encoding="utf-8") as f:
        if course_title:
            f.write(f"# {course_title}\n\n")
            toc_heading = "## Table of contents"
        else:
            toc_heading = "# Table of contents"
        f.write(f"{toc_heading}\n\n")
        for lesson, anchor in with_anchors:
            line = _lesson_heading_plain(lesson)
            f.write(f"- [{line}](#{anchor})\n")
        f.write("\n---\n\n")

        for lesson, _anchor in with_anchors:
            f.write(f"# {_lesson_heading_plain(lesson)}\n\n")
            text = transcripts.get(lesson.url, "").strip()
            if not text:
                text = "[Transcript not found or extraction failed.]\n"
            f.write(text)
            if not text.endswith("\n"):
                f.write("\n")
            f.write("\n\n")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download lesson transcriptions for a BiblicalTraining.org class (course URL)."
    )
    parser.add_argument(
        "course_url",
        help="Class/course page URL, e.g. https://www.biblicaltraining.org/learn/institute/nt201-biblical-greek",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Output Markdown file (default: transcripts/<course-slug>.md)",
    )
    parser.add_argument("--cookies-json", default=None, help="Optional Playwright-format cookies JSON.")
    parser.add_argument(
        "--fetcher",
        default="auto",
        choices=["auto", "requests", "playwright"],
        help="How to fetch pages (auto falls back to Playwright on Cloudflare).",
    )
    parser.add_argument("--timeout-s", type=int, default=30)
    parser.add_argument("--playwright-timeout-ms", type=int, default=60000)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--sleep-seconds", type=float, default=1.2)
    parser.add_argument("--fail-fast", action="store_true")
    args = parser.parse_args()

    try:
        course_url = normalize_course_url(args.course_url)
    except ValueError as e:
        iter_progress(f"Error: {e}")
        return 2

    outpath = args.out or default_output_path(course_url)
    headless = bool(args.headless)

    iter_progress(f"Course URL: {course_url}")
    course_html = fetch_html(
        course_url,
        cookies_json=args.cookies_json,
        timeout_s=args.timeout_s,
        fetcher=args.fetcher,
        playwright_timeout_ms=args.playwright_timeout_ms,
        headless=headless,
    )

    lessons = parse_lessons_from_course_html(course_html, course_url)
    if not lessons:
        iter_progress(
            "No lesson links found. Check the URL is the class overview page "
            "(not a single lesson). Example: .../learn/institute/COURSE-SLUG"
        )
        return 3

    iter_progress(f"Found {len(lessons)} lesson(s).")
    course_title = parse_course_title_from_course_html(course_html)
    if course_title:
        iter_progress(f"Class title: {course_title}")

    transcripts: dict[str, str] = {}
    failures: list[str] = []

    for idx, lesson in enumerate(lessons, start=1):
        iter_progress(f"[{idx}/{len(lessons)}] {lesson.title}")
        html = fetch_html(
            lesson.url,
            cookies_json=args.cookies_json,
            timeout_s=args.timeout_s,
            fetcher=args.fetcher,
            playwright_timeout_ms=args.playwright_timeout_ms,
            headless=headless,
        )
        transcript = extract_transcription_from_lesson_html(html)
        if transcript:
            transcripts[lesson.url] = transcript
        else:
            failures.append(lesson.url)
            iter_progress(f"  Transcript extraction failed for: {lesson.title}")
            if args.fail_fast:
                write_markdown(lessons, transcripts, outpath, course_title=course_title)
                return 2

        time.sleep(max(0.0, args.sleep_seconds))

    write_markdown(lessons, transcripts, outpath, course_title=course_title)
    iter_progress(f"Wrote: {outpath}")
    if failures:
        iter_progress(f"Failed transcripts: {len(failures)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
