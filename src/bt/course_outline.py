"""
Extract the class outline from a BiblicalTraining course overview HTML page.

Primary source: __NEXT_DATA__ JSON (`lessonNode.field_outline` or deep search).

Some courses (e.g. preview lesson as lessonNode) omit per-lesson outlines in the embedded
payload; those are loaded from Drupal JSON:API `node/class` with `include=field_lessons`.
"""

from __future__ import annotations

import html as html_module
import json
import os
import re
from typing import Any, Optional
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

from bt.paths import OUTLINES_DIR

_OUT_CLASS = re.compile(r"^out-(\d+)$")


class OutlineExtractionError(Exception):
    """Could not obtain a non-empty outline from the page or JSON:API."""


def parse_next_data_page_props(html: str) -> Optional[dict[str, Any]]:
    m = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.+?)</script>',
        html,
        re.DOTALL,
    )
    if not m:
        return None
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return None
    pp = data.get("props", {}).get("pageProps")
    return pp if isinstance(pp, dict) else None


def class_jsonapi_self_href(html: str) -> Optional[str]:
    """Drupal JSON:API self URL for the class node (from embedded classNode.links.self.href)."""
    pp = parse_next_data_page_props(html)
    if not pp:
        return None
    cn = pp.get("classNode")
    if not isinstance(cn, dict):
        return None
    href = (cn.get("links") or {}).get("self", {}).get("href")
    if isinstance(href, str) and href.startswith("http"):
        return href
    return None


def _jsonapi_url_with_include(class_self_href: str, include: str) -> str:
    p = urlparse(class_self_href)
    q = parse_qs(p.query)
    q["include"] = [include]
    pairs: list[tuple[str, str]] = []
    for k in sorted(q.keys()):
        for v in q[k]:
            pairs.append((k, v))
    new_query = urlencode(pairs)
    return urlunparse((p.scheme, p.netloc, p.path, p.params, new_query, p.fragment))


def lesson_canonical_urls_by_slug(
    class_self_href: str,
    *,
    origin: str,
    timeout_s: float = 30,
) -> dict[str, str]:
    """
    Map lesson path slug (last segment of path.alias) -> full URL on site.

    Course overview pages sometimes link /learn/{program}/... while Drupal's canonical
    path.alias uses a different program segment; fetching the wrong URL can serve a
    preview shell instead of the real lesson (empty transcript).
    """
    url = _jsonapi_url_with_include(class_self_href, "field_lessons")
    headers = {
        "Accept": "application/vnd.api+json",
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
    }
    try:
        r = requests.get(url, headers=headers, timeout=timeout_s)
        r.raise_for_status()
        payload = r.json()
    except (requests.RequestException, json.JSONDecodeError, ValueError, TypeError):
        return {}

    included = payload.get("included") or []
    if not isinstance(included, list):
        return {}

    base = origin.rstrip("/")
    out: dict[str, str] = {}
    for ent in included:
        if not isinstance(ent, dict) or ent.get("type") != "node--lesson":
            continue
        attrs = ent.get("attributes")
        if not isinstance(attrs, dict):
            continue
        path = attrs.get("path")
        if not isinstance(path, dict):
            continue
        alias = path.get("alias")
        if not isinstance(alias, str) or not alias.startswith("/"):
            continue
        slug = alias.rstrip("/").split("/")[-1]
        if slug:
            out[slug] = f"{base}{alias}"
    return out


def aggregate_outline_markdown_from_class_jsonapi(
    class_self_href: str,
    *,
    timeout_s: float = 30,
) -> str:
    """
    Fetch class with included lessons and concatenate each lesson's field_outline as Markdown.

    Each lesson uses a level-2 heading: ## Lesson {n}: {title}.
    """
    url = _jsonapi_url_with_include(class_self_href, "field_lessons")
    headers = {
        "Accept": "application/vnd.api+json",
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
    }
    r = requests.get(url, headers=headers, timeout=timeout_s)
    try:
        r.raise_for_status()
    except requests.HTTPError as e:
        raise OutlineExtractionError(f"JSON:API request failed ({r.status_code}): {url}") from e

    try:
        payload = r.json()
    except json.JSONDecodeError as e:
        raise OutlineExtractionError("JSON:API response was not valid JSON.") from e

    data = payload.get("data")
    if not isinstance(data, dict):
        raise OutlineExtractionError("JSON:API payload missing data object.")

    rels = (((data.get("relationships") or {}).get("field_lessons") or {}).get("data")) or []
    if not isinstance(rels, list):
        rels = []

    included = payload.get("included") or []
    by_id: dict[str, dict[str, Any]] = {}
    if isinstance(included, list):
        for ent in included:
            if isinstance(ent, dict) and ent.get("type") == "node--lesson" and ent.get("id"):
                by_id[str(ent["id"])] = ent

    parts: list[str] = []
    for lesson_index, ref in enumerate(rels, start=1):
        if not isinstance(ref, dict):
            continue
        lid = ref.get("id")
        if not isinstance(lid, str):
            continue
        ent = by_id.get(lid)
        if not ent:
            continue
        attrs = ent.get("attributes")
        if not isinstance(attrs, dict):
            continue
        title = (attrs.get("title") or "").strip() or "Lesson"
        fo = attrs.get("field_outline")
        if not isinstance(fo, dict):
            continue
        raw = (fo.get("processed") or fo.get("value") or "").strip()
        if not raw:
            continue
        md = html_outline_to_markdown(raw).strip()
        if md:
            ln = attrs.get("field_lesson_number")
            label_num = ln if isinstance(ln, int) and ln >= 1 else lesson_index
            parts.append(f"## Lesson {label_num}: {title}\n\n{md}")

    return "\n\n".join(parts)


def build_course_outline_markdown(
    html: str,
    *,
    timeout_s: float = 30,
    course_title: Optional[str] = None,
) -> str:
    """
    Return Markdown for the full class outline, or raise OutlineExtractionError.

    Single embedded outline is prefixed with ``## Lesson 1: {course_title}`` when ``course_title``
    is set (otherwise "Class").
    """
    href = class_jsonapi_self_href(html)
    if href:
        agg = aggregate_outline_markdown_from_class_jsonapi(href, timeout_s=timeout_s).strip()
        # Prefer per-lesson outlines when available.
        if agg:
            return agg

    oh = extract_outline_html_from_course_page(html)
    if oh:
        md = html_outline_to_markdown(oh).strip()
        if md:
            head = course_title or "Class"
            return f"## Lesson 1: {head}\n\n{md}"

    raise OutlineExtractionError(
        "No per-lesson outlines via JSON:API and no outline in embedded __NEXT_DATA__."
    )


def _outline_dict_from_page_props(page_props: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Prefer lessonNode (first lesson on course page), then classNode."""
    ln = page_props.get("lessonNode")
    if isinstance(ln, dict):
        fo = ln.get("field_outline")
        if isinstance(fo, dict) and _outline_dict_has_html(fo):
            return fo
    cn = page_props.get("classNode")
    if isinstance(cn, dict):
        fo = cn.get("field_outline")
        if isinstance(fo, dict) and _outline_dict_has_html(fo):
            return fo
    return _find_field_outline_deep(page_props)


def _outline_dict_has_html(fo: dict[str, Any]) -> bool:
    h = (fo.get("processed") or fo.get("value") or "").strip()
    return bool(h)


def _find_field_outline_deep(obj: Any, depth: int = 0) -> Optional[dict[str, Any]]:
    if depth > 12:
        return None
    if isinstance(obj, dict):
        if "field_outline" in obj:
            fo = obj["field_outline"]
            if isinstance(fo, dict) and _outline_dict_has_html(fo):
                return fo
        for v in obj.values():
            r = _find_field_outline_deep(v, depth + 1)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for x in obj:
            r = _find_field_outline_deep(x, depth + 1)
            if r is not None:
                return r
    return None


def extract_outline_html_from_course_page(html: str) -> Optional[str]:
    """
    Return raw HTML for the class outline from __NEXT_DATA__, or None if missing/empty.
    """
    page_props = parse_next_data_page_props(html)
    if not page_props:
        return None
    fo = _outline_dict_from_page_props(page_props)
    if not fo:
        return None
    raw = (fo.get("processed") or fo.get("value") or "").strip()
    return raw or None


def _outline_level_from_classes(classes: list[str]) -> int:
    for c in classes:
        m = _OUT_CLASS.match(str(c))
        if m:
            return int(m.group(1))
    return 0


# Match <p … class="… out-N …"> … </p> (handles attributes in any order)
_OUT_P_RE = re.compile(
    r'<p\b[^>]*\bclass="([^"]*)"[^>]*>(.*?)</p>',
    re.DOTALL | re.IGNORECASE,
)


def _strip_inline_html_to_text(fragment: str) -> str:
    if not fragment or not fragment.strip():
        return ""
    soup = BeautifulSoup(fragment, "html.parser")
    t = soup.get_text(" ", strip=True)
    t = html_module.unescape(t)
    return re.sub(r"\s+", " ", t).strip()


def html_outline_to_markdown(html_fragment: str) -> str:
    """
    Convert outline HTML (<p class="out-1"> …) to nested Markdown bullets; strip all tags.
    Uses regex segments so malformed/nested <p> markup still yields separate outline lines.
    """
    if not html_fragment.strip():
        return ""

    raw = html_fragment.strip()
    lines: list[str] = []

    for m in _OUT_P_RE.finditer(raw):
        class_attr = m.group(1) or ""
        inner_html = m.group(2) or ""
        level = _outline_level_from_classes(class_attr.split())
        text = _strip_inline_html_to_text(inner_html)
        if not text:
            continue
        if level >= 1:
            pad = "  " * (level - 1)
            lines.append(f"{pad}- {text}")
        else:
            lines.append(text)

    if lines:
        return "\n\n".join(lines)

    # Fallback: html.parser on wrapped fragment (some outlines omit closing tags consistently)
    soup = BeautifulSoup(f"<div>{raw}</div>", "html.parser")
    for p in soup.find_all("p"):
        text = p.get_text(" ", strip=True)
        text = html_module.unescape(text)
        if not text:
            continue
        classes = [str(c) for c in (p.get("class") or [])]
        level = _outline_level_from_classes(classes)
        if level >= 1:
            pad = "  " * (level - 1)
            lines.append(f"{pad}- {text}")
        else:
            lines.append(text)

    if lines:
        return "\n\n".join(lines)

    plain = soup.get_text("\n", strip=True)
    plain = html_module.unescape(plain)
    return plain.strip()


def default_outline_path(transcript_path: str) -> str:
    """Course transcript path -> data/outlines/<basename>.outline.md (alongside default transcripts)."""
    root, ext = os.path.splitext(transcript_path)
    base = os.path.basename(root)
    if not ext:
        ext = ".md"
    return str(OUTLINES_DIR / f"{base}.outline{ext}")
