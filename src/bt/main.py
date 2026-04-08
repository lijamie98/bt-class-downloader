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
from pathlib import Path
from dataclasses import dataclass, replace
from typing import Iterable, Optional
from urllib.parse import urlparse, urlunparse

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

from bt.paths import course_transcript_path
from bt.course_outline import (
    OutlineExtractionError,
    build_course_outline_markdown,
    class_jsonapi_self_href,
    default_outline_path,
    lesson_canonical_urls_by_slug,
)
from bt.course_index import (
    CourseIndexError,
    ensure_index_exists,
    index_path,
    load_index,
    resolve_course_query,
    write_fetched_index,
 )
from bt.lesson_paragraph import (
    default_study_note_cn_course_out_path,
    default_study_note_cn_out_path,
    default_study_note_zh_course_out_path,
    default_study_note_zh_out_path,
    default_paragraph_course_out_path,
    default_paragraph_out_path,
    default_plain_paragraph_course_out_path,
    default_plain_paragraph_out_path,
    default_translate_cn_course_out_path,
    default_translate_cn_out_path,
    default_translate_zh_course_out_path,
    default_translate_zh_out_path,
    extract_course_title_from_transcript,
    extract_lesson_h1_line,
    extract_lesson_outline_section,
    extract_lesson_transcript_body,
    format_chinese_study_note_markdown_file,
    format_chinese_translation_markdown_file,
    format_paragraph_markdown_file,
    format_paragraphed_document_with_toc,
    format_plain_paragraph_markdown_file,
    lesson_h2_line_from_paragraph_chunk,
    list_lesson_numbers_from_transcript,
    load_paragraph_lessons_for_translation,
    read_text,
    resolve_english_course_title_for_translation,
    resolve_transcript_outline_paths,
    run_gemini_chinese_study_note,
    run_gemini_chinese_translation,
    run_gemini_paragraph,
    run_gemini_paragraph_transcript_only,
    run_gemini_translate_course_title,
)
from bt.transcript_clean import strip_appended_lesson_catalog, strip_transcript_ui_noise


@dataclass(frozen=True)
class Lesson:
    order: int
    title: str
    url: str


def _cmd_list_index(args: argparse.Namespace) -> int:
    try:
        data = load_index()
    except OSError as e:
        iter_progress(f"Error: cannot read index at {index_path()}: {e}")
        return 2
    except Exception as e:
        iter_progress(f"Error: invalid index at {index_path()}: {e}")
        return 2

    courses = data.get("courses") or []
    if not isinstance(courses, list):
        iter_progress(f"Error: invalid index format at {index_path()}")
        return 2

    limit = max(0, int(getattr(args, "limit", 0) or 0))
    shown = 0
    for item in courses:
        if not isinstance(item, dict):
            continue
        slug = str(item.get("slug") or "").strip()
        url = str(item.get("url") or "").strip()
        title = str(item.get("title") or slug).strip()
        if not slug:
            continue
        iter_progress(f"{slug} — {title} — {url}")
        shown += 1
        if limit and shown >= limit:
            break
    iter_progress(f"Listed {shown} course(s).")
    return 0


def _cmd_search_index(args: argparse.Namespace) -> int:
    q = (getattr(args, "query", "") or "").strip().lower()
    if not q:
        iter_progress("Error: query is required.")
        return 2

    try:
        data = load_index()
    except OSError as e:
        iter_progress(f"Error: cannot read index at {index_path()}: {e}")
        return 2
    except Exception as e:
        iter_progress(f"Error: invalid index at {index_path()}: {e}")
        return 2

    courses = data.get("courses") or []
    if not isinstance(courses, list):
        iter_progress(f"Error: invalid index format at {index_path()}")
        return 2

    limit = max(1, int(getattr(args, "limit", 50) or 50))
    matches = []
    for item in courses:
        if not isinstance(item, dict):
            continue
        slug = str(item.get("slug") or "").strip()
        if slug.lower().startswith(q):
            matches.append(item)

    if not matches:
        iter_progress(f"No matches for: {q!r}")
        return 2

    shown = 0
    for item in matches:
        slug = str(item.get("slug") or "").strip()
        url = str(item.get("url") or "").strip()
        title = str(item.get("title") or slug).strip()
        iter_progress(f"{slug} — {title} — {url}")
        shown += 1
        if shown >= limit:
            break

    iter_progress(f"Matches: {len(matches)} (shown {shown}).")
    return 0


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
    return str(course_transcript_path(safe))


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


def _download_one_course(raw: str, args: argparse.Namespace) -> int:
    try:
        raw = raw.strip()
        if not raw:
            return 2
        if re.match(r"^https?://", raw, re.I):
            course_url = normalize_course_url(raw)
        else:
            try:
                c = resolve_course_query(raw)
            except CourseIndexError as e:
                iter_progress(f"Error: {e}")
                return 2
            course_url = normalize_course_url(c.url)
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

    api_href = class_jsonapi_self_href(course_html)
    if api_href:
        origin = f"{urlparse(course_url).scheme}://{urlparse(course_url).netloc}"
        by_slug = lesson_canonical_urls_by_slug(
            api_href,
            origin=origin,
            timeout_s=float(args.timeout_s),
        )
        if by_slug:
            fixed: list[Lesson] = []
            for l in lessons:
                slug = urlparse(l.url).path.rstrip("/").split("/")[-1]
                canon = by_slug.get(slug)
                if canon and canon != l.url:
                    fixed.append(replace(l, url=canon))
                else:
                    fixed.append(l)
            lessons = fixed

    iter_progress(f"Found {len(lessons)} lesson(s).")
    course_title = parse_course_title_from_course_html(course_html)
    if course_title:
        iter_progress(f"Class title: {course_title}")

    try:
        outline_md = build_course_outline_markdown(
            course_html,
            timeout_s=float(args.timeout_s),
            course_title=course_title,
        )
    except OutlineExtractionError as e:
        iter_progress(f"Outline error: {e}")
        return 4

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
            t = strip_transcript_ui_noise(transcript)
            transcripts[lesson.url] = strip_appended_lesson_catalog(t)
        else:
            failures.append(lesson.url)
            iter_progress(f"  Transcript extraction failed for: {lesson.title}")
            if args.fail_fast:
                write_markdown(lessons, transcripts, outpath, course_title=course_title)
                outline_path = default_outline_path(outpath)
                _ensure_dir(outline_path)
                tt = course_title or "Class"
                with open(outline_path, "w", encoding="utf-8") as f:
                    f.write(f"# {tt}\n\n{outline_md}\n")
                iter_progress(f"Wrote: {outline_path}")
                return 2

        time.sleep(max(0.0, args.sleep_seconds))

    write_markdown(lessons, transcripts, outpath, course_title=course_title)
    iter_progress(f"Wrote: {outpath}")

    outline_path = default_outline_path(outpath)
    _ensure_dir(outline_path)
    title = course_title or "Class"
    with open(outline_path, "w", encoding="utf-8") as f:
        f.write(f"# {title}\n\n{outline_md}\n")
    iter_progress(f"Wrote: {outline_path}")

    if failures:
        iter_progress(f"Failed transcripts: {len(failures)}")
    return 0


def cmd_download(args: argparse.Namespace) -> int:
    courses = getattr(args, "course", None) or []
    if not courses:
        iter_progress(
            "Error: one or more course URLs or slug-prefixes are required (e.g. nt201 or download nt201 nt203)."
        )
        return 2
    if len(courses) > 1 and args.out:
        iter_progress(
            "Error: --out cannot be used when downloading multiple courses (each uses courses/<slug>/<slug>.md)."
        )
        return 2
    worst = 0
    for raw in courses:
        r = _download_one_course(raw, args)
        worst = max(worst, r)
    return worst


def _paragraph_course(slug: str, args: argparse.Namespace, *, api_key: str) -> int:
    tpath = Path(args.transcript) if args.transcript else course_transcript_path(slug)
    if not tpath.is_file():
        iter_progress(f"Error: transcript file not found: {tpath}")
        return 2

    try:
        transcript_md = read_text(tpath)
    except OSError as e:
        iter_progress(f"Error reading file: {e}")
        return 2

    course_title = extract_course_title_from_transcript(transcript_md) or slug.replace("-", " ").title()

    if args.lesson is not None:
        lesson_nums = [int(args.lesson)]
    else:
        lesson_nums = list_lesson_numbers_from_transcript(transcript_md)
        if not lesson_nums:
            iter_progress(f"No # Lesson N: sections found in {tpath}")
            return 2
        iter_progress(f"Paragraphing {len(lesson_nums)} lesson(s) (transcript only)…")

    single_lesson = args.lesson is not None
    any_data_error = False
    combined_docs: list[str] = []

    for n in lesson_nums:
        body = extract_lesson_transcript_body(transcript_md, n)
        if body is None:
            iter_progress(f"No transcript section found for lesson {n} in {tpath}")
            any_data_error = True
            continue
        if "[Transcript not found or extraction failed.]" in body:
            iter_progress(
                f"Lesson {n} transcript is missing in Markdown (download may have failed for it)."
            )
            any_data_error = True
            continue

        iter_progress(f"Lesson {n}: calling Gemini ({args.model})…")
        try:
            gemini_raw = run_gemini_paragraph_transcript_only(
                api_key=api_key, transcription=body, model=args.model
            )
        except Exception as e:
            iter_progress(f"Gemini error: {e}")
            return 6

        h1 = extract_lesson_h1_line(transcript_md, n)
        md_doc = format_plain_paragraph_markdown_file(lesson_h1=h1, gemini_body=gemini_raw)
        if single_lesson:
            if args.out:
                outp = Path(args.out)
                if not outp.suffix:
                    outp = outp.with_suffix(".md")
            else:
                outp = default_plain_paragraph_out_path(slug, n, model=args.model)
            _ensure_dir(str(outp))
            full_md = format_paragraphed_document_with_toc(
                course_title=course_title,
                lesson_md_docs=[md_doc],
            )
            outp.write_text(full_md, encoding="utf-8")
            iter_progress(f"Wrote Markdown: {outp}")
        else:
            combined_docs.append(md_doc)

    if not single_lesson and combined_docs:
        if args.out:
            outp = Path(args.out)
            if not outp.suffix:
                outp = outp.with_suffix(".md")
        else:
            outp = default_plain_paragraph_course_out_path(slug, model=args.model)
        _ensure_dir(str(outp))
        full_md = format_paragraphed_document_with_toc(
            course_title=course_title,
            lesson_md_docs=combined_docs,
        )
        outp.write_text(full_md, encoding="utf-8")
        iter_progress(f"Wrote Markdown: {outp}")

    if any_data_error:
        return 2
    return 0


def cmd_paragraph(args: argparse.Namespace) -> int:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        iter_progress("Error: GEMINI_API_KEY is not set.")
        return 5
    slugs = getattr(args, "course_slug", None) or []
    if not slugs:
        iter_progress(
            "Error: one or more course slug(s) or slug-prefix(es) are required "
            "(e.g. nt203 or nt203 nt203-greek-tools-for-bible-study)."
        )
        return 2
    if len(slugs) > 1 and (args.transcript or args.out):
        iter_progress("Error: --transcript and --out cannot be used with multiple courses.")
        return 2
    worst = 0
    for raw in slugs:
        raw = raw.strip()
        if not raw:
            worst = max(worst, 2)
            continue
        try:
            slug = resolve_course_query(raw).slug
        except CourseIndexError as e:
            iter_progress(f"Error: {e}")
            worst = max(worst, 2)
            continue
        if len(slugs) > 1:
            iter_progress(f"--- {slug} ---")
        worst = max(worst, _paragraph_course(slug, args, api_key=key))
    return worst


def _paragraph_outline_course(slug: str, args: argparse.Namespace, *, api_key: str) -> int:
    tpath, opath = resolve_transcript_outline_paths(
        slug,
        transcript=args.transcript,
        outline=args.outline,
    )
    if not tpath.is_file():
        iter_progress(f"Error: transcript file not found: {tpath}")
        return 2
    if not opath.is_file():
        iter_progress(f"Error: outline file not found: {opath}")
        return 2

    try:
        transcript_md = read_text(tpath)
        outline_md = read_text(opath)
    except OSError as e:
        iter_progress(f"Error reading file: {e}")
        return 2

    course_title = extract_course_title_from_transcript(transcript_md) or slug.replace("-", " ").title()

    if args.lesson is not None:
        lesson_nums = [int(args.lesson)]
    else:
        lesson_nums = list_lesson_numbers_from_transcript(transcript_md)
        if not lesson_nums:
            iter_progress(f"No # Lesson N: sections found in {tpath}")
            return 2
        iter_progress(f"Paragraphing {len(lesson_nums)} lesson(s)…")

    any_data_error = False
    combined_docs: list[str] = []
    single_lesson = args.lesson is not None

    prepared: list[tuple[int, str, str]] = []
    for n in lesson_nums:
        body = extract_lesson_transcript_body(transcript_md, n)
        if body is None:
            iter_progress(f"No transcript section found for lesson {n} in {tpath}")
            any_data_error = True
            continue
        if "[Transcript not found or extraction failed.]" in body:
            iter_progress(
                f"Lesson {n} transcript is missing in Markdown (download may have failed for it)."
            )
            any_data_error = True
            continue

        outline_block = extract_lesson_outline_section(outline_md, n)
        if outline_block is None:
            iter_progress(f"No outline section found for lesson {n} in {opath}")
            any_data_error = True
            continue
        prepared.append((n, body, outline_block))

    for n, body, outline_block in prepared:
        iter_progress(f"Lesson {n}: calling Gemini ({args.model})…")
        try:
            raw = run_gemini_paragraph(
                api_key=api_key,
                transcription=body,
                outline=outline_block,
                model=args.model,
            )
        except Exception as e:
            iter_progress(f"Gemini error: {e}")
            return 6

        h1 = extract_lesson_h1_line(transcript_md, n)
        md_doc = format_paragraph_markdown_file(lesson_h1=h1, gemini_body=raw)
        if single_lesson:
            if args.out:
                outp = Path(args.out)
                if not outp.suffix:
                    outp = outp.with_suffix(".md")
            else:
                outp = default_paragraph_out_path(slug, n, model=args.model)
            _ensure_dir(str(outp))
            full_md = format_paragraphed_document_with_toc(
                course_title=course_title,
                lesson_md_docs=[md_doc],
            )
            outp.write_text(full_md, encoding="utf-8")
            iter_progress(f"Wrote Markdown: {outp}")
        else:
            combined_docs.append(md_doc)

    if not single_lesson and combined_docs:
        if args.out:
            outp = Path(args.out)
            if not outp.suffix:
                outp = outp.with_suffix(".md")
        else:
            outp = default_paragraph_course_out_path(slug, model=args.model)
        _ensure_dir(str(outp))
        full_md = format_paragraphed_document_with_toc(
            course_title=course_title,
            lesson_md_docs=combined_docs,
        )
        outp.write_text(full_md, encoding="utf-8")
        iter_progress(f"Wrote Markdown: {outp}")

    if any_data_error:
        return 2
    return 0


def _study_note_chinese_course(
    slug: str, args: argparse.Namespace, *, api_key: str, simplified: bool
) -> int:
    tpath, opath = resolve_transcript_outline_paths(
        slug,
        transcript=args.transcript,
        outline=args.outline,
    )
    if not tpath.is_file():
        iter_progress(f"Error: transcript file not found: {tpath}")
        return 2
    if not opath.is_file():
        iter_progress(f"Error: outline file not found: {opath}")
        return 2

    try:
        transcript_md = read_text(tpath)
        outline_md = read_text(opath)
    except OSError as e:
        iter_progress(f"Error reading file: {e}")
        return 2

    course_title = extract_course_title_from_transcript(transcript_md) or slug.replace("-", " ").title()
    label = "Simplified Chinese" if simplified else "Traditional Chinese"
    variant = "cn" if simplified else "zh"

    if args.lesson is not None:
        lesson_nums = [int(args.lesson)]
    else:
        lesson_nums = list_lesson_numbers_from_transcript(transcript_md)
        if not lesson_nums:
            iter_progress(f"No # Lesson N: sections found in {tpath}")
            return 2
        iter_progress(f"Study notes: {len(lesson_nums)} lesson(s) in {label}…")

    any_data_error = False
    combined_docs: list[str] = []
    single_lesson = args.lesson is not None

    prepared: list[tuple[int, str, str]] = []
    for n in lesson_nums:
        body = extract_lesson_transcript_body(transcript_md, n)
        if body is None:
            iter_progress(f"No transcript section found for lesson {n} in {tpath}")
            any_data_error = True
            continue
        if "[Transcript not found or extraction failed.]" in body:
            iter_progress(
                f"Lesson {n} transcript is missing in Markdown (download may have failed for it)."
            )
            any_data_error = True
            continue

        outline_block = extract_lesson_outline_section(outline_md, n)
        if outline_block is None:
            iter_progress(f"No outline section found for lesson {n} in {opath}")
            any_data_error = True
            continue
        prepared.append((n, body, outline_block))

    for n, body, outline_block in prepared:
        h1 = extract_lesson_h1_line(transcript_md, n)
        iter_progress(f"Lesson {n}: calling Gemini ({args.model}) for {label} study note…")
        try:
            raw = run_gemini_chinese_study_note(
                api_key=api_key,
                transcription=body,
                outline=outline_block,
                model=args.model,
                lesson_h1_line=h1,
                simplified=simplified,
            )
        except Exception as e:
            iter_progress(f"Gemini error: {e}")
            return 6

        md_doc = format_chinese_study_note_markdown_file(
            lesson_h1=h1, gemini_body=raw, variant=variant
        )
        if single_lesson:
            if args.out:
                outp = Path(args.out)
                if not outp.suffix:
                    outp = outp.with_suffix(".md")
            else:
                if simplified:
                    outp = default_study_note_cn_out_path(slug, n, model=args.model)
                else:
                    outp = default_study_note_zh_out_path(slug, n, model=args.model)
            _ensure_dir(str(outp))
            full_md = format_paragraphed_document_with_toc(
                course_title=course_title,
                lesson_md_docs=[md_doc],
            )
            outp.write_text(full_md, encoding="utf-8")
            iter_progress(f"Wrote Markdown: {outp}")
        else:
            combined_docs.append(md_doc)

    if not single_lesson and combined_docs:
        if args.out:
            outp = Path(args.out)
            if not outp.suffix:
                outp = outp.with_suffix(".md")
        else:
            if simplified:
                outp = default_study_note_cn_course_out_path(slug, model=args.model)
            else:
                outp = default_study_note_zh_course_out_path(slug, model=args.model)
        _ensure_dir(str(outp))
        full_md = format_paragraphed_document_with_toc(
            course_title=course_title,
            lesson_md_docs=combined_docs,
        )
        outp.write_text(full_md, encoding="utf-8")
        iter_progress(f"Wrote Markdown: {outp}")

    if any_data_error:
        return 2
    return 0


def cmd_study_note_zh(args: argparse.Namespace) -> int:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        iter_progress("Error: GEMINI_API_KEY is not set.")
        return 5
    slugs = getattr(args, "course_slug", None) or []
    if not slugs:
        iter_progress(
            "Error: one or more course slug(s) or slug-prefix(es) are required "
            "(e.g. nt203 or nt203-greek-tools-for-bible-study)."
        )
        return 2
    if len(slugs) > 1 and (args.transcript or args.outline or args.out):
        iter_progress(
            "Error: --transcript, --outline, and --out cannot be used with multiple courses."
        )
        return 2
    worst = 0
    for raw in slugs:
        raw = raw.strip()
        if not raw:
            worst = max(worst, 2)
            continue
        try:
            slug = resolve_course_query(raw).slug
        except CourseIndexError as e:
            iter_progress(f"Error: {e}")
            worst = max(worst, 2)
            continue
        if len(slugs) > 1:
            iter_progress(f"--- {slug} ---")
        worst = max(worst, _study_note_chinese_course(slug, args, api_key=key, simplified=False))
    return worst


def cmd_study_note_cn(args: argparse.Namespace) -> int:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        iter_progress("Error: GEMINI_API_KEY is not set.")
        return 5
    slugs = getattr(args, "course_slug", None) or []
    if not slugs:
        iter_progress(
            "Error: one or more course slug(s) or slug-prefix(es) are required "
            "(e.g. nt203 or nt203-greek-tools-for-bible-study)."
        )
        return 2
    if len(slugs) > 1 and (args.transcript or args.outline or args.out):
        iter_progress(
            "Error: --transcript, --outline, and --out cannot be used with multiple courses."
        )
        return 2
    worst = 0
    for raw in slugs:
        raw = raw.strip()
        if not raw:
            worst = max(worst, 2)
            continue
        try:
            slug = resolve_course_query(raw).slug
        except CourseIndexError as e:
            iter_progress(f"Error: {e}")
            worst = max(worst, 2)
            continue
        if len(slugs) > 1:
            iter_progress(f"--- {slug} ---")
        worst = max(worst, _study_note_chinese_course(slug, args, api_key=key, simplified=True))
    return worst


def _translate_chinese_course(
    slug: str, args: argparse.Namespace, *, api_key: str, simplified: bool
) -> int:
    lessons, err = load_paragraph_lessons_for_translation(
        slug,
        model=args.model,
        paragraph=getattr(args, "paragraph", None),
        lesson_num=args.lesson,
    )
    if err:
        iter_progress(f"Error: {err}")
        return 2

    label = "Simplified Chinese" if simplified else "Traditional Chinese"
    variant = "cn" if simplified else "zh"

    paragraph_md_hint: Optional[str] = None
    p_arg = getattr(args, "paragraph", None)
    if p_arg:
        pp = Path(p_arg)
        if pp.is_file():
            paragraph_md_hint = read_text(pp)
    combined = default_plain_paragraph_course_out_path(slug, model=args.model)
    if paragraph_md_hint is None and combined.is_file():
        paragraph_md_hint = read_text(combined)

    title_en = resolve_english_course_title_for_translation(
        slug, model=args.model, paragraph_md_hint=paragraph_md_hint
    )

    iter_progress(f"Translating course title to {label}…")
    try:
        title_translated = run_gemini_translate_course_title(
            api_key=api_key,
            title_en=title_en,
            model=args.model,
            simplified=simplified,
        )
    except Exception as e:
        iter_progress(f"Gemini error (title): {e}")
        return 6

    single_lesson = args.lesson is not None
    combined_docs: list[str] = []

    for n, chunk in lessons:
        h2_src = lesson_h2_line_from_paragraph_chunk(chunk)
        iter_progress(f"Lesson {n}: calling Gemini ({args.model}) for {label} translation…")
        try:
            raw = run_gemini_chinese_translation(
                api_key=api_key,
                lesson_english_md=chunk,
                model=args.model,
                lesson_h2_official=h2_src,
                simplified=simplified,
            )
        except Exception as e:
            iter_progress(f"Gemini error: {e}")
            return 6

        md_doc = format_chinese_translation_markdown_file(
            lesson_h2_line=h2_src,
            gemini_body=raw,
            variant=variant,
        )
        if single_lesson:
            if args.out:
                outp = Path(args.out)
                if not outp.suffix:
                    outp = outp.with_suffix(".md")
            else:
                if simplified:
                    outp = default_translate_cn_out_path(slug, n, model=args.model)
                else:
                    outp = default_translate_zh_out_path(slug, n, model=args.model)
            _ensure_dir(str(outp))
            full_md = format_paragraphed_document_with_toc(
                course_title=title_translated,
                lesson_md_docs=[md_doc],
            )
            outp.write_text(full_md, encoding="utf-8")
            iter_progress(f"Wrote Markdown: {outp}")
        else:
            combined_docs.append(md_doc)

    if not single_lesson and combined_docs:
        if args.out:
            outp = Path(args.out)
            if not outp.suffix:
                outp = outp.with_suffix(".md")
        else:
            if simplified:
                outp = default_translate_cn_course_out_path(slug, model=args.model)
            else:
                outp = default_translate_zh_course_out_path(slug, model=args.model)
        _ensure_dir(str(outp))
        full_md = format_paragraphed_document_with_toc(
            course_title=title_translated,
            lesson_md_docs=combined_docs,
        )
        outp.write_text(full_md, encoding="utf-8")
        iter_progress(f"Wrote Markdown: {outp}")

    return 0


def cmd_translate_zh(args: argparse.Namespace) -> int:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        iter_progress("Error: GEMINI_API_KEY is not set.")
        return 5
    slugs = getattr(args, "course_slug", None) or []
    if not slugs:
        iter_progress(
            "Error: one or more course slug(s) or slug-prefix(es) are required "
            "(e.g. nt203 or nt203-greek-tools-for-bible-study)."
        )
        return 2
    if len(slugs) > 1 and (getattr(args, "paragraph", None) or args.out):
        iter_progress(
            "Error: --paragraph and --out cannot be used with multiple courses."
        )
        return 2
    worst = 0
    for raw in slugs:
        raw = raw.strip()
        if not raw:
            worst = max(worst, 2)
            continue
        try:
            slug = resolve_course_query(raw).slug
        except CourseIndexError as e:
            iter_progress(f"Error: {e}")
            worst = max(worst, 2)
            continue
        if len(slugs) > 1:
            iter_progress(f"--- {slug} ---")
        worst = max(worst, _translate_chinese_course(slug, args, api_key=key, simplified=False))
    return worst


def cmd_translate_cn(args: argparse.Namespace) -> int:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        iter_progress("Error: GEMINI_API_KEY is not set.")
        return 5
    slugs = getattr(args, "course_slug", None) or []
    if not slugs:
        iter_progress(
            "Error: one or more course slug(s) or slug-prefix(es) are required "
            "(e.g. nt203 or nt203-greek-tools-for-bible-study)."
        )
        return 2
    if len(slugs) > 1 and (getattr(args, "paragraph", None) or args.out):
        iter_progress(
            "Error: --paragraph and --out cannot be used with multiple courses."
        )
        return 2
    worst = 0
    for raw in slugs:
        raw = raw.strip()
        if not raw:
            worst = max(worst, 2)
            continue
        try:
            slug = resolve_course_query(raw).slug
        except CourseIndexError as e:
            iter_progress(f"Error: {e}")
            worst = max(worst, 2)
            continue
        if len(slugs) > 1:
            iter_progress(f"--- {slug} ---")
        worst = max(worst, _translate_chinese_course(slug, args, api_key=key, simplified=True))
    return worst


def cmd_paragraph_lesson(args: argparse.Namespace) -> int:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        iter_progress("Error: GEMINI_API_KEY is not set.")
        return 5
    slugs = getattr(args, "course_slug", None) or []
    if not slugs:
        iter_progress(
            "Error: one or more course slug(s) or slug-prefix(es) are required "
            "(e.g. nt203 or nt203 nt203-greek-tools-for-bible-study)."
        )
        return 2
    if len(slugs) > 1 and (args.transcript or args.outline or args.out):
        iter_progress(
            "Error: --transcript, --outline, and --out cannot be used with multiple courses."
        )
        return 2
    worst = 0
    for raw in slugs:
        raw = raw.strip()
        if not raw:
            worst = max(worst, 2)
            continue
        try:
            slug = resolve_course_query(raw).slug
        except CourseIndexError as e:
            iter_progress(f"Error: {e}")
            worst = max(worst, 2)
            continue
        if len(slugs) > 1:
            iter_progress(f"--- {slug} ---")
        worst = max(worst, _paragraph_outline_course(slug, args, api_key=key))
    return worst


def _add_study_note_cli(
    sub,
    name: str,
    *,
    simplified: bool,
    func,
    deprecated: bool,
) -> None:
    out_seg = "study-note-cn" if simplified else "study-note-zh"
    ext = "cn" if simplified else "zh"
    lang_long = "Simplified Chinese (简体中文)" if simplified else "Traditional Chinese (繁體中文)"
    if deprecated:
        primary = "study-note-cn" if simplified else "study-note-zh"
        help_txt = f"(Deprecated) Alias for `{primary}`."
        desc = (
            f"Deprecated: use `{primary}` instead. Same behavior as `{primary}`.\n"
            "Pass one or more course slugs or slug-prefixes from the index.\n"
            "If a prefix matches 0 or >1 courses, that entry fails. With multiple courses, --transcript, --outline, and --out are not allowed."
        )
    else:
        help_txt = f"Generate {lang_long} study notes with Gemini (transcript + outline on disk)."
        desc = (
            f"Generate detailed {lang_long} study-guide notes from transcript + outline Markdown.\n"
            "Pass one or more course slugs or slug-prefixes from the index.\n"
            "If a prefix matches 0 or >1 courses, that entry fails. With multiple courses, --transcript, --outline, and --out are not allowed."
        )
    p = sub.add_parser(name, help=help_txt, description=desc)
    p.add_argument(
        "course_slug",
        nargs="+",
        help="One or more course slugs OR slug-prefixes (from index), e.g. nt203 nt201-biblical-greek.",
    )
    p.add_argument(
        "--lesson",
        type=int,
        default=None,
        metavar="N",
        help=(
            "Lesson number (same as # Lesson N: headings). Omit to generate study notes for every lesson."
        ),
    )
    p.add_argument(
        "--transcript",
        default=None,
        help="Transcript .md path (default: courses/<slug>/<slug>.md; not allowed with multiple courses).",
    )
    p.add_argument(
        "--outline",
        default=None,
        help="Outline .md path (default: courses/<slug>/<slug>.outline.md; not allowed with multiple courses).",
    )
    p.add_argument(
        "--out",
        default=None,
        help=(
            "Output file (single course only): with --lesson, default "
            f"courses/<slug>/{out_seg}/<model>/<slug>.lessonNN.{ext}.md; "
            f"without --lesson, default courses/<slug>/{out_seg}/<model>/<slug>.{ext}.md (all lessons in one file)."
        ),
    )
    p.add_argument(
        "--model",
        default="gemini-3.1-flash-lite-preview",
        help="Gemini model id (default: gemini-3.1-flash-lite-preview).",
    )
    p.set_defaults(func=func)


def main() -> int:
    # Load `.env` from the current working directory (does not override existing env vars).
    load_dotenv()

    # Ensure course index exists on startup (used for slug-prefix resolution).
    try:
        ensure_index_exists()
    except Exception as e:
        iter_progress(f"Error: failed to fetch course index ({index_path()}): {e}")
        return 2

    parser = argparse.ArgumentParser(
        prog="bt",
        description=(
            "BiblicalTraining.org transcripts: download, paragraph lessons with Gemini (transcript-only or with outline), "
            "Chinese study notes (study-note-zh / study-note-cn; explain-zh / explain-cn are deprecated aliases), or Chinese translations of paragraphed lessons (translate-zh / translate-cn)."
        ),
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=(
            "Examples:\n"
            "  # Refresh local course index\n"
            "  python -m bt refresh-index\n"
            "\n"
            "  # Download by URL\n"
            "  python -m bt download \"https://www.biblicaltraining.org/learn/institute/nt201-biblical-greek\"\n"
            "\n"
            "  # Download by slug-prefix (must be unambiguous)\n"
            "  python -m bt download nt201\n"
            "\n"
            "  # Download multiple courses\n"
            "  python -m bt download nt201 nt203\n"
            "\n"
            "  # Paragraph one lesson (transcript only, no outline)\n"
            "  python -m bt paragraph nt203 --lesson 3\n"
            "\n"
            "  # Paragraph all lessons (transcript only; one combined file)\n"
            "  python -m bt paragraph nt203\n"
            "\n"
            "  # Paragraph multiple courses (default output path per course)\n"
            "  python -m bt paragraph nt203 nt201\n"
            "\n"
            "  # Outline-paragraph one lesson\n"
            "  python -m bt paragraph-outline nt203 --lesson 3\n"
            "\n"
            "  # Outline-paragraph all lessons (one Gemini request per lesson)\n"
            "  python -m bt paragraph-outline nt203\n"
            "\n"
            "  # Outline-paragraph multiple courses\n"
            "  python -m bt paragraph-outline nt203 nt201\n"
            "\n"
            "  # Traditional Chinese study notes (one lesson)\n"
            "  python -m bt study-note-zh nt203 --lesson 3\n"
            "\n"
            "  # Traditional Chinese study notes (all lessons)\n"
            "  python -m bt study-note-zh nt203\n"
            "\n"
            "  # Simplified Chinese study notes (one lesson)\n"
            "  python -m bt study-note-cn nt203 --lesson 3\n"
            "\n"
            "  # Simplified Chinese study notes (all lessons)\n"
            "  python -m bt study-note-cn nt203\n"
            "\n"
            "  # Traditional Chinese translation of paragraphed lesson(s)\n"
            "  python -m bt translate-zh nt203 --lesson 3\n"
            "  python -m bt translate-zh nt203\n"
            "\n"
            "  # Simplified Chinese translation of paragraphed lesson(s)\n"
            "  python -m bt translate-cn nt203 --lesson 3\n"
            "  python -m bt translate-cn nt203\n"
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    r = sub.add_parser("refresh-index", help="Refetch and overwrite the local course index cache.")
    r.add_argument("--timeout-s", type=int, default=30)
    r.set_defaults(
        func=lambda args: (
            iter_progress(f"Wrote index: {write_fetched_index(timeout_s=int(args.timeout_s))}") or 0
        )
    )

    li = sub.add_parser(
        "list-index",
        help="List cached courses from the local index.",
        description="List cached courses from the local course index.",
    )
    li.add_argument("--limit", type=int, default=0, help="Max courses to print (0 = no limit).")
    li.set_defaults(
        func=lambda args: _cmd_list_index(args),
    )

    si = sub.add_parser(
        "search-index",
        help="Search cached courses by slug prefix.",
        description="Search cached courses by slug prefix (case-insensitive).",
    )
    si.add_argument("query", help="Slug prefix to search (case-insensitive). Example: nt201")
    si.add_argument("--limit", type=int, default=50, help="Max matches to print (default: 50).")
    si.set_defaults(
        func=lambda args: _cmd_search_index(args),
    )

    d = sub.add_parser(
        "download",
        help="Download course transcript(s) to Markdown file(s).",
        description="Download one or more courses; each writes courses/<slug>/<slug>.md and courses/<slug>/<slug>.outline.md.",
    )
    d.add_argument(
        "course",
        nargs="+",
        help=(
            "One or more class/course page URLs OR slug-prefixes (from index), "
            "e.g. nt201 nt203 or a single https://.../learn/.../nt201-biblical-greek"
        ),
    )
    d.add_argument(
        "--out",
        default=None,
        help="Output Markdown file (default: courses/<course-slug>/<course-slug>.md)",
    )
    d.add_argument("--cookies-json", default=None, help="Optional Playwright-format cookies JSON.")
    d.add_argument(
        "--fetcher",
        default="auto",
        choices=["auto", "requests", "playwright"],
        help="How to fetch pages (auto falls back to Playwright on Cloudflare).",
    )
    d.add_argument("--timeout-s", type=int, default=30)
    d.add_argument("--playwright-timeout-ms", type=int, default=60000)
    d.add_argument("--headless", action="store_true")
    d.add_argument("--sleep-seconds", type=float, default=1.2)
    d.add_argument("--fail-fast", action="store_true")
    d.set_defaults(func=cmd_download)

    pg = sub.add_parser(
        "paragraph",
        help="Paragraph lesson(s) with Gemini using the transcript only (no outline file).",
        description=(
            "Paragraph lesson(s) with Gemini using the downloaded transcript Markdown only.\n"
            "With --lesson, only that lesson; omit --lesson to process every lesson in one file.\n"
            "Does not use the course outline file. Pass one or more course slugs or slug-prefixes from the index.\n"
            "If a prefix matches 0 or >1 courses, that entry fails. With multiple courses, --transcript and --out are not allowed."
        ),
    )
    pg.add_argument(
        "course_slug",
        nargs="+",
        help="One or more course slugs OR slug-prefixes (from index), e.g. nt203 nt201-biblical-greek.",
    )
    pg.add_argument(
        "--lesson",
        type=int,
        default=None,
        metavar="N",
        help=(
            "Lesson number (same as # Lesson N: headings). Omit to paragraph every lesson "
            "(one Gemini request per lesson; one combined output file)."
        ),
    )
    pg.add_argument(
        "--transcript",
        default=None,
        help="Transcript .md path (default: courses/<slug>/<slug>.md; not allowed with multiple courses).",
    )
    pg.add_argument(
        "--out",
        default=None,
        help=(
            "Output file (single course only): with --lesson, default courses/<slug>/paragraph/<model>/<slug>.lessonNN.paragraph.md; "
            "without --lesson, default courses/<slug>/paragraph/<model>/<slug>.paragraph.md (all lessons). "
            "Paths without an extension get .md appended."
        ),
    )
    pg.add_argument(
        "--model",
        default="gemini-3.1-flash-lite-preview",
        help="Gemini model id (default: gemini-3.1-flash-lite-preview).",
    )
    pg.set_defaults(func=cmd_paragraph)

    p = sub.add_parser(
        "paragraph-outline",
        help="Outline-paragraph lesson(s) with Gemini using transcript + outline Markdown on disk.",
        description=(
            "Outline-paragraph lesson(s) with Gemini using transcript + outline Markdown on disk.\n"
            "Pass one or more course slugs or slug-prefixes from the index.\n"
            "If a prefix matches 0 or >1 courses, that entry fails. With multiple courses, --transcript, --outline, and --out are not allowed."
        ),
    )
    p.add_argument(
        "course_slug",
        nargs="+",
        help="One or more course slugs OR slug-prefixes (from index), e.g. nt203 nt201-biblical-greek.",
    )
    p.add_argument(
        "--lesson",
        type=int,
        default=None,
        help="Lesson number (same as # Lesson N: headings). Omit to process every lesson.",
    )
    p.add_argument(
        "--transcript",
        default=None,
        help="Transcript .md path (default: courses/<slug>/<slug>.md; not allowed with multiple courses).",
    )
    p.add_argument(
        "--outline",
        default=None,
        help="Outline .md path (default: courses/<slug>/<slug>.outline.md; not allowed with multiple courses).",
    )
    p.add_argument(
        "--out",
        default=None,
        help=(
            "Output file (single course only): with --lesson, default courses/<slug>/paragraph-outlined/<model>/<slug>.lessonNN.paragraph-outlined.md; "
            "without --lesson, default courses/<slug>/paragraph-outlined/<model>/<slug>.paragraph-outlined.md (all lessons in one file)."
        ),
    )
    p.add_argument(
        "--model",
        default="gemini-3.1-flash-lite-preview",
        help="Gemini model id (default: gemini-3.1-flash-lite-preview).",
    )
    p.set_defaults(func=cmd_paragraph_lesson)

    # Backwards-compatible alias.
    p2 = sub.add_parser(
        "paragraph-lesson",
        help="(Deprecated) Use `paragraph-outline`.",
    )
    # Mirror arguments from `paragraph-outline`.
    p2.add_argument(
        "course_slug",
        nargs="+",
        help="One or more course slugs OR slug-prefixes (from index), e.g. nt203 nt201-biblical-greek.",
    )
    p2.add_argument(
        "--lesson",
        type=int,
        default=None,
        help="Lesson number (same as # Lesson N: headings). Omit to process every lesson.",
    )
    p2.add_argument(
        "--transcript",
        default=None,
        help="Transcript .md path (default: courses/<slug>/<slug>.md; not allowed with multiple courses).",
    )
    p2.add_argument(
        "--outline",
        default=None,
        help="Outline .md path (default: courses/<slug>/<slug>.outline.md; not allowed with multiple courses).",
    )
    p2.add_argument(
        "--out",
        default=None,
        help=(
            "Output file (single course only): with --lesson, default courses/<slug>/paragraph-outlined/<model>/<slug>.lessonNN.paragraph-outlined.md; "
            "without --lesson, default courses/<slug>/paragraph-outlined/<model>/<slug>.paragraph-outlined.md (all lessons in one file)."
        ),
    )
    p2.add_argument(
        "--model",
        default="gemini-3.1-flash-lite-preview",
        help="Gemini model id (default: gemini-3.1-flash-lite-preview).",
    )
    p2.set_defaults(func=cmd_paragraph_lesson)

    _add_study_note_cli(
        sub, "study-note-zh", simplified=False, func=cmd_study_note_zh, deprecated=False
    )
    _add_study_note_cli(
        sub, "study-note-cn", simplified=True, func=cmd_study_note_cn, deprecated=False
    )
    _add_study_note_cli(sub, "explain-zh", simplified=False, func=cmd_study_note_zh, deprecated=True)
    _add_study_note_cli(sub, "explain-cn", simplified=True, func=cmd_study_note_cn, deprecated=True)

    tz = sub.add_parser(
        "translate-zh",
        help="Translate paragraphed English lesson(s) to Traditional Chinese with Gemini.",
        description=(
            "Translate Markdown from courses/<slug>/paragraph/ (``paragraph`` command output) into Traditional Chinese (繁體中文).\n"
            "One Gemini request per lesson, plus one for the course title. Pass one or more course slugs or slug-prefixes from the index.\n"
            "If a prefix matches 0 or >1 courses, that entry fails. With multiple courses, --paragraph and --out are not allowed."
        ),
    )
    tz.add_argument(
        "course_slug",
        nargs="+",
        help="One or more course slugs OR slug-prefixes (from index), e.g. nt203 nt201-biblical-greek.",
    )
    tz.add_argument(
        "--lesson",
        type=int,
        default=None,
        metavar="N",
        help="Lesson number (same as ## Lesson N: in paragraph Markdown). Omit to translate every lesson.",
    )
    tz.add_argument(
        "--paragraph",
        default=None,
        help=(
            "Input .md path (single course only): default courses/<slug>/paragraph/<model>/<slug>.paragraph.md "
            "or courses/<slug>/paragraph/<model>/<slug>.lessonNN.paragraph.md with --lesson."
        ),
    )
    tz.add_argument(
        "--out",
        default=None,
        help=(
            "Output file (single course only): with --lesson, default courses/<slug>/translate-zh/<model>/<slug>.lessonNN.zh.md; "
            "without --lesson, default courses/<slug>/translate-zh/<model>/<slug>.zh.md (all lessons in one file)."
        ),
    )
    tz.add_argument(
        "--model",
        default="gemini-3.1-flash-lite-preview",
        help="Gemini model id (default: gemini-3.1-flash-lite-preview).",
    )
    tz.set_defaults(func=cmd_translate_zh)

    tc = sub.add_parser(
        "translate-cn",
        help="Translate paragraphed English lesson(s) to Simplified Chinese with Gemini.",
        description=(
            "Translate Markdown from courses/<slug>/paragraph/ (``paragraph`` command output) into Simplified Chinese (简体中文).\n"
            "One Gemini request per lesson, plus one for the course title. Pass one or more course slugs or slug-prefixes from the index.\n"
            "If a prefix matches 0 or >1 courses, that entry fails. With multiple courses, --paragraph and --out are not allowed."
        ),
    )
    tc.add_argument(
        "course_slug",
        nargs="+",
        help="One or more course slugs OR slug-prefixes (from index), e.g. nt203 nt201-biblical-greek.",
    )
    tc.add_argument(
        "--lesson",
        type=int,
        default=None,
        metavar="N",
        help="Lesson number (same as ## Lesson N: in paragraph Markdown). Omit to translate every lesson.",
    )
    tc.add_argument(
        "--paragraph",
        default=None,
        help=(
            "Input .md path (single course only): default courses/<slug>/paragraph/<model>/<slug>.paragraph.md "
            "or courses/<slug>/paragraph/<model>/<slug>.lessonNN.paragraph.md with --lesson."
        ),
    )
    tc.add_argument(
        "--out",
        default=None,
        help=(
            "Output file (single course only): with --lesson, default courses/<slug>/translate-cn/<model>/<slug>.lessonNN.cn.md; "
            "without --lesson, default courses/<slug>/translate-cn/<model>/<slug>.cn.md (all lessons in one file)."
        ),
    )
    tc.add_argument(
        "--model",
        default="gemini-3.1-flash-lite-preview",
        help="Gemini model id (default: gemini-3.1-flash-lite-preview).",
    )
    tc.set_defaults(func=cmd_translate_cn)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
