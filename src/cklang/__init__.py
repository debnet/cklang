"""Lossless script parsing, exploration and editing."""

from .errors import DuplicateKeyError, ParseError, Span
from .lexer import Token, Trivia, lex
from .nodes import (
    Assignment, Block, Conditional, Container, Document, Node, Prefixed, Scalar,
    InsertNode, ScalarInput, ScalarKind, ScalarValue, ValueInput, ValueNode,
)
from .facade import ContainerAPI, NodeAPI, api, render
from .parser import dump, load, parse

__all__ = [
    "Assignment", "Block", "Conditional", "Container", "Document", "DuplicateKeyError",
    "Node", "ParseError", "Prefixed", "Scalar", "Span", "Token", "Trivia", "dump",
    "lex", "load", "parse", "ScalarInput", "ScalarKind", "ScalarValue",
    "ValueInput", "ValueNode", "InsertNode", "NodeAPI", "ContainerAPI", "api", "render",
]
