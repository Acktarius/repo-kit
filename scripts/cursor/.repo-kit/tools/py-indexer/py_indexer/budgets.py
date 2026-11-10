"""Server-side response budget ceilings."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Budgets:
    max_results: int = 12
    max_snippet_chars: int = 1200
    max_total_chars: int = 12000
    max_read_lines: int = 400
    max_file_bytes: int = 524288

    def clamp_results(self, n: int) -> int:
        return max(1, min(int(n), self.max_results))

    def clamp_snippet(self, text: str) -> tuple[str, bool]:
        if len(text) <= self.max_snippet_chars:
            return text, False
        return text[: self.max_snippet_chars], True
