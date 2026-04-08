"""Default filesystem layout: course artifacts live under ``courses/<course-slug>/``."""

from __future__ import annotations

from pathlib import Path

COURSES_ROOT = Path("courses")


def course_dir(course_slug: str) -> Path:
    return COURSES_ROOT / course_slug


def course_transcript_path(course_slug: str) -> Path:
    """``courses/<slug>/<slug>.md``"""
    return course_dir(course_slug) / f"{course_slug}.md"


def course_outline_path(course_slug: str) -> Path:
    """``courses/<slug>/<slug>.outline.md``"""
    return course_dir(course_slug) / f"{course_slug}.outline.md"
