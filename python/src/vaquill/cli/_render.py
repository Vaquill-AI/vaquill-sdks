"""Human output: width-aware tables and key/value lines. Colour only when asked for."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

RESET = "\x1b[0m"
CODES = {"bold": "1", "dim": "2", "red": "31", "yellow": "33"}


def cell(value: Any) -> str:
    """A table cell: None is a dash, booleans are yes/no, whole floats lose the decimal."""
    if value is None or value == "":
        return "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:g}"
    return " ".join(str(value).split())


def clip(text: str, width: int) -> str:
    return text if len(text) <= width else text[: max(width - 3, 0)] + "..."


def paint(text: str, style: str, enabled: bool) -> str:
    return f"\x1b[{CODES[style]}m{text}{RESET}" if enabled else text


class UI:
    def __init__(self, *, color: bool, width: int) -> None:
        self.color = color
        self.width = max(width, 40)

    def bold(self, text: str) -> str:
        return paint(text, "bold", self.color)

    def dim(self, text: str) -> str:
        return paint(text, "dim", self.color)

    def table(self, headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
        """Left-aligned columns; the last column is clipped so each line fits the terminal."""
        body = [[cell(v) for v in row] for row in rows]
        widths = [max(len(h), *(len(r[i]) for r in body)) for i, h in enumerate(headers)]
        used = sum(widths[:-1]) + 2 * (len(widths) - 1)
        widths[-1] = max(min(widths[-1], self.width - used), len(headers[-1]))

        def line(values: Sequence[str]) -> str:
            parts = [v.ljust(w) for v, w in zip(values[:-1], widths, strict=False)]
            return "  ".join([*parts, clip(values[-1], widths[-1])]).rstrip()

        head = self.bold(line([h.upper() for h in headers]))
        return "\n".join([head, *(line(r) for r in body)])

    def kv(self, pairs: Sequence[tuple[str, Any]]) -> str:
        shown = [(k, cell(v)) for k, v in pairs if v is not None and v != ""]
        if not shown:
            return ""
        key_width = max(len(k) for k, _ in shown)
        return "\n".join(f"{self.bold(k.ljust(key_width))}  {v}" for k, v in shown)
