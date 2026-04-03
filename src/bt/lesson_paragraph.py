"""
Extract a single lesson's transcript and outline from course Markdown files, and build
Gemini prompts for paragraphing with inlined outline headings.
"""

from __future__ import annotations

import re
import warnings
from pathlib import Path
from typing import Literal, Optional

from bt.paths import (
    EXPLAIN_CN_DIR,
    EXPLAIN_ZH_DIR,
    PARAGRAPH_DIR,
    PARAGRAPH_OUTLINED_DIR,
    OUTLINES_DIR,
    TRANSCRIPTS_DIR,
)

_COURSE_TITLE_LINE = re.compile(r"^#\s+(?!Lesson\s+\d+:)(.+)$", re.MULTILINE)
_LESSON_TRANSCRIPT_START = re.compile(r"^# Lesson (\d+):\s*.+$", re.MULTILINE)
_LESSON_OUTLINE_START = re.compile(r"^## Lesson (\d+):\s*.+$", re.MULTILINE)
_LEADING_LESSON_H = re.compile(r"^#{2,6}\s+Lesson\s+\d+:", re.I)
_LEADING_NT_COURSE = re.compile(r"^#{2,6}\s+NT\d+", re.I)
_ROMAN_OUTLINE_SECTION = re.compile(r"^#{2,6}\s+[IVX]+\.\s")
_HEADING_TOC_LINE = re.compile(r"^(#{2,6})\s+(.+)$")


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


def format_plain_paragraph_markdown_file(*, lesson_h1: Optional[str], gemini_body: str) -> str:
    """Transcript-only paragraphing: strip duplicate headings; no outline H3 normalization."""
    body = strip_leading_redundant_headings(gemini_body.strip())
    if lesson_h1:
        title = lesson_title_as_h2(lesson_h1.strip())
        return f"{title}\n\n{body}\n"
    return f"{body}\n"


_EXPLAIN_ZH_H2_HTML = re.compile(r"<!--\s*explain-zh-h2:\s*(.+?)\s*-->", re.DOTALL)
_EXPLAIN_CN_H2_HTML = re.compile(r"<!--\s*explain-cn-h2:\s*(.+?)\s*-->", re.DOTALL)


def format_chinese_explanation_markdown_file(
    *,
    lesson_h1: Optional[str],
    gemini_body: str,
    variant: Literal["zh", "cn"] = "zh",
) -> str:
    """
    Like ``format_paragraph_markdown_file`` but prefers bilingual ``##`` from an HTML comment in the model output:

    - Traditional: ``<!-- explain-zh-h2: Lesson N: … (English) -->``
    - Simplified: ``<!-- explain-cn-h2: Lesson N: … (English) -->``

    If that comment is missing, falls back to the English lesson line as ``##``.
    """
    text = gemini_body.strip()
    h2_line: Optional[str] = None
    pat = _EXPLAIN_CN_H2_HTML if variant == "cn" else _EXPLAIN_ZH_H2_HTML
    m = pat.search(text)
    if m:
        inner = " ".join(m.group(1).split())
        if inner:
            h2_line = f"## {inner}"
        text = (text[: m.start()] + text[m.end() :]).strip()
    body = strip_leading_redundant_headings(text)
    body = normalize_outline_starts_at_h3(body)
    if h2_line is None and lesson_h1:
        h2_line = lesson_title_as_h2(lesson_h1.strip())
    if h2_line:
        return f"{h2_line}\n\n{body}\n"
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


def _allocate_anchor_slug(base_slug: str, counts: dict[str, int]) -> str:
    """GitHub-style duplicate heading ids: foo, foo-1, foo-2, …"""
    n = counts.get(base_slug, 0)
    counts[base_slug] = n + 1
    if n == 0:
        return base_slug
    return f"{base_slug}-{n}"


def _parse_heading_toc_entries(md: str) -> list[tuple[int, str, str]]:
    """
    Each ``##`` … ``######`` line becomes ``(level, heading_plain_text, fragment_id)`` in document order.
    """
    slug_counts: dict[str, int] = {}
    out: list[tuple[int, str, str]] = []
    for line in md.splitlines():
        m = _HEADING_TOC_LINE.match(line.strip())
        if not m:
            continue
        level = len(m.group(1))
        text = m.group(2).strip()
        text = re.sub(r"\s+#+\s*$", "", text).strip()
        base = github_style_heading_id(text)
        if not base:
            base = "heading"
        anchor = _allocate_anchor_slug(base, slug_counts)
        out.append((level, text, anchor))
    return out


def format_paragraphed_document_with_toc(*, course_title: str, lesson_md_docs: list[str]) -> str:
    """
    Heading 1 course title, ``## Table of contents`` with nested links to every ``##``–``######``
    heading in the combined document, horizontal rule, then bodies.
    Each lesson should start with ``## Lesson N: …`` (from ``format_paragraph_markdown_file``).
    """
    body = "\n\n".join(lesson_md_docs)
    entries = _parse_heading_toc_entries(body)

    lines = [f"# {course_title}", "", "## Table of contents", ""]
    for level, link_text, anchor in entries:
        indent = "  " * max(0, level - 2)
        lines.append(f"{indent}- [{link_text}](#{anchor})")
    lines.extend(["", "---", ""])
    head = "\n".join(lines)
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


GEMINI_SYSTEM_INSTRUCTION = """Paragraph the lesson.
Do not modify the contents.
Inline the outline as headings to the output.

The lesson name will be added separately as heading 2 (##); do not output a duplicate lesson title line.
Use heading 3 (###) for the top level of the outline (e.g. I. Introduction, II. …).
Use heading 4 (####) for the next outline level (e.g. A. …), then ##### and so on.
Do not use heading 1 (#) or heading 2 (##) in your output.
"""

GEMINI_SYSTEM_INSTRUCTION_TRANSCRIPT_ONLY = """Paragraph the lesson.
Do not modify the contents.
No headings for the paragraphs.
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


def build_paragraph_transcript_only_prompt(transcription: str) -> str:
    return (
        f"{GEMINI_SYSTEM_INSTRUCTION_TRANSCRIPT_ONLY}\n\n"
        "---\n\n"
        "Lesson transcription:\n\n"
        f"{transcription}\n"
    )


GEMINI_SYSTEM_INSTRUCTION_EXPLAIN_ZH = """Task:
- Read the lesson (transcription below).
- Read the outline of the lesson (below).
- Write a **substantial, study-guide-level** explanation: your goal is depth and clarity, not a short summary. Err on the side of **more** explanation when the transcript gives enough material.

Depth and coverage (prioritize these):
- **Unpack the teacher’s reasoning**: not only *what* was said, but *why* it matters, how it connects to earlier or later points in the same lesson, and what a student might misunderstand without help.
- **Define and situate terms**: when a technical or Greek/English term appears, explain it in Traditional Chinese with enough context that a reader new to the topic can follow; keep the original term visible.
- **Use multiple paragraphs per section** whenever the transcript supports it: one-sentence sections are too thin unless the point is truly trivial.
- **Add helpful bridges**: short transitions that show how subtopics fit together (cause/effect, contrast, sequence).
- If the teacher gives an illustration, story, or aside, **integrate it** and say what lesson point it supports.

Language:
- Use Traditional Chinese (中文, 繁體) for the detailed explanation. Do not use Simplified Chinese.
- For important terminology, retain the original English and Greek vocabulary (Latin or Greek script as given); you may add a short Chinese gloss in parentheses when helpful.
- For Bible and theological terminology in Chinese, prefer wording and standard terms associated with **Reformed theology** (改革宗 / 歸正神學), unless the teacher clearly follows another tradition in the lecture.

Structure:
- If the lesson follows the outline closely, structure your explanation to follow that outline (mirror it with your section headings).
- If the lesson does not follow the outline closely, do not force the outline: structure your explanation according to what the teacher actually taught, in order, so the reader still gets a clear “map” of the lesson.
- Include a short note stating whether the provided outline was followed. Put it in a Markdown blockquote at the very start of your output (before any section headings), in Traditional Chinese:
> **大綱對照：**
> (whether the outline was followed and briefly why)

Examples and Scripture (be thorough):
- For **every example** the teacher gives: state the example, unpack it step by step, state the takeaway, and link it explicitly to the argument it supports.
- For **every Bible verse and reference**: give literary/historical context as needed, summarize the force of the wording where relevant, and explain how the teacher uses it in this lesson (not only the citation text).

Bilingual lesson heading (required):
- After the 大綱對照 blockquote, on its own line, output exactly one HTML comment (the tool turns this into ``##``):
  <!-- explain-zh-h2: Lesson N: 繁體中文標題 (English lesson title) -->
  Use the real lesson number N. The Traditional Chinese part should be a concise translation of the lesson topic. The English part in parentheses must match the official lesson title given above (same wording as after ``Lesson N:``).
- Do **not** follow this with a ``###`` heading that only repeats the same topic—that would duplicate the merged title.

Formatting:
- Do not output heading 1 (#) or raw heading 2 (##) in the prose; the ``##`` line is produced from the HTML comment.
- Use heading 3 (###) for the first real section onward, heading 4 (####) for subsections, then ##### and so on as needed.
"""


GEMINI_SYSTEM_INSTRUCTION_EXPLAIN_CN = """Task:
- Read the lesson (transcription below).
- Read the outline of the lesson (below).
- Write a **substantial, study-guide-level** explanation: your goal is depth and clarity, not a short summary. Err on the side of **more** explanation when the transcript gives enough material.

Depth and coverage (prioritize these):
- **Unpack the teacher’s reasoning**: not only *what* was said, but *why* it matters, how it connects to earlier or later points in the same lesson, and what a student might misunderstand without help.
- **Define and situate terms**: when a technical or Greek/English term appears, explain it in Simplified Chinese with enough context that a reader new to the topic can follow; keep the original term visible.
- **Use multiple paragraphs per section** whenever the transcript supports it: one-sentence sections are too thin unless the point is truly trivial.
- **Add helpful bridges**: short transitions that show how subtopics fit together (cause/effect, contrast, sequence).
- If the teacher gives an illustration, story, or aside, **integrate it** and say what lesson point it supports.

Language:
- Use Simplified Chinese (简体中文) for the detailed explanation. Do not use Traditional Chinese.
- For important terminology, retain the original English and Greek vocabulary (Latin or Greek script as given); you may add a short Chinese gloss in parentheses when helpful.
- For Bible and theological terminology in Chinese, prefer wording and standard terms associated with **Reformed theology** (改革宗 / 归正神学), unless the teacher clearly follows another tradition in the lecture.

Structure:
- If the lesson follows the outline closely, structure your explanation to follow that outline (mirror it with your section headings).
- If the lesson does not follow the outline closely, do not force the outline: structure your explanation according to what the teacher actually taught, in order, so the reader still gets a clear “map” of the lesson.
- Include a short note stating whether the provided outline was followed. Put it in a Markdown blockquote at the very start of your output (before any section headings), in Simplified Chinese:
> **大纲对照：**
> (whether the outline was followed and briefly why)

Examples and Scripture (be thorough):
- For **every example** the teacher gives: state the example, unpack it step by step, state the takeaway, and link it explicitly to the argument it supports.
- For **every Bible verse and reference**: give literary/historical context as needed, summarize the force of the wording where relevant, and explain how the teacher uses it in this lesson (not only the citation text).

Bilingual lesson heading (required):
- After the 大纲对照 blockquote, on its own line, output exactly one HTML comment (the tool turns this into ``##``):
  <!-- explain-cn-h2: Lesson N: 简体中文标题 (English lesson title) -->
  Use the real lesson number N. The Simplified Chinese part should be a concise translation of the lesson topic. The English part in parentheses must match the official lesson title given above (same wording as after ``Lesson N:``).
- Do **not** follow this with a ``###`` heading that only repeats the same topic—that would duplicate the merged title.

Formatting:
- Do not output heading 1 (#) or raw heading 2 (##) in the prose; the ``##`` line is produced from the HTML comment.
- Use heading 3 (###) for the first real section onward, heading 4 (####) for subsections, then ##### and so on as needed.
"""


def build_chinese_explanation_prompt(
    transcription: str,
    outline: str,
    *,
    lesson_h1_line: Optional[str] = None,
    simplified: bool = False,
) -> str:
    official = ""
    if lesson_h1_line and lesson_h1_line.strip():
        official = (
            "Official lesson title (verbatim—use this lesson number and English title inside the HTML comment):\n\n"
            f"{lesson_h1_line.strip()}\n\n"
            "---\n\n"
        )
    system = GEMINI_SYSTEM_INSTRUCTION_EXPLAIN_CN if simplified else GEMINI_SYSTEM_INSTRUCTION_EXPLAIN_ZH
    kind = "Simplified Chinese" if simplified else "Traditional Chinese"
    return (
        f"{system}\n\n"
        "---\n\n"
        f"{official}"
        "Lesson (transcription):\n\n"
        f"{transcription}\n\n"
        "---\n\n"
        "Outline of the lesson:\n\n"
        f"{outline}\n\n"
        "---\n\n"
        f"Now produce the {kind} explanation. Aim for a long-form study guide: "
        "dense with explanation, light on generic overview sentences.\n"
    )


def _generate_gemini_text(
    api_key: str,
    prompt: str,
    model: str,
    *,
    temperature: float = 0.2,
) -> str:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FutureWarning)
        import google.generativeai as genai

    genai.configure(api_key=api_key)
    m = genai.GenerativeModel(model)
    resp = m.generate_content(prompt, generation_config={"temperature": temperature})
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


def run_gemini_paragraph_transcript_only(
    *,
    api_key: str,
    transcription: str,
    model: str = "gemini-3.1-flash-lite-preview",
) -> str:
    prompt = build_paragraph_transcript_only_prompt(transcription)
    return _generate_gemini_text(api_key, prompt, model)


def run_gemini_chinese_explanation(
    *,
    api_key: str,
    transcription: str,
    outline: str,
    model: str = "gemini-3.1-flash-lite-preview",
    lesson_h1_line: Optional[str] = None,
    simplified: bool = False,
) -> str:
    prompt = build_chinese_explanation_prompt(
        transcription, outline, lesson_h1_line=lesson_h1_line, simplified=simplified
    )
    # Slightly higher temperature helps varied, expansive explanatory prose; paragraphing stays at default 0.2.
    return _generate_gemini_text(api_key, prompt, model, temperature=0.35)


def resolve_transcript_outline_paths(
    course_slug: str,
    *,
    transcript: Optional[str] = None,
    outline: Optional[str] = None,
) -> tuple[Path, Path]:
    t = Path(transcript) if transcript else TRANSCRIPTS_DIR / f"{course_slug}.md"
    o = Path(outline) if outline else OUTLINES_DIR / f"{course_slug}.outline.md"
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
    return PARAGRAPH_OUTLINED_DIR / d / f"{course_slug}.lesson{lesson_num:02d}.paragraph-outlined.md"


def default_paragraph_course_out_path(course_slug: str, *, model: str) -> Path:
    """Single file for all lessons: ``data/paragraph-outlined/<model>/<slug>.paragraph-outlined.md``."""
    d = sanitize_model_for_path(model)
    return PARAGRAPH_OUTLINED_DIR / d / f"{course_slug}.paragraph-outlined.md"


def default_plain_paragraph_out_path(course_slug: str, lesson_num: int, *, model: str) -> Path:
    d = sanitize_model_for_path(model)
    return PARAGRAPH_DIR / d / f"{course_slug}.lesson{lesson_num:02d}.paragraph.md"


def default_plain_paragraph_course_out_path(course_slug: str, *, model: str) -> Path:
    """Single file for all lessons: ``data/paragraph/<model>/<slug>.paragraph.md``."""
    d = sanitize_model_for_path(model)
    return PARAGRAPH_DIR / d / f"{course_slug}.paragraph.md"


def default_explain_zh_out_path(course_slug: str, lesson_num: int, *, model: str) -> Path:
    d = sanitize_model_for_path(model)
    return EXPLAIN_ZH_DIR / d / f"{course_slug}.lesson{lesson_num:02d}.zh.md"


def default_explain_zh_course_out_path(course_slug: str, *, model: str) -> Path:
    """Single file for all lessons: ``data/explain-zh/<model>/<slug>.zh.md``."""
    d = sanitize_model_for_path(model)
    return EXPLAIN_ZH_DIR / d / f"{course_slug}.zh.md"


def default_explain_cn_out_path(course_slug: str, lesson_num: int, *, model: str) -> Path:
    d = sanitize_model_for_path(model)
    return EXPLAIN_CN_DIR / d / f"{course_slug}.lesson{lesson_num:02d}.cn.md"


def default_explain_cn_course_out_path(course_slug: str, *, model: str) -> Path:
    """Single file for all lessons: ``data/explain-cn/<model>/<slug>.cn.md``."""
    d = sanitize_model_for_path(model)
    return EXPLAIN_CN_DIR / d / f"{course_slug}.cn.md"
