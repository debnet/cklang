"""Checked usage examples; no casts/Any needed for normal typed exploration.

These functions are checked by mypy but do not run as part of unittest.
Dynamic data names/cardinality require narrowing with isinstance, not guesses.
"""

from collections.abc import Iterator
from decimal import Decimal
from typing import assert_type

from cklang import (
    Assignment, Block, ContainerAPI, Document, Node, NodeAPI, Scalar, ScalarKind, ScalarValue, Span,
    Token, ValueInput, ValueNode, api, lex, load, parse, render,
)


def explore(source: str) -> str:
    """Narrow optional/multiple/nested values before using their type's API."""
    tree = parse(source)
    assert_type(tree, Document)
    assert_type(tree[0], Node)
    assert_type(tree["event"], ValueNode | list[ValueNode])
    assert_type(tree.event, ValueNode | list[ValueNode])
    assert_type(tree._api.getall("event"), list[ValueNode])
    assert_type(tree._api.entry("event"), Assignment)
    assert_type(tree._api.tokens(), Iterator[Token])
    assert_type(tree._api.span, Span | None)
    assert_type(lex(source), Iterator[Token])
    assert_type(lex(source, ignore_comments=True), Iterator[Token])
    assert_type(parse(source, ignore_comments=True), Document)

    event = tree["event"]
    if isinstance(event, Block):
        for option in event._api.getall("option"):
            if isinstance(option, Block):
                name = option["name"]
                if isinstance(name, Scalar):
                    assert_type(name.value, ScalarValue)
                    assert_type(name.kind, ScalarKind)
                    name.value = "edited"
                    entry = name._api.assignment
                    if entry is not None:
                        entry.operator = "="
    return render(tree)


def construct() -> Document:
    """Native typed sequences, ownership edits and wider setter inputs work."""
    tree = Document()
    names: list[str] = ["brave", "calm"]
    values: tuple[int, ...] = (1, 2, 3)
    tree["traits"] = names
    tree["numbers"] = values
    tree._api.add("gold", Decimal("1.25"), ">=")
    tree._api.entry("gold").value = 42
    scalar = Scalar(1)
    scalar.value = 1.5
    tree._api.append(Assignment("added", scalar))
    tree._api.children[:] = reversed(tree._api.children)
    tree._api.children = tuple(tree._api.children)
    nested: ValueInput = ["symbol", [True, Decimal("2.50")]]
    tree["nested"] = nested
    return tree


def read_without_comments(path: str) -> Document:
    """The file API accepts the same typed comment policy as parse/lex."""
    document = load(path, encoding="utf-8", ignore_comments=True)
    assert_type(document, Document)
    return document


def edit_and_format() -> str:
    """Facade insertion retains concrete node types; script fragments are typed."""
    block = Block()
    block["gold"] = 100
    entry = block._api.add("gold", 200, ">=")
    assert_type(entry, Assignment)
    direct = block._api.append(Assignment("prestige", 10))
    assert_type(direct, Assignment)
    first = block._api.insert(0, Scalar("anonymous"))
    assert_type(first, Scalar)
    fragment = block._api.add_script("OR = { value = 10 }")
    assert_type(fragment, Node | list[Node])
    block._api.insert_script(1, "a=1 b=2")
    assert_type(block._api.render(pretty=True, indent=2), str)
    return render(block, pretty=True, indent="\t")


def facade_usage() -> str:
    """Public views preserve node types and separate data, nodes and source."""
    tree = Document()
    block = Block()
    scalar = Scalar(100)
    assert_type(api(tree), ContainerAPI[Document])
    assert_type(tree._api, ContainerAPI[Document])
    assert_type(block._api, ContainerAPI[Block])
    assert_type(scalar._api, NodeAPI[Scalar])
    assert_type(api(scalar), NodeAPI[Scalar])
    assert_type(api(scalar).node, Scalar)
    assert_type(api(block).node, Block)
    node: Node = scalar
    assert_type(api(node), NodeAPI[Node])
    view = block._api
    assert_type(view.add("gold", 100), Assignment)
    assert_type(view.append(scalar), Scalar)
    assert_type(view.insert(0, Assignment("prestige", 50)), Assignment)
    assert_type(view.add_script("OR={value=10}"), Node | list[Node])
    assert_type(view.insert_script(0, "first=yes"), Node | list[Node])
    assert_type(view.entry("gold"), Assignment)
    assert_type(view.getall("gold"), list[ValueNode])
    assert_type(view.entries(), Iterator[Assignment])
    assert_type(view.parent, Node | None)
    assert_type(view.assignment, Assignment | None)
    assert_type(view.span, Span | None)
    assert_type(view.children, list[Node])
    assert_type(view.tokens(), Iterator[Token])
    assert_type(view.walk(), Iterator[Node])
    assert_type(render(tree), str)
    assert_type(render(scalar, pretty=True, indent=2), str)
    assert_type(render(node, pretty=True, indent="\t"), str)
    view.children = tuple(reversed(view.children))
    tree._api.add("root", block)
    return api(tree).render(pretty=True, indent=2)
