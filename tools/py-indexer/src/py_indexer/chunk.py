"""Deterministic bounded line-window chunking (not AST analysis)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class Chunk:
    start_line: int  # 1-based inclusive
    end_line: int  # 1-based inclusive
    text: str
    content_hash: str


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def chunk_lines(text: str, *, chunk_lines: int = 80, overlap: int = 10) -> list[Chunk]:
    """Split text into overlapping line windows.

    Strategy (documented MVP):
    - Split on ``\\n`` preserving content (no AST / symbol analysis).
    - Windows of ``chunk_lines`` with ``overlap`` shared lines between windows.
    - Final window may be shorter; empty files yield no chunks.
    """
    if chunk_lines < 1:
        raise ValueError("chunk_lines must be >= 1")
    if overlap < 0 or overlap >= chunk_lines:
        raise ValueError("overlap must be >= 0 and < chunk_lines")

    # Keep line endings out of stored text for stable hashes; rejoin with \n.
    raw_lines = text.splitlines()
    if not raw_lines:
        if text == "":
            return []
        raw_lines = [text]

    chunks: list[Chunk] = []
    step = max(1, chunk_lines - overlap)
    n = len(raw_lines)
    i = 0
    while i < n:
        end = min(n, i + chunk_lines)
        window = raw_lines[i:end]
        body = "\n".join(window)
        start_line = i + 1
        end_line = end
        chunks.append(
            Chunk(
                start_line=start_line,
                end_line=end_line,
                text=body,
                content_hash=content_hash(body),
            )
        )
        if end >= n:
            break
        i += step
    return chunks
