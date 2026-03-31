"""
Parse transcript Markdown, call Gemini to add two-layer outlines and paragraph breaks, reassemble.

Each lesson: one `# Lesson` line, then outline (`##` / `###`), then transcript.
No `## Outline` wrapper.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from dataclasses import dataclass
from typing import Any, Optional

from bt.transcript_clean import strip_appended_lesson_catalog, strip_transcript_ui_noise

_LESSON_H1 = re.compile(r"^# Lesson (\d+):\s*(.+)$", re.MULTILINE)

USER_PROMPT = (
    "I want to paragraph the lesson, create a two-layer outline of the lesson without changing "
    "the wording. Preserve markdown from the transcript (headings, emphasis, lists) where it "
    "exists. The outline will be placed immediately under the lesson heading; do not add a "
    "separate 'Outline' section title inside your fields. Never repeat the lesson's # heading."
)


@dataclass(frozen=True)
class LessonSegment:
    order: int
    title: str
    heading_line: str
    body: str


def iter_progress(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def parse_markdown_lessons(text: str) -> tuple[str, list[LessonSegment]]:
    """
    Split file into header (TOC + ---) and lesson segments.
    Each segment is a `# Lesson N: Title` block; body is text until the next `# Lesson` or EOF.
    """
    matches = list(_LESSON_H1.finditer(text))
    if not matches:
        raise ValueError("No '# Lesson N: Title' headings found. Is this a downloader transcript?")

    header = text[: matches[0].start()]
    segments: list[LessonSegment] = []

    for i, m in enumerate(matches):
        order = int(m.group(1))
        title = m.group(2).strip()
        heading_line = m.group(0).strip()
        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[body_start:body_end].strip()
        segments.append(
            LessonSegment(order=order, title=title, heading_line=heading_line, body=body)
        )

    return header, segments


def _strip_duplicate_lesson_heading(body: str, heading_line: str) -> str:
    """Remove a leading duplicate of `# Lesson N: Title` if the model echoed it."""
    want = heading_line.strip()
    lines = body.splitlines()
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i < len(lines) and lines[i].strip() == want:
        return "\n".join(lines[:i] + lines[i + 1 :]).lstrip("\n")
    return body


def _strip_outline_artifacts(outline: str, heading_line: str) -> str:
    """Drop a spurious `# Lesson ...` line if the model echoed the lesson H1 in the outline."""
    want = heading_line.strip()
    lines = outline.strip().splitlines()
    out: list[str] = []
    for i, ln in enumerate(lines):
        if i == 0 and ln.strip() == want:
            continue
        if ln.strip() in {"## Outline", "### Outline"}:
            continue
        out.append(ln)
    return "\n".join(out).strip()


def _extract_json_object(raw: str) -> dict[str, Any]:
    raw = raw.strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", raw)
        if not m:
            raise
        data = json.loads(m.group(0))
    if not isinstance(data, dict):
        raise ValueError("Expected JSON object from model")
    return data


def enrich_lesson_with_gemini(
    lesson_heading: str,
    body: str,
    *,
    model: str,
    api_key: str,
) -> tuple[str, str]:
    """Return (outline_markdown, paragraphed_body) from Gemini."""
    import google.generativeai as genai

    genai.configure(api_key=api_key)

    system_instruction = (
        "You respond with JSON only, no markdown fences. "
        'Schema: {"outline_markdown": string, "body": string}. '
        "outline_markdown: a two-level outline only — use ## for the first level and ### for "
        "the second (no deeper nesting). Do not use # in the outline. Do not repeat or paraphrase "
        "the lesson line given below as a # heading. Do not output a heading named 'Outline'. "
        "body: the full lesson transcript text only, starting with the first word of the "
        "transcript (not with any # heading). Add paragraph breaks and whitespace only — do not "
        "change, add, or remove words. Preserve markdown that exists in the transcript "
        "(e.g. **bold**, lists). Never include the outline inside body."
    )

    user_block = (
        f"{USER_PROMPT}\n\n"
        "The lesson heading line (do not repeat this in outline_markdown or body):\n"
        f"{lesson_heading}\n\n"
        f"Transcript:\n{body}"
    )

    generation_config = genai.GenerationConfig(
        response_mime_type="application/json",
    )

    model_client = genai.GenerativeModel(
        model,
        system_instruction=system_instruction,
        generation_config=generation_config,
    )

    for attempt in range(2):
        try:
            response = model_client.generate_content(user_block)
            text = (response.text or "").strip()
            if not text:
                raise ValueError("Empty response from model")
            data = _extract_json_object(text)
            outline = data.get("outline_markdown")
            out_body = data.get("body")
            if not isinstance(outline, str) or not isinstance(out_body, str):
                raise ValueError("JSON must contain string fields outline_markdown and body")
            outline = _strip_outline_artifacts(outline.strip(), lesson_heading)
            out_body = _strip_duplicate_lesson_heading(out_body.strip(), lesson_heading)
            return outline, out_body
        except Exception:
            if attempt == 0:
                user_block = (
                    user_block
                    + "\n\nReturn ONLY valid JSON: "
                    '{"outline_markdown":"...","body":"..."}'
                )
                continue
            raise


def format_lesson_block(heading_line: str, outline_markdown: str, body: str) -> str:
    """# Lesson, then ##/### outline, then body. No separate Outline heading."""
    return f"{heading_line}\n\n{outline_markdown}\n\n{body}\n\n"


def run_outline(
    in_path: str,
    out_path: str,
    *,
    model: str,
    api_key: str,
    sleep_seconds: float,
) -> int:
    with open(in_path, encoding="utf-8") as f:
        text = f.read()

    try:
        header, segments = parse_markdown_lessons(text)
    except ValueError as e:
        iter_progress(f"Error: {e}")
        return 2

    parts: list[str] = [header]
    n = len(segments)
    for idx, seg in enumerate(segments, start=1):
        iter_progress(f"[{idx}/{n}] Lesson {seg.order}: {seg.title}")
        try:
            body_clean = strip_appended_lesson_catalog(strip_transcript_ui_noise(seg.body))
            outline_md, body_out = enrich_lesson_with_gemini(
                seg.heading_line,
                body_clean,
                model=model,
                api_key=api_key,
            )
            body_out = strip_transcript_ui_noise(body_out)
        except Exception as e:
            iter_progress(f"  Gemini failed: {e}")
            return 2
        parts.append(format_lesson_block(seg.heading_line, outline_md, body_out))
        if idx < n:
            time.sleep(max(0.0, sleep_seconds))

    out_text = "".join(parts)
    if not out_text.endswith("\n"):
        out_text += "\n"

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(out_text)

    iter_progress(f"Wrote: {out_path}")
    return 0


def resolve_api_key() -> Optional[str]:
    return os.environ.get("GEMINI_API_KEY", "").strip() or None
