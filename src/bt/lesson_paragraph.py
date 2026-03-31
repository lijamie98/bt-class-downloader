"""
Extract a single lesson's transcript and outline from course Markdown files, and build
Gemini prompts for paragraphing with inlined outline headings.
"""

from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Optional

_COURSE_TITLE_LINE = re.compile(r"^#\s+(?!Lesson\s+\d+:)(.+)$", re.MULTILINE)
_LESSON_TRANSCRIPT_START = re.compile(r"^# Lesson (\d+):\s*.+$", re.MULTILINE)
_LESSON_OUTLINE_START = re.compile(r"^## Lesson (\d+):\s*.+$", re.MULTILINE)
_LEADING_LESSON_H = re.compile(r"^#{2,6}\s+Lesson\s+\d+:", re.I)
_LEADING_NT_COURSE = re.compile(r"^#{2,6}\s+NT\d+", re.I)
_ROMAN_OUTLINE_SECTION = re.compile(r"^#{2,6}\s+[IVX]+\.\s")


def extract_lesson_h1_line(transcript_md: str, lesson_num: int) -> Optional[str]:
    """The ``# Lesson N: …`` line from the course transcript file, if present."""
    for m in _LESSON_TRANSCRIPT_START.finditer(transcript_md):
        if int(m.group(1)) != lesson_num:
            continue
        return m.group(0).strip()
    return None


def list_lesson_numbers_from_transcript(transcript_md: str) -> list[int]:
    """Unique lesson numbers from ``# Lesson N:`` headings, ascending order."""
    return sorted({int(m.group(1)) for m in _LESSON_TRANSCRIPT_START.finditer(transcript_md)})


def lesson_title_as_h2(h1_line: str) -> str:
    """Transcript uses ``# Lesson N: …``; paragraphed files use that title as heading 2 (``##``)."""
    s = h1_line.strip()
    if s.startswith("# ") and not s.startswith("##"):
        return "#" + s
    return s


def strip_leading_redundant_headings(gemini_md: str) -> str:
    """
    Remove duplicate outline noise from the start of Gemini output: repeated
    ``##/### Lesson N: …``, course/class lines (``NT203: …``), and a lone ``##/###``
    topic line before the first Roman section (``I.``, ``II.``, …).
    """
    lines = gemini_md.splitlines()
    i = 0
    n = len(lines)
    while i < n:
        while i < n and not lines[i].strip():
            i += 1
        if i >= n:
            break
        cur = lines[i].strip()
        if _LEADING_LESSON_H.match(cur) or _LEADING_NT_COURSE.match(cur):
            i += 1
            continue
        # Orphan topic heading (duplicate lesson title) before first I./II. section
        if re.match(r"^#{2,6}\s+", cur) and not _ROMAN_OUTLINE_SECTION.match(cur):
            j = i + 1
            while j < n and not lines[j].strip():
                j += 1
            if j < n and _ROMAN_OUTLINE_SECTION.match(lines[j].strip()):
                i += 1
                continue
        break
    return "\n".join(lines[i:]).strip()


def normalize_outline_starts_at_h3(md: str) -> str:
    """
    Shift heading levels so the shallowest heading in the model output is ``###`` (H3).

    The lesson name is written separately as ``##``; outline sections start at ``###``.
    """
    lines = md.splitlines()
    levels: list[int] = []
    for line in lines:
        m = re.match(r"^(#+)\s", line)
        if m:
            levels.append(len(m.group(1)))
    if not levels:
        return md
    min_level = min(levels)
    if min_level == 3:
        return md
    shift = 3 - min_level
    out: list[str] = []
    for line in lines:
        m = re.match(r"^(#+)\s", line)
        if m:
            old_n = len(m.group(1))
            new_n = old_n + shift
            line = "#" * new_n + line[old_n:]
        out.append(line)
    return "\n".join(out)


def format_paragraph_markdown_file(*, lesson_h1: Optional[str], gemini_body: str) -> str:
    """Full Markdown document: lesson title as ``##``, outline body starting at ``###``."""
    body = strip_leading_redundant_headings(gemini_body.strip())
    body = normalize_outline_starts_at_h3(body)
    if lesson_h1:
        title = lesson_title_as_h2(lesson_h1.strip())
        return f"{title}\n\n{body}\n"
    return f"{body}\n"


def extract_course_title_from_transcript(transcript_md: str) -> Optional[str]:
    """First ``# …`` line that is not ``# Lesson N:`` (course transcript header)."""
    m = _COURSE_TITLE_LINE.search(transcript_md)
    return m.group(1).strip() if m else None


def github_style_heading_id(heading_text: str) -> str:
    """GFM-style fragment id for heading text (after ``##``)."""
    s = heading_text.lower().strip()
    s = re.sub(r"[^\w\s-]", "", s, flags=re.UNICODE)
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"-+", "-", s)
    return s.strip("-")


def _lesson_doc_with_anchor_h2(md_doc: str) -> tuple[str, Optional[tuple[str, str]]]:
    """
    Replace leading ``## Lesson …`` with ``<h2 id="…">…</h2>`` for stable ToC targets.
    Returns ``(document, (link_text, anchor))`` or ``(document, None)``.
    """
    lines = md_doc.splitlines()
    if not lines:
        return md_doc, None
    m = re.match(r"^##\s+(.+)$", lines[0].strip())
    if not m:
        return md_doc, None
    link_text = m.group(1).strip()
    anchor = github_style_heading_id(link_text)
    h2 = f'<h2 id="{anchor}">{html.escape(link_text)}</h2>'
    rest = lines[1:]
    body = "\n".join([h2] + rest) if rest else h2
    return body, (link_text, anchor)


def format_paragraphed_document_with_toc(*, course_title: str, lesson_md_docs: list[str]) -> str:
    """
    Heading 1 course title, ``## Table of contents`` with links, horizontal rule, then lesson bodies.
    Each lesson should start with ``## Lesson N: …`` (from ``format_paragraph_markdown_file``).
    """
    chunks: list[str] = []
    toc: list[tuple[str, str]] = []
    for doc in lesson_md_docs:
        chunk, meta = _lesson_doc_with_anchor_h2(doc)
        chunks.append(chunk)
        if meta:
            toc.append(meta)
    lines = [f"# {course_title}", "", "## Table of contents", ""]
    for link_text, anchor in toc:
        lines.append(f"- [{link_text}](#{anchor})")
    lines.extend(["", "---", ""])
    head = "\n".join(lines)
    body = "\n\n".join(chunks)
    return f"{head}\n{body}\n"


def extract_lesson_transcript_body(transcript_md: str, lesson_num: int) -> Optional[str]:
    """
    Body text for one lesson: content after ``# Lesson N: ...`` until the next ``# Lesson``.
    Excludes the heading line.
    """
    for m in _LESSON_TRANSCRIPT_START.finditer(transcript_md):
        if int(m.group(1)) != lesson_num:
            continue
        start = m.end()
        nxt = _LESSON_TRANSCRIPT_START.search(transcript_md, start)
        end = nxt.start() if nxt else len(transcript_md)
        return transcript_md[start:end].strip()
    return None


def extract_lesson_outline_section(outline_md: str, lesson_num: int) -> Optional[str]:
    """
    Outline block for lesson N: ``## Lesson N:`` through the next ``## Lesson`` or EOF.
    """
    for m in _LESSON_OUTLINE_START.finditer(outline_md):
        if int(m.group(1)) != lesson_num:
            continue
        start = m.start()
        nxt = _LESSON_OUTLINE_START.search(outline_md, m.end())
        end = nxt.start() if nxt else len(outline_md)
        return outline_md[start:end].strip()
    return None


GEMINI_SYSTEM_INSTRUCTION = """Paragraph the lesson
Do not modify the contents
Inline the outline as headings to the output.

The lesson name will be added separately as heading 2 (##); do not output a duplicate lesson title line.
Use heading 3 (###) for the top level of the outline (e.g. I. Introduction, II. …).
Use heading 4 (####) for the next outline level (e.g. A. …), then ##### and so on.
Do not use heading 1 (#) or heading 2 (##) in your output.
"""

BATCH_LESSON_DELIMITER = "---LESSON-END---"

GEMINI_BATCH_SYSTEM_INSTRUCTION = """Paragraph every lesson below, in the same order given.
Do not modify the transcript wording.
For each lesson, inline the outline as headings (### for top level, #### next, etc.).
Do not output a lesson title line (## Lesson N); it will be added separately.
Do not use heading 1 (#) or heading 2 (##) in each lesson's body.
"""


def build_paragraph_prompt(transcription: str, outline: str) -> str:
    return (
        f"{GEMINI_SYSTEM_INSTRUCTION}\n\n"
        "---\n\n"
        "Lesson transcription:\n\n"
        f"{transcription}\n\n"
        "---\n\n"
        "Lesson outline (use to insert ### headings for outline sections; preserve transcript wording):\n\n"
        f"{outline}\n"
    )


def build_batch_paragraph_prompt(lessons: list[tuple[int, str, str]]) -> str:
    """``lessons`` is ``(lesson_num, transcription, outline)`` in order."""
    n = len(lessons)
    delim_block = ""
    if n > 1:
        delim_block = (
            f"\n\nYou must output exactly {n} separate lesson bodies, in the same order as the inputs.\n"
            f"Between lesson 1 and lesson 2, lesson 2 and lesson 3, … through lesson {n - 1} and lesson {n}, "
            f"put exactly one line containing only this text (copy it exactly, nothing else on that line):\n"
            f"{BATCH_LESSON_DELIMITER}\n"
            f"That line must appear exactly {n - 1} times total. Do not merge lessons. "
            f"Do not put {BATCH_LESSON_DELIMITER} after the last lesson.\n"
        )
    parts: list[str] = [GEMINI_BATCH_SYSTEM_INSTRUCTION + delim_block, "\n---\n\n"]
    for num, trans, outline in lessons:
        parts.append(
            f"Lesson {num} — transcription:\n\n{trans}\n\n"
            f"Lesson {num} — outline (use to insert ### headings; preserve transcript wording):\n\n"
            f"{outline}\n\n---\n\n"
        )
    return "".join(parts).rstrip()


def _strip_markdown_fenced_response(text: str) -> str:
    t = text.strip()
    if not t.startswith("```"):
        return t
    lines = t.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def split_batch_paragraph_output(raw: str, expected_count: int) -> list[str]:
    """Split Gemini batch response on ``BATCH_LESSON_DELIMITER``."""
    if expected_count < 1:
        return []
    if expected_count == 1:
        return [_strip_markdown_fenced_response(raw)]

    text = _strip_markdown_fenced_response(raw)
    # Normalize delimiter wrapped in markdown emphasis or backticks
    d = re.escape(BATCH_LESSON_DELIMITER)
    text = re.sub(r"[*_`]*\s*" + d + r"\s*[*_`]*", "\n" + BATCH_LESSON_DELIMITER + "\n", text)

    patterns = [
        re.compile(r"\r?\n\s*" + re.escape(BATCH_LESSON_DELIMITER) + r"\s*\r?\n"),
        re.compile(r"\s+" + re.escape(BATCH_LESSON_DELIMITER) + r"\s+"),
        re.compile(r"\s*" + re.escape(BATCH_LESSON_DELIMITER) + r"\s*"),
    ]
    for pat in patterns:
        parts = [p.strip() for p in pat.split(text) if p.strip()]
        if len(parts) == expected_count:
            return parts

    parts = [p.strip() for p in re.split(r"\s*" + re.escape(BATCH_LESSON_DELIMITER) + r"\s*", text) if p.strip()]
    if len(parts) == expected_count:
        return parts

    raise RuntimeError(
        f"Expected {expected_count} lesson segments after delimiter {BATCH_LESSON_DELIMITER!r}, "
        f"got {len(parts)} (check model output)."
    )


def _generate_gemini_text(api_key: str, prompt: str, model: str) -> str:
    import google.generativeai as genai

    genai.configure(api_key=api_key)
    m = genai.GenerativeModel(model)
    resp = m.generate_content(prompt, generation_config={"temperature": 0.2})
    text = getattr(resp, "text", None)
    if not text and resp.candidates:
        parts = []
        for part in resp.candidates[0].content.parts:
            if hasattr(part, "text") and part.text:
                parts.append(part.text)
        text = "".join(parts) if parts else None
    if not text:
        raise RuntimeError("Gemini returned empty response (blocked or no text).")
    return text.strip()


def run_gemini_paragraph(
    *,
    api_key: str,
    transcription: str,
    outline: str,
    model: str = "gemini-3.1-flash-lite-preview",
) -> str:
    prompt = build_paragraph_prompt(transcription, outline)
    return _generate_gemini_text(api_key, prompt, model)


def run_gemini_paragraph_batch(
    *,
    api_key: str,
    lessons: list[tuple[int, str, str]],
    model: str = "gemini-3.1-flash-lite-preview",
) -> str:
    """
    One or more lessons in one API call. Single lesson uses the single-lesson prompt;
    multiple lessons use a batch prompt and ``BATCH_LESSON_DELIMITER`` between outputs.
    """
    if not lessons:
        raise ValueError("lessons must not be empty")
    if len(lessons) == 1:
        _, t, o = lessons[0]
        return run_gemini_paragraph(api_key=api_key, transcription=t, outline=o, model=model)
    prompt = build_batch_paragraph_prompt(lessons)
    return _generate_gemini_text(api_key, prompt, model)


def resolve_transcript_outline_paths(
    course_slug: str,
    *,
    transcript: Optional[str] = None,
    outline: Optional[str] = None,
) -> tuple[Path, Path]:
    t = Path(transcript) if transcript else Path("transcripts") / f"{course_slug}.md"
    o = Path(outline) if outline else Path("outlines") / f"{course_slug}.outline.md"
    return t, o


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def sanitize_model_for_path(model: str) -> str:
    """Model id safe for use as a single path segment (directory name)."""
    s = model.strip()
    s = re.sub(r"[^a-zA-Z0-9._-]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "model"


def default_paragraph_out_path(course_slug: str, lesson_num: int, *, model: str) -> Path:
    d = sanitize_model_for_path(model)
    return Path("paragraph-outlined") / d / f"{course_slug}.lesson{lesson_num:02d}.paragraph-outlined.md"


def default_paragraph_course_out_path(course_slug: str, *, model: str) -> Path:
    """Single file for all lessons: ``paragraph-outlined/<model>/<slug>.paragraph-outlined.md``."""
    d = sanitize_model_for_path(model)
    return Path("paragraph-outlined") / d / f"{course_slug}.paragraph-outlined.md"
