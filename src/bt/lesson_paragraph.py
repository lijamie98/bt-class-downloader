"""
Extract a single lesson's transcript and outline from course Markdown files, and build
Gemini prompts for paragraphing with inlined outline headings.
"""

from __future__ import annotations

import re
import warnings
from pathlib import Path
from typing import Literal, Optional

from bt.paths import course_dir, course_outline_path, course_transcript_path

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


# Accept legacy ``explain-*-h2`` and current ``study-note-*-h2`` comments in existing Markdown.
_STUDY_NOTE_ZH_H2_HTML = re.compile(
    r"<!--\s*(?:explain-zh-h2|study-note-zh-h2):\s*(.+?)\s*-->", re.DOTALL
)
_STUDY_NOTE_CN_H2_HTML = re.compile(
    r"<!--\s*(?:explain-cn-h2|study-note-cn-h2):\s*(.+?)\s*-->", re.DOTALL
)


def split_plain_paragraph_course_into_lessons(md: str) -> list[tuple[int, str]]:
    """Split ``courses/<slug>/paragraph/…`` course Markdown on ``## Lesson N:`` headings."""
    matches = list(_LESSON_OUTLINE_START.finditer(md))
    if not matches:
        return []
    out: list[tuple[int, str]] = []
    for i, m in enumerate(matches):
        n = int(m.group(1))
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(md)
        chunk = md[start:end].strip()
        out.append((n, chunk))
    return out


def format_chinese_study_note_markdown_file(
    *,
    lesson_h1: Optional[str],
    gemini_body: str,
    variant: Literal["zh", "cn"] = "zh",
) -> str:
    """
    Like ``format_paragraph_markdown_file`` but prefers bilingual ``##`` from an HTML comment in the model output:

    - Traditional: ``<!-- study-note-zh-h2: Lesson N: … (English) -->`` (legacy: ``explain-zh-h2``)
    - Simplified: ``<!-- study-note-cn-h2: Lesson N: … (English) -->`` (legacy: ``explain-cn-h2``)

    If that comment is missing, falls back to the English lesson line as ``##``.
    """
    text = gemini_body.strip()
    h2_line: Optional[str] = None
    pat = _STUDY_NOTE_CN_H2_HTML if variant == "cn" else _STUDY_NOTE_ZH_H2_HTML
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


_TRANSLATE_ZH_H2_HTML = re.compile(r"<!--\s*translate-zh-h2:\s*(.+?)\s*-->", re.DOTALL)
_TRANSLATE_CN_H2_HTML = re.compile(r"<!--\s*translate-cn-h2:\s*(.+?)\s*-->", re.DOTALL)
_LESSON_NUM_FROM_H2 = re.compile(r"^##\s+Lesson\s+(\d+)\s*:", re.I | re.MULTILINE)
_LESSON_DUP_H3_ZH = re.compile(r"^###\s+第\s*(\d+)\s*[课課][:：\uFF1A]?\s*.*$")


def lesson_num_from_h2_line(line: Optional[str]) -> Optional[int]:
    if not line or not line.strip():
        return None
    m = _LESSON_NUM_FROM_H2.match(line.strip())
    return int(m.group(1)) if m else None


def strip_duplicate_chinese_lesson_h3(body: str, *, lesson_num: int) -> str:
    """
    Remove a leading ``###`` line that repeats the lesson title (e.g. ``### 第 3 課：…`` / ``### 第14课：…``).
    The model sometimes inserts these when translating plain paragraph lessons that already have ``## Lesson N:``.
    """
    lines = body.splitlines()
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i >= len(lines):
        return body
    m = _LESSON_DUP_H3_ZH.match(lines[i].strip())
    if m and int(m.group(1)) == lesson_num:
        i += 1
        while i < len(lines) and not lines[i].strip():
            i += 1
        return "\n".join(lines[i:]).strip()
    return body


def format_chinese_translation_markdown_file(
    *,
    lesson_h2_line: Optional[str],
    gemini_body: str,
    variant: Literal["zh", "cn"] = "zh",
) -> str:
    """
    Bilingual ``##`` from HTML comment in model output:

    - ``<!-- translate-zh-h2: Lesson N: … (English) -->``
    - ``<!-- translate-cn-h2: Lesson N: … (English) -->``

    Falls back to ``lesson_h2_line`` (e.g. ``## Lesson N: …`` from the English source).
    """
    text = gemini_body.strip()
    h2_line: Optional[str] = None
    pat = _TRANSLATE_CN_H2_HTML if variant == "cn" else _TRANSLATE_ZH_H2_HTML
    m = pat.search(text)
    if m:
        inner = " ".join(m.group(1).split())
        if inner:
            h2_line = f"## {inner}"
        text = (text[: m.start()] + text[m.end() :]).strip()
    body = strip_leading_redundant_headings(text)
    body = normalize_outline_starts_at_h3(body)
    if h2_line is None and lesson_h2_line:
        h2_line = lesson_h2_line.strip()
    ref_h2 = h2_line or (lesson_h2_line.strip() if lesson_h2_line else None)
    ln = lesson_num_from_h2_line(ref_h2)
    if ln is not None:
        body = strip_duplicate_chinese_lesson_h3(body, lesson_num=ln)
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


GEMINI_SYSTEM_INSTRUCTION = """Paragraph the lesson using the outline structure.

Transcript wording (non-negotiable):
- The spoken text in your output must be **verbatim** from the lesson transcription below: same words, same order, same spelling and punctuation (do not “fix,” paraphrase, summarize, expand, shorten, translate, or polish).
- Under each outline section, paste the corresponding transcript sentences **unchanged** except for paragraph breaks (blank lines) where helpful.
- Do **not** replace the teacher’s wording with your own.

Inline the outline as headings to the output.

The lesson name will be added separately as heading 2 (##); do not output a duplicate lesson title line.
Use heading 3 (###) for the top level of the outline (e.g. I. Introduction, II. …).
Use heading 4 (####) for the next outline level (e.g. A. …), then ##### and so on.
Do not use heading 1 (#) or heading 2 (##) in your output.
"""


GEMINI_SYSTEM_INSTRUCTION_TRANSCRIPT_ONLY = """Your only job is to **add paragraph breaks** to the lesson transcription.

Transcript wording (non-negotiable):
- Reproduce the transcription **verbatim**: identical wording, order, spelling, and punctuation. Do **not** paraphrase, summarize, expand, shorten, “correct” grammar, translate, or rephrase.
- Do **not** reorder, merge, or split sentences except by inserting blank lines between paragraphs.
- You may insert **blank lines** between coherent paragraphs only. No headings, no bullet lists unless they appear verbatim in the source.

Output: plain text paragraphs separated by blank lines—nothing else.
"""


def build_paragraph_prompt(transcription: str, outline: str) -> str:
    return (
        f"{GEMINI_SYSTEM_INSTRUCTION}\n\n"
        "---\n\n"
        "Lesson transcription:\n\n"
        f"{transcription}\n\n"
        "---\n\n"
        "Lesson outline (insert ###+ headings to match sections; transcript text under each part must stay verbatim):\n\n"
        f"{outline}\n\n"
        "---\n\n"
        "Output the paragraphed Markdown. Transcript wording must remain verbatim.\n"
    )


def build_paragraph_transcript_only_prompt(transcription: str) -> str:
    return (
        f"{GEMINI_SYSTEM_INSTRUCTION_TRANSCRIPT_ONLY}\n\n"
        "---\n\n"
        "Lesson transcription:\n\n"
        f"{transcription}\n\n"
        "---\n\n"
        "Output the same text verbatim with only blank lines between paragraphs added.\n"
    )


GEMINI_SYSTEM_INSTRUCTION_STUDY_NOTE_ZH = """Task:
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
- **Voice (required):** Explain **from the teacher’s perspective**, as if **you are the instructor** speaking to the class—use **first person** and **direct address** (我們、我、你們、你) wherever natural. **Do not** write in detached third person about “the teacher,” “the speaker,” or “the professor” (避免「教師指出…」「講者認為…」等第三人稱旁述口吻).
- For important terminology, retain the original English and Greek vocabulary (Latin or Greek script as given); you may add a short Chinese gloss in parentheses when helpful.
- For Bible and theological terminology in Chinese, prefer wording and standard terms associated with **Reformed theology** (改革宗 / 歸正神學), unless the teacher clearly follows another tradition in the lecture.

Structure:
- If the lesson follows the outline closely, structure your explanation to follow that outline (mirror it with your section headings).
- If the lesson does not follow the outline closely, do not force the outline: structure your explanation according to what the teacher actually taught, in order, so the reader still gets a clear “map” of the lesson.
- Include a short note stating whether the provided outline was followed. Put it in a Markdown blockquote at the very start of your output (before any section headings), in Traditional Chinese:
> **大綱對照：**
> (whether the outline was followed and briefly why)

Examples and Scripture (be thorough):
- For **every example** in the lecture: present it **in the teacher’s voice** (first person / direct address—not “the teacher gives an example…”), unpack it step by step, state the takeaway, and link it explicitly to the argument it supports.
- For **every Bible verse and reference**: give literary/historical context as needed, summarize the force of the wording where relevant, and explain how **we** use it in this lesson (not only the citation text).

Bilingual lesson heading (required):
- After the 大綱對照 blockquote, on its own line, output exactly one HTML comment (the tool turns this into ``##``):
  <!-- study-note-zh-h2: Lesson N: 繁體中文標題 (English lesson title) -->
  Use the real lesson number N. The Traditional Chinese part should be a concise translation of the lesson topic. The English part in parentheses must match the official lesson title given above (same wording as after ``Lesson N:``).
- Do **not** follow this with a ``###`` heading that only repeats the same topic—that would duplicate the merged title.

Formatting:
- Do not output heading 1 (#) or raw heading 2 (##) in the prose; the ``##`` line is produced from the HTML comment.
- Use heading 3 (###) for the first real section onward, heading 4 (####) for subsections, then ##### and so on as needed.
"""


GEMINI_SYSTEM_INSTRUCTION_STUDY_NOTE_CN = """Task:
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
- **Voice (required):** Explain **from the teacher’s perspective**, as if **you are the instructor** speaking to the class—use **first person** and **direct address** (我们、我、你们、你) wherever natural. **Do not** write in detached third person about “the teacher,” “the speaker,” or “the professor” (避免「教师指出…」「讲者认为…」等第三人称旁观口吻).
- For important terminology, retain the original English and Greek vocabulary (Latin or Greek script as given); you may add a short Chinese gloss in parentheses when helpful.
- For Bible and theological terminology in Chinese, prefer wording and standard terms associated with **Reformed theology** (改革宗 / 归正神学), unless the teacher clearly follows another tradition in the lecture.

Structure:
- If the lesson follows the outline closely, structure your explanation to follow that outline (mirror it with your section headings).
- If the lesson does not follow the outline closely, do not force the outline: structure your explanation according to what the teacher actually taught, in order, so the reader still gets a clear “map” of the lesson.
- Include a short note stating whether the provided outline was followed. Put it in a Markdown blockquote at the very start of your output (before any section headings), in Simplified Chinese:
> **大纲对照：**
> (whether the outline was followed and briefly why)

Examples and Scripture (be thorough):
- For **every example** in the lecture: present it **in the teacher’s voice** (first person / direct address—not “the teacher gives an example…”), unpack it step by step, state the takeaway, and link it explicitly to the argument it supports.
- For **every Bible verse and reference**: give literary/historical context as needed, summarize the force of the wording where relevant, and explain how **we** use it in this lesson (not only the citation text).

Bilingual lesson heading (required):
- After the 大纲对照 blockquote, on its own line, output exactly one HTML comment (the tool turns this into ``##``):
  <!-- study-note-cn-h2: Lesson N: 简体中文标题 (English lesson title) -->
  Use the real lesson number N. The Simplified Chinese part should be a concise translation of the lesson topic. The English part in parentheses must match the official lesson title given above (same wording as after ``Lesson N:``).
- Do **not** follow this with a ``###`` heading that only repeats the same topic—that would duplicate the merged title.

Formatting:
- Do not output heading 1 (#) or raw heading 2 (##) in the prose; the ``##`` line is produced from the HTML comment.
- Use heading 3 (###) for the first real section onward, heading 4 (####) for subsections, then ##### and so on as needed.
"""


GEMINI_SYSTEM_INSTRUCTION_TRANSLATE_ZH = """Task: Translate the English lesson Markdown below into Traditional Chinese.

Requirements:
- Faithful translation: preserve meaning and tone; do not summarize, expand, or add commentary.
- Use Traditional Chinese (繁體中文) only; do not use Simplified characters.
- For Bible and theological terms in Chinese, prefer standard Reformed / 改革宗 / 歸正神學 wording unless context clearly follows another tradition.
- Keep original English, Greek, or Latin technical terms in Latin script where they appear; you may add a short Traditional gloss in parentheses when helpful.
- Preserve Markdown structure (paragraph breaks, lists, emphasis, links, and any ###+ headings) in parallel; do not add new sections.
- Do **not** add a ``###`` line that repeats the lesson topic (e.g. ``第 N 課：…``); the lesson title is already conveyed by the HTML comment / ``##`` line.

Bilingual lesson heading (required):
- On its own line at the very start of your output, output exactly one HTML comment (the tool turns this into heading 2):
  <!-- translate-zh-h2: Lesson N: 繁體標題 (English lesson title) -->
  N and the English text in parentheses must match the official ``## Lesson N: …`` line from the input.
- After that comment, output the translated body only. Do not output a duplicate raw ``## Lesson`` line.
- Do not use heading 1 (#).
"""

GEMINI_SYSTEM_INSTRUCTION_TRANSLATE_CN = """Task: Translate the English lesson Markdown below into Simplified Chinese.

Requirements:
- Faithful translation: preserve meaning and tone; do not summarize, expand, or add commentary.
- Use Simplified Chinese (简体中文) only; do not use Traditional characters.
- For Bible and theological terms in Chinese, prefer standard Reformed / 改革宗 / 归正神学 wording unless context clearly follows another tradition.
- Keep original English, Greek, or Latin technical terms in Latin script where they appear; you may add a short Simplified gloss in parentheses when helpful.
- Preserve Markdown structure (paragraph breaks, lists, emphasis, links, and any ###+ headings) in parallel; do not add new sections.
- Do **not** add a ``###`` line that repeats the lesson topic (e.g. ``第 N 课：…``); the lesson title is already conveyed by the HTML comment / ``##`` line.

Bilingual lesson heading (required):
- On its own line at the very start of your output, output exactly one HTML comment (the tool turns this into heading 2):
  <!-- translate-cn-h2: Lesson N: 简体中文标题 (English lesson title) -->
  N and the English text in parentheses must match the official ``## Lesson N: …`` line from the input.
- After that comment, output the translated body only. Do not output a duplicate raw ``## Lesson`` line.
- Do not use heading 1 (#).
"""


def build_chinese_study_note_prompt(
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
    system = GEMINI_SYSTEM_INSTRUCTION_STUDY_NOTE_CN if simplified else GEMINI_SYSTEM_INSTRUCTION_STUDY_NOTE_ZH
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


def build_chinese_translation_prompt(
    lesson_english_md: str,
    *,
    lesson_h2_official: Optional[str] = None,
    simplified: bool = False,
) -> str:
    official = ""
    if lesson_h2_official and lesson_h2_official.strip():
        official = (
            "Official lesson heading from source (verbatim—use this lesson number and English title in the HTML comment):\n\n"
            f"{lesson_h2_official.strip()}\n\n"
            "---\n\n"
        )
    system = GEMINI_SYSTEM_INSTRUCTION_TRANSLATE_CN if simplified else GEMINI_SYSTEM_INSTRUCTION_TRANSLATE_ZH
    kind = "Simplified Chinese" if simplified else "Traditional Chinese"
    return (
        f"{system}\n\n"
        "---\n\n"
        f"{official}"
        "English Markdown to translate:\n\n"
        f"{lesson_english_md}\n\n"
        "---\n\n"
        f"Now output only the {kind} translation as specified.\n"
    )


def build_translate_course_title_prompt(*, title_en: str, simplified: bool) -> str:
    script = "Simplified Chinese (简体中文)" if simplified else "Traditional Chinese (繁體中文)"
    return (
        f"Translate this BiblicalTraining course title to {script} only.\n\n"
        "Rules:\n"
        "- Output a single line: the translated title text only.\n"
        "- No quotation marks, no Markdown heading (#), no explanation.\n\n"
        f"English title:\n{title_en.strip()}\n"
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
    # Temperature 0 minimizes paraphrasing; paragraphing must preserve transcript wording verbatim.
    return _generate_gemini_text(api_key, prompt, model, temperature=0.0)


def run_gemini_paragraph_transcript_only(
    *,
    api_key: str,
    transcription: str,
    model: str = "gemini-3.1-flash-lite-preview",
) -> str:
    prompt = build_paragraph_transcript_only_prompt(transcription)
    return _generate_gemini_text(api_key, prompt, model, temperature=0.0)


def run_gemini_chinese_study_note(
    *,
    api_key: str,
    transcription: str,
    outline: str,
    model: str = "gemini-3.1-flash-lite-preview",
    lesson_h1_line: Optional[str] = None,
    simplified: bool = False,
) -> str:
    prompt = build_chinese_study_note_prompt(
        transcription, outline, lesson_h1_line=lesson_h1_line, simplified=simplified
    )
    # Slightly higher temperature helps varied, expansive explanatory prose; paragraphing stays at default 0.2.
    return _generate_gemini_text(api_key, prompt, model, temperature=0.35)


def run_gemini_chinese_translation(
    *,
    api_key: str,
    lesson_english_md: str,
    model: str = "gemini-3.1-flash-lite-preview",
    lesson_h2_official: Optional[str] = None,
    simplified: bool = False,
) -> str:
    prompt = build_chinese_translation_prompt(
        lesson_english_md,
        lesson_h2_official=lesson_h2_official,
        simplified=simplified,
    )
    return _generate_gemini_text(api_key, prompt, model, temperature=0.2)


def run_gemini_translate_course_title(
    *,
    api_key: str,
    title_en: str,
    model: str = "gemini-3.1-flash-lite-preview",
    simplified: bool = False,
) -> str:
    prompt = build_translate_course_title_prompt(title_en=title_en, simplified=simplified)
    text = _generate_gemini_text(api_key, prompt, model, temperature=0.2)
    line = text.splitlines()[0].strip() if text else ""
    return line or text.strip()


def resolve_transcript_outline_paths(
    course_slug: str,
    *,
    transcript: Optional[str] = None,
    outline: Optional[str] = None,
) -> tuple[Path, Path]:
    t = Path(transcript) if transcript else course_transcript_path(course_slug)
    o = Path(outline) if outline else course_outline_path(course_slug)
    return t, o


def resolve_english_course_title_for_translation(
    course_slug: str,
    *,
    model: str,
    paragraph_md_hint: Optional[str] = None,
) -> str:
    """Course display title for the translated document (English, before Gemini title translation)."""
    if paragraph_md_hint:
        t = extract_course_title_from_transcript(paragraph_md_hint)
        if t:
            return t
    combined = default_plain_paragraph_course_out_path(course_slug, model=model)
    if combined.is_file():
        t = extract_course_title_from_transcript(read_text(combined))
        if t:
            return t
    tp = course_transcript_path(course_slug)
    if tp.is_file():
        t = extract_course_title_from_transcript(read_text(tp))
        if t:
            return t
    return course_slug.replace("-", " ").title()


def load_paragraph_lessons_for_translation(
    course_slug: str,
    *,
    model: str,
    paragraph: Optional[str] = None,
    lesson_num: Optional[int] = None,
) -> tuple[list[tuple[int, str]], Optional[str]]:
    """
    Load ``(lesson_num, english_chunk)`` chunks from plain ``paragraph`` Markdown.
    Returns ``([], error_message)`` on failure.
    """
    if lesson_num is not None:
        if paragraph:
            p = Path(paragraph)
            if not p.is_file():
                return [], f"Paragraph file not found: {p}"
            md = read_text(p)
            lessons = split_plain_paragraph_course_into_lessons(md)
            if not lessons:
                return [], f"No ## Lesson N: section in {p}"
            for n, ch in lessons:
                if n == lesson_num:
                    return [(n, ch)], None
            return [], f"No lesson {lesson_num} in {p} (found: {[n for n, _ in lessons]})"
        per = default_plain_paragraph_out_path(course_slug, lesson_num, model=model)
        if per.is_file():
            md = read_text(per)
            lessons = split_plain_paragraph_course_into_lessons(md)
            if lessons:
                return lessons, None
            return [], f"No ## Lesson heading in {per}"
        combined = default_plain_paragraph_course_out_path(course_slug, model=model)
        if not combined.is_file():
            return [], f"No paragraph input for lesson {lesson_num}: tried {per} and {combined}"
        md = read_text(combined)
        lessons = split_plain_paragraph_course_into_lessons(md)
        for n, ch in lessons:
            if n == lesson_num:
                return [(n, ch)], None
        return [], f"No lesson {lesson_num} in {combined}"

    path = Path(paragraph) if paragraph else default_plain_paragraph_course_out_path(course_slug, model=model)
    if not path.is_file():
        return [], f"Combined paragraph file not found: {path}"
    md = read_text(path)
    lessons = split_plain_paragraph_course_into_lessons(md)
    if not lessons:
        return [], f"No ## Lesson N: sections in {path}"
    return lessons, None


def lesson_h2_line_from_paragraph_chunk(chunk: str) -> Optional[str]:
    for line in chunk.splitlines():
        s = line.strip()
        if s and _LESSON_OUTLINE_START.match(s):
            return s
    return None


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
    return (
        course_dir(course_slug)
        / "paragraph-outlined"
        / d
        / f"{course_slug}.lesson{lesson_num:02d}.paragraph-outlined.md"
    )


def default_paragraph_course_out_path(course_slug: str, *, model: str) -> Path:
    """Single file for all lessons: ``courses/<slug>/paragraph-outlined/<model>/<slug>.paragraph-outlined.md``."""
    d = sanitize_model_for_path(model)
    return course_dir(course_slug) / "paragraph-outlined" / d / f"{course_slug}.paragraph-outlined.md"


def default_plain_paragraph_out_path(course_slug: str, lesson_num: int, *, model: str) -> Path:
    d = sanitize_model_for_path(model)
    return (
        course_dir(course_slug)
        / "paragraph"
        / d
        / f"{course_slug}.lesson{lesson_num:02d}.paragraph.md"
    )


def default_plain_paragraph_course_out_path(course_slug: str, *, model: str) -> Path:
    """Single file for all lessons: ``courses/<slug>/paragraph/<model>/<slug>.paragraph.md``."""
    d = sanitize_model_for_path(model)
    return course_dir(course_slug) / "paragraph" / d / f"{course_slug}.paragraph.md"


def default_study_note_zh_out_path(course_slug: str, lesson_num: int, *, model: str) -> Path:
    d = sanitize_model_for_path(model)
    return course_dir(course_slug) / "study-note-zh" / d / f"{course_slug}.lesson{lesson_num:02d}.zh.md"


def default_study_note_zh_course_out_path(course_slug: str, *, model: str) -> Path:
    """Single file for all lessons: ``courses/<slug>/study-note-zh/<model>/<slug>.zh.md``."""
    d = sanitize_model_for_path(model)
    return course_dir(course_slug) / "study-note-zh" / d / f"{course_slug}.zh.md"


def default_study_note_cn_out_path(course_slug: str, lesson_num: int, *, model: str) -> Path:
    d = sanitize_model_for_path(model)
    return course_dir(course_slug) / "study-note-cn" / d / f"{course_slug}.lesson{lesson_num:02d}.cn.md"


def default_study_note_cn_course_out_path(course_slug: str, *, model: str) -> Path:
    """Single file for all lessons: ``courses/<slug>/study-note-cn/<model>/<slug>.cn.md``."""
    d = sanitize_model_for_path(model)
    return course_dir(course_slug) / "study-note-cn" / d / f"{course_slug}.cn.md"


def default_translate_zh_out_path(course_slug: str, lesson_num: int, *, model: str) -> Path:
    d = sanitize_model_for_path(model)
    return course_dir(course_slug) / "translate-zh" / d / f"{course_slug}.lesson{lesson_num:02d}.zh.md"


def default_translate_zh_course_out_path(course_slug: str, *, model: str) -> Path:
    """Single file for all lessons: ``courses/<slug>/translate-zh/<model>/<slug>.zh.md``."""
    d = sanitize_model_for_path(model)
    return course_dir(course_slug) / "translate-zh" / d / f"{course_slug}.zh.md"


def default_translate_cn_out_path(course_slug: str, lesson_num: int, *, model: str) -> Path:
    d = sanitize_model_for_path(model)
    return course_dir(course_slug) / "translate-cn" / d / f"{course_slug}.lesson{lesson_num:02d}.cn.md"


def default_translate_cn_course_out_path(course_slug: str, *, model: str) -> Path:
    """Single file for all lessons: ``courses/<slug>/translate-cn/<model>/<slug>.cn.md``."""
    d = sanitize_model_for_path(model)
    return course_dir(course_slug) / "translate-cn" / d / f"{course_slug}.cn.md"
