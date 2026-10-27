"""Structural, non-mutating script formatting, separate from lossless rendering.

Only whitespace trivia is regenerated. Token spellings and comment text remain
opaque, so strings, expressions, operators and repeated entries are preserved.
"""

from __future__ import annotations

from .lexer import Token
from .nodes import Assignment, Block, Conditional, Document, Node, Prefixed, Scalar


def render_pretty(node: Node, *, indent: str | int = "    ") -> str:
    """Format one subtree, normalizing layout to LF without modifying its tokens.

    Documents end with LF when nonempty (except a BOM-only document). Subtrees
    have no automatically appended final LF. Each structural child occupies its
    own line; comments retain their order and original inline/standalone status.
    """
    if isinstance(indent, bool) or not isinstance(indent, (str, int)):
        raise TypeError("indent must be a whitespace string or a number of spaces")
    if isinstance(indent, int):
        if indent < 0:
            raise ValueError("indent must be nonnegative")
        unit = " " * indent
    else:
        if any(char not in " \t" for char in indent):
            raise ValueError("indent may contain only spaces and tabs")
        unit = indent
    writer = _Writer(unit)
    writer.write(node)
    return "".join(writer.parts)


class _Writer:
    """Small output state machine; never read source indentation as layout."""

    def __init__(self, indent: str) -> None:
        self.indent = indent
        self.parts: list[str] = []
        self.line_start = True

    def newline(self) -> None:
        if not self.line_start:
            self.parts.append("\n")
            self.line_start = True

    def text(self, text: str, depth: int, separator: str = "") -> None:
        if not text:
            return
        if self.line_start:
            self.parts.append(self.indent * depth)
        elif separator:
            self.parts.append(separator)
        self.parts.append(text)
        self.line_start = text.endswith(("\n", "\r"))

    def token(
        self, token: Token, depth: int, *, separator: str = "", line_break: bool = False,
        comment_depth: int | None = None,
    ) -> None:
        """Emit trivia comments before layout breaks, keeping inline comments inline."""
        standalone = False
        for trivia in token.leading:
            if trivia.kind == "WHITESPACE":
                standalone = standalone or "\n" in trivia.text or "\r" in trivia.text
                if "\ufeff" in trivia.text and not self.parts:
                    self.parts.append("\ufeff")
            elif trivia.kind == "COMMENT":
                if standalone:
                    self.newline()
                self.text(trivia.text, depth if comment_depth is None else comment_depth, " ")
                self.newline()
                standalone = True
        if line_break:
            self.newline()
        self.text(token.text, depth, separator)

    def write(self, node: Node, depth: int = 0, *, separator: str = "", line_break: bool = False) -> None:
        """Emit syntax recursively; child boundaries determine newlines, not tokens."""
        if isinstance(node, Document):
            for child in node._children:
                self.write(child, depth, line_break=True)
            self.token(node._eof, depth, line_break=True)
        elif isinstance(node, Scalar):
            self.token(node.token, depth, separator=separator, line_break=line_break)
        elif isinstance(node, Assignment):
            first = node.modifier if node.modifier is not None else node.key
            self.token(first.token, depth, separator=separator, line_break=line_break)
            if node.modifier is not None:
                self.token(node.key.token, depth, separator=" ")
            self.token(node.operator_token, depth, separator=" ")
            self.write(node.value, depth, separator=" ")
        elif isinstance(node, Prefixed):
            self.token(node.prefix.token, depth, separator=separator, line_break=line_break)
            self.write(node.value, depth, separator=" ")
        elif isinstance(node, (Block, Conditional)):
            self.token(node._open, depth, separator=separator, line_break=line_break)
            for child in node._children:
                self.write(child, depth + 1, line_break=True)
            has_comments = any(t.kind == "COMMENT" for t in node._close.leading)
            self.token(
                node._close, depth, line_break=bool(node._children) or has_comments,
                comment_depth=depth + 1,
            )
        else:
            raise TypeError(f"Cannot format {type(node).__name__}")
