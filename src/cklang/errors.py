"""Public exceptions and original source locations."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Span:
    """Original source extent: zero-based [start, end), one-based line/column.

    Offsets count Unicode characters, not encoded bytes. Locations remain
    unchanged after editing; synthetic tokens have no span.
    """

    start: int
    end: int
    line: int
    column: int


class ParseError(ValueError):
    """Lexical/syntactic failure with the original source location and filename."""

    def __init__(self, message: str, span: Span, filename: str = "<string>") -> None:
        self.span = span
        self.filename = filename
        super().__init__(f"{filename}:{span.line}:{span.column}: {message}")


class DuplicateKeyError(KeyError):
    """An operation requires one assignment, but several entries match."""
