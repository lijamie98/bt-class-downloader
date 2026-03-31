"""
Remove common BiblicalTraining lesson-page UI text that leaks into scraped transcripts.
"""

from __future__ import annotations

import re
from typing import Optional

# Multi-line "0" / "%" / "Complete" (broken progress indicator)
_UI_PROGRESS_BLOCK = re.compile(
    r"(?:^|\n)\s*0\s*\n\s*%\s*\n\s*Complete\s*(?=\n|$)",
    re.MULTILINE,
)

# Single-line variants
_UI_PROGRESS_ONE_LINE = re.compile(
    r"^\s*0\s*%\s*Complete\s*$",
    re.MULTILINE | re.IGNORECASE,
)


def strip_transcript_ui_noise(text: str) -> str:
    """
    Drop lines/blocks that look like a '0% Complete' lesson progress widget, not speech.
    """
    if not text:
        return text
    t = _UI_PROGRESS_BLOCK.sub("\n", text)
    t = _UI_PROGRESS_ONE_LINE.sub("", t)
    lines = t.splitlines()
    out: list[str] = []
    for ln in lines:
        s = ln.strip()
        if s in {"0", "%"} or s.lower() == "complete":
            continue
        if s.lower() == "scroll down":
            continue
        out.append(ln)
    return "\n".join(out).strip()


# Site appends the full course lesson list (1. Title + short description) after the real transcript.
_LESSON_LIST_START = re.compile(r"^1\.\s*$")

_LESSON_NUM_LINE = re.compile(r"^(\d+)\.\s*$")
# After lesson 36, the site may repeat "Transcription" before the real speech (DOM order).
_TRANSCRIPTION_MARKER = re.compile(r"^transcription$", re.I)


def _next_nonempty_line_index(lines: list[str], start: int, n: int) -> Optional[int]:
    for i in range(start, n):
        if lines[i].strip():
            return i
    return None


def _has_lesson_2_nearby(lines: list[str], j: int, n: int, lookahead: int = 120) -> bool:
    """True if a '2.' lesson header appears soon after a '1.' block (course catalog signature)."""
    end = min(n, j + lookahead)
    for k in range(j + 1, end):
        m = _LESSON_NUM_LINE.match(lines[k].strip())
        if m and int(m.group(1)) == 2:
            return True
    return False


def _skip_desc_until_next_lesson(
    lines: list[str],
    j: int,
    n: int,
    next_num: int,
    *,
    max_lines: int = 50,
) -> Optional[int]:
    """
    Advance past description lines until a standalone 'next_num.' lesson header line.

    Site lesson blurbs are short; if we scan too many lines without finding the next header,
    this is not the course catalog (avoids swallowing real speech as if it were a blurb).
    """
    start = j
    while j < n:
        if j - start > max_lines:
            return None
        m = _LESSON_NUM_LINE.match(lines[j].strip())
        if m:
            found = int(m.group(1))
            if found == next_num:
                return j
            if found < next_num:
                return None
            return None
        j += 1
    return n


def _find_course_catalog_span(lines: list[str], start_j: int, n: int) -> Optional[tuple[int, int]]:
    """
    If start_j begins a full course lesson list (1. … N.), return [start_j, end) line indices.

    Descriptions are not always boilerplate phrasing (e.g. 'Understanding the roots...');
    we only require numbered headers and short gaps between them, matching the site index.
    """
    i = start_j
    for num in range(1, 100):
        if i >= n:
            return None
        m0 = _LESSON_NUM_LINE.match(lines[i].strip())
        if not m0 or int(m0.group(1)) != num:
            return None
        title_i = _next_nonempty_line_index(lines, i + 1, n)
        if title_i is None:
            return None
        desc_start = title_i + 1
        while desc_start < n and not lines[desc_start].strip():
            desc_start += 1
        if desc_start >= n:
            return None
        nxt = _skip_desc_until_next_lesson(lines, desc_start, n, num + 1)
        if nxt is None:
            # Possibly the final lesson in the catalog block: the site often continues with
            # a 'Transcription' marker and then the real speech, so don't strip to EOF.
            scan_end = min(n, desc_start + 400)
            for k in range(desc_start, scan_end):
                if _TRANSCRIPTION_MARKER.match(lines[k].strip()):
                    return (start_j, k + 1)
            return None
        if nxt >= n:
            return (start_j, n)
        i = nxt
    return None


def _find_appended_lesson_catalog_span(lines: list[str]) -> Optional[tuple[int, int]]:
    """
    Find [start, end) line indices for the site-wide lesson list, or None.

    Requires a '1.' block that is followed by '2.' (catalog signature) and a consistent
    1..36 walk so we do not truncate on an early '1.' that is not the full course list.
    """
    n = len(lines)
    for j in range(n):
        if not _LESSON_LIST_START.match(lines[j]):
            continue
        title_i = _next_nonempty_line_index(lines, j + 1, n)
        if title_i is None:
            continue
        if not _has_lesson_2_nearby(lines, j, n):
            continue
        span = _find_course_catalog_span(lines, j, n)
        if span is not None:
            return span
    return None


def _strip_appended_lesson_catalog_looped(text: str) -> str:
    if not text:
        return text
    text = text.strip()
    while True:
        lines = text.splitlines()
        span = _find_appended_lesson_catalog_span(lines)
        if span is None:
            return text
        start, end = span
        text = "\n".join(lines[:start] + lines[end:]).rstrip()


def collapse_duplicate_transcription_segment(text: str) -> str:
    """
    Some lesson pages emit the same paragraph block twice around course navigation (and may
    drop the 'Transcription' marker during catalog stripping). If the text is two identical
    copies of k lines plus an optional trailing 'Lessons' line, keep one copy.
    """
    if not text:
        return text
    lines = text.splitlines()
    while lines and lines[-1].strip() == "Lessons":
        lines.pop()
    n = len(lines)
    for k in range(n // 2, 2, -1):
        if 2 * k <= n and lines[:k] == lines[k : 2 * k]:
            return "\n".join(lines[:k]).rstrip()
    return "\n".join(lines).rstrip()


def strip_appended_lesson_catalog(text: str) -> str:
    """
    Remove the course lesson list (all lessons with short descriptions) sometimes scraped
    from lesson pages, then collapse an immediately duplicated paragraph block (same lines
    twice in a row, optional trailing 'Lessons') when the site repeats speech around nav.
    """
    t = _strip_appended_lesson_catalog_looped(text)
    return collapse_duplicate_transcription_segment(t)
