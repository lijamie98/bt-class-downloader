"""Default filesystem layout: all course downloads and generated Markdown live under ``data/``."""

from __future__ import annotations

from pathlib import Path

DATA_ROOT = Path("data")
TRANSCRIPTS_DIR = DATA_ROOT / "transcripts"
OUTLINES_DIR = DATA_ROOT / "outlines"
PARAGRAPH_DIR = DATA_ROOT / "paragraph"
PARAGRAPH_OUTLINED_DIR = DATA_ROOT / "paragraph-outlined"
EXPLAIN_ZH_DIR = DATA_ROOT / "explain-zh"
EXPLAIN_CN_DIR = DATA_ROOT / "explain-cn"
