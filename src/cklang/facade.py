"""Explicit, typed operations on nodes, separate from dynamic script attributes.

``api(node)`` and ``node._api`` create lightweight live views of the same node.
They never copy/wrap the data tree or cache an API object inside it. This module
uses qualified node annotations and resolves classes only when called, allowing
nodes to expose the facade without an import-time class dependency cycle.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Generic, SupportsIndex, TypeVar, overload

from . import nodes
from .errors import Span
from .lexer import Token, Trivia


_NodeT = TypeVar("_NodeT", bound="nodes.Node", covariant=True)
_ContainerT = TypeVar("_ContainerT", bound="nodes.Container", covariant=True)
_InsertT = TypeVar("_InsertT", bound="nodes.InsertNode")
_NodeArg = TypeVar("_NodeArg", bound="nodes.Node")
_ContainerArg = TypeVar("_ContainerArg", bound="nodes.Container")


class NodeAPI(Generic[_NodeT]):
    """Live operations/metadata common to every syntax node.

    Access type-specific data directly on the node: Scalar.value,
    Assignment.operator, Prefixed.prefix, etc. Metadata returned here consists
    of the actual nodes/tokens/trivia, not further API wrappers or copies.
    """

    __slots__ = ("_node",)

    def __init__(self, node: _NodeT) -> None:
        if not isinstance(node, nodes.Node):
            raise TypeError("api() requires a syntax node")
        self._node = node

    @property
    def node(self) -> _NodeT:
        """The original node, retaining its concrete static type."""
        return self._node

    @property
    def parent(self) -> nodes.Node | None:
        """Immediate structural parent, or None for a detached/root node."""
        return self._node._parent

    @property
    def assignment(self) -> nodes.Assignment | None:
        """Nearest enclosing assignment, including the node itself if applicable."""
        return self._node._assignment

    @property
    def span(self) -> Span | None:
        """Original first-token location; synthetic nodes may have no location."""
        return self._node._span

    @property
    def comments(self) -> Iterator[Trivia]:
        """Iterate the comments attached to tokens throughout this subtree."""
        return self._node._comments

    @property
    def leading_comments(self) -> list[Trivia]:
        """Snapshot of the editable comment objects on the first token."""
        return self._node._leading_comments

    @property
    def trailing_comments(self) -> list[Trivia]:
        """Snapshot of editable same-line comments after the node's last token."""
        return self._node._trailing_comments

    def tokens(self) -> Iterator[Token]:
        """Iterate significant tokens, including closing tokens and EOF if present."""
        return self._node._tokens()

    def walk(self) -> Iterator[nodes.Node]:
        """Pre-order traversal, including the wrapped node, keys and prefixes."""
        return self._node._walk()

    def render(self, *, pretty: bool = False, indent: str | int = "    ") -> str:
        """Serialize losslessly by default, or regenerate layout without mutation."""
        return render(self._node, pretty=pretty, indent=indent)

    def __repr__(self) -> str:
        return f"{type(self).__name__}(node={self._node!r})"


class ContainerAPI(NodeAPI[_ContainerT]):
    """Ordered container operations with unambiguous data/node/source inputs.

    add(key, value) constructs an assignment. append/insert accept only detached
    syntax nodes. add_script/insert_script parse source explicitly. Legacy node
    methods remain available separately; this API never guesses a string's role.
    """

    __slots__ = ()

    def __init__(self, node: _ContainerT) -> None:
        if not isinstance(node, nodes.Container):
            raise TypeError("ContainerAPI requires a container node")
        super().__init__(node)

    @property
    def children(self) -> list[nodes.Node]:
        """Live managed child list; low-level edits maintain parent links, not layout."""
        return self._node._children

    @children.setter
    def children(self, value: Iterable[nodes.Node]) -> None:
        self._node._children = value

    def entries(self, key: str | None = None, *, recursive: bool = False) -> Iterator[nodes.Assignment]:
        """Yield assignment occurrences in order, optionally filtering/nesting."""
        return self._node._entries(key, recursive=recursive)

    def entry(self, key: str) -> nodes.Assignment:
        """Get exactly one assignment; raise KeyError or DuplicateKeyError otherwise."""
        return self._node._entry(key)

    def getall(self, key: str) -> list[nodes.ValueNode]:
        """Always return a snapshot list of matching value nodes, including zero/one."""
        return self._node._getall(key)

    def add(self, key: str, value: nodes.ValueInput, operator: str = "=") -> nodes.Assignment:
        """Append a new key/value assignment, even if the key already exists.

        Native scalars become Scalars and sequences become Blocks. Strings are
        always data, never script source. Existing nodes must be detached.
        """
        return self._node._add(key, value, operator)

    def append(self, node: _InsertT) -> _InsertT:
        """Attach a detached syntax node at the end, adding lexical separators."""
        _require_insertable(node)
        return self._node._insert(len(self._node), node)

    def insert(self, index: SupportsIndex, node: _InsertT) -> _InsertT:
        """Insert a detached syntax node using list.insert index semantics."""
        _require_insertable(node)
        return self._node._insert(index, node)

    def add_script(self, source: str) -> nodes.Node | list[nodes.Node]:
        """Parse and append source; return one node or a list for zero/many.

        Parsing errors leave the destination unchanged. Fragment comments are
        retained, including comments after the last statement. No BOM is allowed.
        """
        if not isinstance(source, str):
            raise TypeError("add_script() requires script source text")
        return self._node._add(source)

    def insert_script(self, index: SupportsIndex, source: str) -> nodes.Node | list[nodes.Node]:
        """Parse source and insert its statements before a structural child index."""
        if not isinstance(source, str):
            raise TypeError("insert_script() requires script source text")
        return self._node._insert(index, source)


def _require_insertable(node: nodes.InsertNode) -> None:
    if not isinstance(node, (nodes.Scalar, nodes.Block, nodes.Prefixed, nodes.Assignment, nodes.Conditional)):
        raise TypeError("append()/insert() require a syntax node; use Scalar(...) for data or *_script() for source")


def render(node: nodes.Node, *, pretty: bool = False, indent: str | int = "    ") -> str:
    """Serialize a syntax node, also exposed by node._api.render(...).

    Preserve tokens/trivia by default. With ``pretty=True``, regenerate layout
    using spaces/tabs or an integer space count, without mutating the tree.
    Accept any syntax subtree, not only documents. Non-node input raises
    TypeError; formatting errors propagate unchanged.
    """
    if not isinstance(node, nodes.Node):
        raise TypeError("render() requires a syntax node")
    if pretty:
        from .formatter import render_pretty

        return render_pretty(node, indent=indent)
    return "".join(token.render() for token in node._tokens())


@overload
def api(node: _ContainerArg) -> ContainerAPI[_ContainerArg]: ...


@overload
def api(node: _NodeArg) -> NodeAPI[_NodeArg]: ...


def api(node: nodes.Node) -> NodeAPI[nodes.Node]:
    """Return the typed live API view, also exposed by node._api.

    Container nodes receive ContainerAPI; all other nodes receive NodeAPI.
    Views share the underlying node, but wrapper identity is not guaranteed.
    """
    if isinstance(node, nodes.Container):
        return ContainerAPI(node)
    return NodeAPI(node)
