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

    lessons: list[Lesson] = []
    seen_urls: set[str] = set()

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
        if full_url in seen_urls:
            continue
        seen_urls.add(full_url)

        raw_text = a.get_text(" ", strip=True)
        m2 = re.match(r"^\s*(\d+)\.\s*(.+?)\s*$", raw_text)
        if m2:
            order = int(m2.group(1))
            title = m2.group(2).strip()
        else:
            order = _order_from_lesson_slug(suffix)
            title = raw_text or suffix.replace("-", " ").title()

        lessons.append(Lesson(order=order, title=title, url=full_url))

    lessons.sort(key=lambda x: (x.order, x.title))
    return lessons


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


def write_markdown(lessons: Iterable[Lesson], transcripts: dict[str, str], outpath: str) -> None:
    _ensure_dir(outpath)
    with open(outpath, "w", encoding="utf-8") as f:
        for lesson in lessons:
            f.write(f"# Lesson {lesson.order}: {lesson.title}\n\n")
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
                write_markdown(lessons, transcripts, outpath)
                return 2

        time.sleep(max(0.0, args.sleep_seconds))

    write_markdown(lessons, transcripts, outpath)
    iter_progress(f"Wrote: {outpath}")
    if failures:
        iter_progress(f"Failed transcripts: {len(failures)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
