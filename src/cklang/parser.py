"""Recursive descent over a lossless token stream."""

from __future__ import annotations

from collections import deque
from os import PathLike
from pathlib import Path
from typing import NoReturn

from .errors import ParseError
from .facade import render
from .lexer import Token, lex
from .nodes import Assignment, Block, Conditional, Document, Node, Prefixed, Scalar, ValueNode, is_parameter


class Parser:
    """Internal recursive-descent parser with a bounded token lookahead buffer.

    Parsed nodes wrap original tokens directly: constructors that would add
    spacing to new nodes are intentionally bypassed. Parsing does not recover
    after errors or validate CK3's runtime scopes/triggers.
    """

    def __init__(self, source: str, filename: str, *, ignore_comments: bool = False) -> None:
        self.stream = iter(lex(source, filename=filename, ignore_comments=ignore_comments))
        self.buffer: deque[Token] = deque()
        self.filename = filename

    def peek(self, offset: int = 0) -> Token:
        """Inspect a token without consuming it (only small offsets are used)."""
        while len(self.buffer) <= offset:
            self.buffer.append(next(self.stream))
        return self.buffer[offset]

    def take(self) -> Token:
        """Consume the next significant token, including its attached trivia."""
        self.peek()
        return self.buffer.popleft()

    def fail(self, message: str) -> NoReturn:
        """Raise a syntax error at the next token's original location."""
        span = self.peek().span
        assert span is not None  # Every token produced by lex() has a location.
        raise ParseError(message, span, self.filename)

    def children(self, closing: str) -> list[Node]:
        """Parse statements until closing, leaving the closing token unconsumed."""
        children: list[Node] = []
        while self.peek().kind != closing:
            if self.peek().kind in {"EOF", "RBRACE", "RBRACKET"}:
                self.fail(f"Expected {closing}, got {self.peek().kind}")
            children.append(self.statement())
        return children

    def statement(self) -> Node:
        """Parse a declaration, assignment, guard, block or anonymous scalar."""
        if self.peek().kind == "CONDITION":
            opening = self.take()
            try:
                guard = Conditional(opening.text[2:-1])
            except ValueError as error:
                assert opening.span is not None
                raise ParseError(str(error), opening.span, self.filename) from error
            guard._open = opening
            guard._children = self.children("RBRACKET")
            guard._close = self.take()
            return guard
        if self.peek().kind == "LBRACE":
            return self.block()
        key = self.scalar()
        modifier: Scalar | None = None
        if key.text in {"scripted_trigger", "scripted_effect", "scripted_value"} and self.peek().kind in {"ATOM", "STRING"} and self.peek(1).kind == "OPERATOR":
            modifier, key = key, self.scalar()
        if self.peek().kind == "OPERATOR" or (
            is_parameter(self.peek().text)
            and self.peek(1).kind in {"ATOM", "STRING", "EXPRESSION", "LBRACE"}
        ):
            operator = self.take()
            value = self.value()
            # Constructors add spacing for new nodes; parsed nodes must be untouched.
            node = Assignment.__new__(Assignment)
            node.key, node.modifier = key, modifier
            node.operator_token, node._value = operator, value
            return node
        return key

    def scalar(self, *, operator_value: bool = False) -> Scalar:
        """Read one scalar; bare operators are allowed only in value position."""
        allowed = {"ATOM", "STRING", "EXPRESSION"}
        if operator_value:
            allowed.add("OPERATOR")
        if self.peek().kind not in allowed:
            self.fail(f"Expected scalar, got {self.peek().kind}")
        return Scalar.from_token(self.take())

    def value(self) -> ValueNode:
        """Read an assignment value, preserving symbolic prefixes/formulas."""
        if self.peek().kind == "LBRACE":
            return self.block()
        scalar = self.scalar(operator_value=True)
        # Braced tags are open-ended; scalar tags are explicitly disambiguated.
        if (scalar.kind == "symbol" and self.peek().kind == "LBRACE") or (scalar.text == "list" and self.peek().kind == "STRING"):
            node = Prefixed.__new__(Prefixed)
            node.prefix = scalar
            node.value = self.block() if self.peek().kind == "LBRACE" else self.scalar()
            return node
        return scalar

    def block(self) -> Block:
        """Consume a brace-delimited block, including both brace tokens."""
        node = Block()
        node._open = self.take()
        node._children = self.children("RBRACE")
        node._close = self.take()
        return node

    def parse(self) -> Document:
        """Parse the root sequence and preserve trailing trivia on EOF."""
        node = Document(self.children("EOF"))
        node._eof = self.take()
        return node


def parse(source: str, *, filename: str = "<string>", ignore_comments: bool = False) -> Document:
    """Parse script source into an editable, lossless document.

    ``filename`` is used only in diagnostics; no file is opened. Raises
    ParseError for malformed source. By default, render(document) == source
    without edits. Set ``ignore_comments=True`` to omit lexical comments from
    the tree and output; whitespace and original source locations are preserved.
    Hashes inside quoted strings or opaque scalar expressions are not removed.
    """
    return Parser(source, filename, ignore_comments=ignore_comments).parse()


def load(
    path: str | PathLike[str], *, encoding: str = "utf-8", ignore_comments: bool = False,
) -> Document:
    """Read and parse a file without newline conversion or encoding detection.

    UTF-8 BOMs remain in the tree with the default encoding. The encoding is
    retained for dump(). I/O/decoding errors and ParseError propagate unchanged.
    ``ignore_comments`` has the same semantics as parse(): comments are discarded
    during scanning and cannot be recovered by subsequently dumping this tree.
    """
    source_path = Path(path)
    with source_path.open("r", encoding=encoding, newline="") as stream:
        document = parse(stream.read(), filename=str(source_path), ignore_comments=ignore_comments)
    document._encoding = encoding
    return document


def dump(
    document: Document, path: str | PathLike[str], *, encoding: str | None = None,
    pretty: bool = False, indent: str | int = "    ",
) -> None:
    """Write a document to an explicit path without newline conversion.

    Uses the document's encoding unless overridden. The target is overwritten;
    this is not an atomic write and parent directories are not created. Pretty
    rendering regenerates layout with LF and the requested indentation.
    """
    output = render(document, pretty=pretty, indent=indent)
    with Path(path).open("w", encoding=encoding or document._encoding, newline="") as stream:
        stream.write(output)
