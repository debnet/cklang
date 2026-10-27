"""A scanner, not a sequence of source-rewriting regular expressions."""

from dataclasses import dataclass, field
from collections.abc import Iterator

from .errors import ParseError, Span


@dataclass(slots=True)
class Trivia:
    """Editable whitespace or comment preceding a significant token.

    ``text`` includes the comment marker or exact whitespace. Mutating it is
    intentionally low-level: the caller is responsible for valid syntax.
    """

    kind: str
    text: str
    span: Span | None = None


@dataclass(slots=True)
class Token:
    """Significant lexeme with exact spelling, leading trivia and location.

    ``kind`` is a scanner category such as ATOM, STRING, OPERATOR or EOF.
    Tokens created by editing may have ``span=None``.
    """

    kind: str
    text: str
    leading: list[Trivia] = field(default_factory=list)
    span: Span | None = None

    def render(self) -> str:
        """Return this token's leading trivia followed by its exact text."""
        return "".join(t.text for t in self.leading) + self.text


def synthetic(kind: str, text: str, leading: str = "") -> Token:
    """Build a token without an original source location."""
    return Token(kind, text, [Trivia("WHITESPACE", leading)] if leading else [])


def lex(source: str, *, filename: str = "<string>", ignore_comments: bool = False) -> Iterator[Token]:
    """Yield significant tokens, with whitespace/comments attached, then EOF.

    Offsets are Unicode character offsets. Newlines and an initial BOM are kept.
    Raises ParseError on malformed strings, operators or bracketed expressions.
    No variable expansion, evaluation or input/output is performed.
    With ``ignore_comments=True``, skip comment trivia without changing source
    positions or surrounding whitespace. Hashes inside scalar tokens are kept.
    """
    i, line, column = 0, 1, 1
    size = len(source)
    trivia: list[Trivia] = []

    def advance(end: int) -> Span:
        nonlocal i, line, column
        span = Span(i, end, line, column)
        text = source[i:end]
        count = text.count("\n")
        if count:
            line += count
            column = len(text.rsplit("\n", 1)[1]) + 1
        else:
            column += len(text)
        i = end
        return span

    while i < size:
        start = i
        ch = source[i]
        if ch.isspace() or (i == 0 and ch == "\ufeff"):
            end = i + 1
            while end < size and source[end].isspace():
                end += 1
            trivia.append(Trivia("WHITESPACE", source[start:end], advance(end)))
            continue
        if ch == "#":
            end = i + 1
            while end < size and source[end] not in "\r\n":
                end += 1
            span = advance(end)
            if not ignore_comments:
                trivia.append(Trivia("COMMENT", source[start:end], span))
            continue
        if ch == '"':
            kind, end = "STRING", i + 1
            while end < size:
                if source[end] == "\\":
                    end += 2
                elif source[end] == '"':
                    end += 1
                    break
                else:
                    end += 1
            else:
                raise ParseError("Unterminated quoted string", Span(i, size, line, column), filename)
            if end > size:
                raise ParseError("Unterminated quoted string", Span(i, size, line, column), filename)
        elif source.startswith("@[", i):
            kind, end, depth = "EXPRESSION", i + 2, 1
            while end < size and depth:
                if source[end] == "[":
                    depth += 1
                elif source[end] == "]":
                    depth -= 1
                end += 1
            if depth:
                raise ParseError("Unterminated inline expression", Span(i, size, line, column), filename)
        elif source.startswith("[[", i):
            kind = "CONDITION"
            end = source.find("]", i + 2)
            if end == -1:
                raise ParseError("Unterminated parameter condition", Span(i, size, line, column), filename)
            end += 1
        elif ch in "{}]":
            kind, end = {"{": "LBRACE", "}": "RBRACE", "]": "RBRACKET"}[ch], i + 1
        elif ch in "=<>?!" and (ch != "!" or source.startswith("!=", i)):
            kind, end = "OPERATOR", i + 1
            while end < size and source[end] in "=<>?!":
                end += 1
            if source[i:end] not in {"=", "==", "!=", "<", ">", "<=", ">=", "?=", "?!=", "<>"}:
                raise ParseError("Unknown operator", Span(i, end, line, column), filename)
        else:
            kind, end = "ATOM", i + 1
            while end < size and not source[end].isspace() and source[end] not in '{}"#=<>?!]':
                end += 1
        span = advance(end)
        yield Token(kind, source[start:end], trivia, span)
        trivia = []
    yield Token("EOF", "", trivia, Span(i, i, line, column))
