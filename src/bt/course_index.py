from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse

import requests


BT_BASE = "https://www.biblicaltraining.org"
CLASSES_URL = f"{BT_BASE}/classes"
BT_BACK_JSONAPI = "https://back.biblicaltraining.org/jsonapi"
JSONAPI_CLASSES_URL = f"{BT_BACK_JSONAPI}/node/class"


@dataclass(frozen=True)
class Course:
    slug: str
    title: str
    url: str
    category: Optional[str] = None


class CourseIndexError(RuntimeError):
    pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def user_cache_dir() -> Path:
    """
    Best-effort per-user cache dir without extra dependencies.
    - macOS: ~/Library/Caches/bt-class-downloader
    - others: ~/.cache/bt-class-downloader
    """
    home = Path.home()
    if sys.platform == "darwin":
        return home / "Library" / "Caches" / "bt-class-downloader"
    return home / ".cache" / "bt-class-downloader"


def index_path() -> Path:
    return user_cache_dir() / "course_index.json"


def load_index(path: Optional[Path] = None) -> dict:
    p = path or index_path()
    return json.loads(p.read_text(encoding="utf-8"))


def save_index(data: dict, path: Optional[Path] = None) -> None:
    p = path or index_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


class _LinkCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._in_a = False
        self._href: Optional[str] = None
        self._text_parts: list[str] = []
        self.links: list[tuple[str, str]] = []  # (href, text)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        if tag.lower() != "a":
            return
        href = None
        for k, v in attrs:
            if k.lower() == "href" and v:
                href = v
                break
        if href is None:
            return
        self._in_a = True
        self._href = href
        self._text_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a":
            return
        if self._in_a and self._href:
            text = "".join(self._text_parts).strip()
            self.links.append((self._href, text))
        self._in_a = False
        self._href = None
        self._text_parts = []

    def handle_data(self, data: str) -> None:
        if self._in_a and data:
            self._text_parts.append(data)


def _fetch_html(url: str, timeout_s: int = 30) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    resp = requests.get(url, headers=headers, timeout=timeout_s)
    resp.raise_for_status()
    return resp.text


def _fetch_json(url: str, timeout_s: int = 30) -> dict:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "application/vnd.api+json",
        "Accept-Language": "en-US,en;q=0.9",
    }
    resp = requests.get(url, headers=headers, timeout=timeout_s)
    resp.raise_for_status()
    return resp.json()


def _is_course_url(href: str) -> bool:
    # Site uses /learn/<program>/<slug>
    try:
        p = urlparse(href)
    except Exception:
        return False
    path = p.path or ""
    return "/learn/" in path and bool(path.rstrip("/").split("/")[-1])


def _course_slug_from_url(url: str) -> str:
    path = urlparse(url).path.rstrip("/")
    return path.split("/")[-1]


def _is_classes_category_href(href: str) -> bool:
    p = urlparse(href)
    path = p.path or ""
    return path.startswith("/classes/") and path != "/classes"


def _course_from_jsonapi_node(item: dict, *, subject_name_by_id: dict[str, str]) -> Optional[Course]:
    try:
        attrs = item.get("attributes") or {}
        if not attrs.get("status", True):
            return None
        title = str(attrs.get("title") or "").strip()
        path = (attrs.get("path") or {}).get("alias") or ""
        if not path:
            return None
        url = urljoin(BT_BASE, path)
        slug = _course_slug_from_url(url)
        cat = None
        rel = item.get("relationships") or {}
        subs = (rel.get("field_subjects") or {}).get("data") or []
        if isinstance(subs, dict):
            subs = [subs]
        for s in subs:
            sid = s.get("id") if isinstance(s, dict) else None
            if sid and sid in subject_name_by_id:
                cat = subject_name_by_id[sid]
                break
        return Course(slug=slug, title=title or slug, url=url, category=cat)
    except Exception:
        return None


def fetch_course_index_jsonapi(*, timeout_s: int = 30) -> list[Course]:
    """
    Fetch all classes from the site's JSON:API backend.

    This is more reliable than scraping /classes HTML, because the category pages are
    rendered client-side and do not contain course links in the server HTML.
    """
    url = (
        JSONAPI_CLASSES_URL
        + "?page[limit]=50"
        + "&include=field_subjects"
        + "&fields[node--class]=title,path,status,field_search_title,field_seo_title"
        + "&fields[taxonomy_term--subjects]=name"
    )
    by_slug: dict[str, Course] = {}
    while url:
        data = _fetch_json(url, timeout_s=timeout_s)
        included = data.get("included") or []
        subject_name_by_id: dict[str, str] = {}
        for inc in included:
            if not isinstance(inc, dict):
                continue
            if inc.get("type") != "taxonomy_term--subjects":
                continue
            sid = inc.get("id")
            name = (inc.get("attributes") or {}).get("name")
            if sid and name:
                subject_name_by_id[str(sid)] = str(name)

        for item in data.get("data") or []:
            if not isinstance(item, dict):
                continue
            if item.get("type") != "node--class":
                continue
            c = _course_from_jsonapi_node(item, subject_name_by_id=subject_name_by_id)
            if c:
                by_slug.setdefault(c.slug, c)

        nxt = (data.get("links") or {}).get("next") or {}
        url = nxt.get("href") if isinstance(nxt, dict) else None

    return sorted(by_slug.values(), key=lambda c: c.slug)


def fetch_course_index(*, timeout_s: int = 30) -> list[Course]:
    """
    Fetch BT course list by visiting /classes and each /classes/<category> page.
    Returns a list of unique courses (deduped by slug).
    """
    # The /classes pages do not include server-rendered course links; use JSON:API for reliability.
    return fetch_course_index_jsonapi(timeout_s=timeout_s)


def write_fetched_index(*, timeout_s: int = 30, path: Optional[Path] = None) -> Path:
    courses = fetch_course_index(timeout_s=timeout_s)
    data = {
        "version": 1,
        "fetched_at": _now_iso(),
        "source": CLASSES_URL,
        "courses": [
            {"slug": c.slug, "title": c.title, "url": c.url, "category": c.category}
            for c in courses
        ],
    }
    save_index(data, path=path)
    return (path or index_path()).resolve()


def ensure_index_exists(*, timeout_s: int = 30, path: Optional[Path] = None) -> Path:
    p = path or index_path()
    if p.is_file():
        return p
    return write_fetched_index(timeout_s=timeout_s, path=p)


def _looks_like_url(s: str) -> bool:
    return s.startswith("http://") or s.startswith("https://")


def _courses_from_index(data: dict) -> list[Course]:
    courses = []
    for item in data.get("courses", []):
        try:
            courses.append(
                Course(
                    slug=str(item["slug"]),
                    title=str(item.get("title") or item["slug"]),
                    url=str(item["url"]),
                    category=item.get("category"),
                )
            )
        except Exception:
            continue
    return courses


def resolve_course_query(
    query: str, *, index_data: Optional[dict] = None, index_file: Optional[Path] = None
) -> Course:
    """
    Resolve a user query to a single course.
    - URL: returns slug from URL
    - slug-prefix: must match exactly one course by slug startswith (case-insensitive)
    - full slug: works the same as prefix (exact match will be unique)
    """
    q = (query or "").strip()
    if not q:
        raise CourseIndexError("Empty course query.")

    if _looks_like_url(q):
        slug = _course_slug_from_url(q)
        return Course(slug=slug, title=slug, url=q, category=None)

    data = index_data if index_data is not None else load_index(index_file)
    courses = _courses_from_index(data)
    ql = q.lower()
    matches = [c for c in courses if c.slug.lower().startswith(ql)]
    if not matches:
        raise CourseIndexError(f"No courses match slug prefix: {q!r}")
    if len(matches) > 1:
        slugs = ", ".join(sorted(c.slug for c in matches)[:20])
        more = "" if len(matches) <= 20 else f" (+{len(matches) - 20} more)"
        raise CourseIndexError(f"Ambiguous slug prefix {q!r}. Matches: {slugs}{more}")
    return matches[0]

