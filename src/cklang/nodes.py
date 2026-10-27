"""Editable ordered syntax trees. A block is never guessed to be a dict/list."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from datetime import date
from decimal import Decimal
import math
import keyword
import operator as index_operator
import re
import reprlib
from typing import TYPE_CHECKING, Literal, Protocol, Self, SupportsIndex, TypeAlias, TypeVar, cast, overload

from .errors import DuplicateKeyError, Span
from .facade import ContainerAPI, NodeAPI, api
from .lexer import Token, Trivia, lex, synthetic


ScalarInput: TypeAlias = str | int | float | bool | Decimal | date
ScalarValue: TypeAlias = str | int | bool | Decimal
ScalarKind: TypeAlias = Literal[
    "string", "symbol", "integer", "decimal", "boolean", "date",
    "variable", "expression", "operator",
]

# Jedi's runtime property inspection crashes on Literal return annotations
# (TreeInstance.with_generics), preventing *all* completions for a Scalar.
# Keep the public Literal alias and precise static contract, but expose the
# equivalent concrete runtime category to introspection-based completion engines.
if TYPE_CHECKING:
    _KindReturn: TypeAlias = ScalarKind
else:
    _KindReturn: TypeAlias = str

_InsertedNode = TypeVar("_InsertedNode", bound="Scalar | Block | Prefixed | Assignment | Conditional")


class _MissingValue:
    """Distinguish the fragment/node form of _add from key/value construction."""


_MISSING_VALUE = _MissingValue()


class Node:
    """Base syntax node with lossless rendering, traversal and ownership.

    Use cklang.api(node) or node._api for public operations, leaving container
    attribute names available for script data. Earlier underscore operations
    remain compatible. Each attached node has one parent; copying a subtree
    with deepcopy/pickle deliberately omits its ancestors.
    """

    _child_fields: tuple[str, ...] = ()
    _parent_node: Node | None = None

    def __setattr__(self, name: str, value: object) -> None:
        if name in type(self)._child_fields:
            old = self.__dict__.get(name)
            if name in self.__dict__ and old is value:
                return
            if value is not None:
                if not isinstance(value, Node):
                    raise TypeError(f"{name} must be a syntax node")
                _check_attachment(self, value)
            if old is not None:
                object.__setattr__(old, "_parent_node", None)
            object.__setattr__(self, name, value)
            if value is not None:
                object.__setattr__(value, "_parent_node", self)
        else:
            object.__setattr__(self, name, value)

    def __getstate__(self) -> dict[str, object]:
        # Copies of a subtree must not pull in its ancestors. Rebuild ownership
        # from downward edges on deepcopy/unpickle, including managed children.
        state: dict[str, object] = {key: value for key, value in self.__dict__.items() if key != "_parent_node"}
        if "_child_list" in state:
            children = cast(_Children, state.pop("_child_list"))
            state["_children"] = list(children)
        return state

    def __setstate__(self, state: dict[str, object]) -> None:
        for name, value in state.items():
            setattr(self, name, value)

    @property
    def _api(self) -> NodeAPI[Self]:
        """Typed live API view, equivalent to cklang.api(self); never cached."""
        return api(self)

    @property
    def _parent(self) -> Node | None:
        """Immediate structural parent, or None for a detached/root node."""
        return self._parent_node

    @property
    def _assignment(self) -> Assignment | None:
        """Nearest enclosing assignment (self for an Assignment), if any."""
        node: Node | None = self
        while node is not None:
            if isinstance(node, Assignment):
                return node
            node = node._parent
        return None

    def __repr__(self) -> str:
        return _node_repr(self)

    def __str__(self) -> str:
        """A concise summary; use the API's render() for script source."""
        return repr(self)

    def _tokens(self) -> Iterator[Token]:
        """Yield significant tokens in source order, including closing tokens."""
        raise NotImplementedError

    @property
    def _span(self) -> Span | None:
        """Original first-token location; not recomputed after edits."""
        return next(self._tokens()).span

    def _walk(self) -> Iterator[Node]:
        """Pre-order traversal, including self (comments are token trivia)."""
        yield self
        for child in self._nodes():
            yield from child._walk()

    def _nodes(self) -> Iterator[Node]:
        """Yield immediate structural children, excluding tokens and trivia."""
        return iter(())

    @property
    def _comments(self) -> Iterator[Trivia]:
        """Comments stored on this subtree's tokens (including descendants)."""
        return (trivia for token in self._tokens() for trivia in token.leading if trivia.kind == "COMMENT")

    @property
    def _leading_comments(self) -> list[Trivia]:
        """Trivia comments attached to the first token, without descendants."""
        return [t for t in next(self._tokens()).leading if t.kind == "COMMENT"]

    @property
    def _trailing_comments(self) -> list[Trivia]:
        """Same-line comments after this node, stored on the following token."""
        following = _following_token(self)
        result = []
        if following is not None:
            for trivia in following.leading:
                if "\n" in trivia.text or "\r" in trivia.text:
                    break
                if trivia.kind == "COMMENT":
                    result.append(trivia)
        return result


class Scalar(Node):
    """One editable value token, preserving its exact original spelling.

    ``value`` converts booleans, integers and decimals without changing ``text``.
    Dates, variables, expressions and scopes remain symbolic strings. Setting a
    value retains existing quotes, or adds quotes when a string needs them.
    """

    token: Token

    def __init__(self, value: ScalarInput, *, quoted: bool | None = None) -> None:
        self.token = synthetic("ATOM", "")
        self.set(value, quoted=quoted)

    @classmethod
    def from_token(cls, token: Token) -> Scalar:
        """Wrap an existing scalar token without rewriting its text or trivia."""
        node = cls.__new__(cls)
        node.token = token
        return node

    @property
    def text(self) -> str:
        """Exact lexical spelling; assignment must contain exactly one token."""
        return self.token.text

    @text.setter
    def text(self, text: str) -> None:
        tokens = list(lex(text))
        if len(tokens) != 2 or tokens[0].leading or tokens[1].leading or tokens[0].kind not in {"ATOM", "STRING", "EXPRESSION", "OPERATOR"}:
            raise ValueError("Expected exactly one scalar token")
        self.token.text = tokens[0].text
        self.token.kind = tokens[0].kind

    @property
    def quoted(self) -> bool:
        """Whether the token is a double-quoted string."""
        return self.token.kind == "STRING"

    @property
    def kind(self) -> _KindReturn:
        """Syntactic classification, not the meaning of a CK3 scope/value."""
        if self.quoted:
            return "string"
        if self.token.kind == "EXPRESSION":
            return "expression"
        if self.token.kind == "OPERATOR":
            return "operator"
        if self.text.startswith("@"):
            return "variable"
        if self.text in {"yes", "no"}:
            return "boolean"
        if re.fullmatch(r"[+-]?\d+", self.text):
            return "integer"
        if re.fullmatch(r"[+-]?(?:\d+\.\d*|\.\d+)(?:[eE][+-]?\d+)?|[+-]?\d+[eE][+-]?\d+", self.text):
            return "decimal"
        if re.fullmatch(r"\d+\.\d+\.\d+", self.text):
            return "date"
        return "symbol"

    @property
    def value(self) -> ScalarValue:
        """Native value, using Decimal for decimals and str for symbolic forms."""
        kind = self.kind
        if kind == "string":
            # Decode only the escapes we can unambiguously reverse; not Python escapes.
            return re.sub(r'\\(["\\])', r'\1', self.text[1:-1])
        if kind == "boolean":
            return self.text == "yes"
        if kind == "integer":
            return int(self.text)
        if kind == "decimal":
            return Decimal(self.text)
        return self.text

    @value.setter
    def value(self, value: ScalarInput) -> None:
        self.set(value)

    def set(self, value: ScalarInput, *, quoted: bool | None = None) -> None:
        """Replace the value; optionally force quoting of string input.

        Raises TypeError for unsupported values and ValueError for non-finite
        numbers or invalid forced-bare text. No formulas are evaluated.
        """
        if isinstance(value, bool):
            text = "yes" if value else "no"
        elif isinstance(value, date):
            text = f"{value.year}.{value.month}.{value.day}"
        elif isinstance(value, (int, float, Decimal)):
            if isinstance(value, float) and not math.isfinite(value) or isinstance(value, Decimal) and not value.is_finite():
                raise ValueError("Non-finite numbers are not script scalars")
            text = str(value)
        elif isinstance(value, str):
            if quoted is None:
                quoted = self.quoted or not _is_bare(value)
            text = '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"' if quoted else value
        else:
            raise TypeError(f"Unsupported scalar: {type(value).__name__}")
        self.text = text

    def _tokens(self) -> Iterator[Token]:
        yield self.token


def _is_bare(text: str) -> bool:
    try:
        tokens = list(lex(text))
    except ValueError:
        return False
    return len(tokens) == 2 and tokens[0].kind in {"ATOM", "EXPRESSION"} and not tokens[0].leading and not tokens[1].leading


def as_node(value: ValueInput) -> ValueNode:
    """Convert native scalars/sequences to nodes, leaving existing nodes intact."""
    if isinstance(value, (Scalar, Block, Prefixed)):
        return value
    if isinstance(value, Sequence) and not isinstance(value, str):
        block = Block()
        for item in cast("Sequence[ValueInput]", value):
            block._append(item)
        return block
    if isinstance(value, (str, int, float, bool, Decimal, date)):
        return Scalar(value)
    raise TypeError(f"Unsupported scalar: {type(value).__name__}")


class Assignment(Node):
    """A key, operator and value, optionally with a declaration modifier.

    Assignments are individual occurrences, never merged with equal keys.
    ``value`` accepts native input as well as value nodes; node replacement
    preserves the previous value's leading trivia and updates ownership.
    """

    _child_fields = ("key", "modifier", "_value")
    key: Scalar
    modifier: Scalar | None
    operator_token: Token
    _value: ValueNode

    def __init__(self, key: str | Scalar, value: ValueInput, operator: str = "=", *, modifier: Scalar | None = None) -> None:
        key_node = key if isinstance(key, Scalar) else Scalar(key)
        value_node = as_node(value)
        self.operator_token = synthetic("OPERATOR", "=", " ")
        self.operator = operator
        nodes: list[Node] = [key_node, value_node]
        if modifier is not None:
            nodes.append(modifier)
        if len({id(node) for node in nodes}) != len(nodes):
            raise ValueError("A node cannot occur twice; use copy.deepcopy()")
        for node in nodes:
            _check_attachment(self, node)
        self.key = key_node
        self.modifier = modifier
        self._value = value_node
        _ensure_space(self._value)

    @property
    def operator(self) -> str:
        """Literal operator or a parameter such as $OPERATOR$; validated on set."""
        return self.operator_token.text

    @operator.setter
    def operator(self, value: str) -> None:
        tokens = list(lex(value))
        if len(tokens) != 2 or (tokens[0].kind != "OPERATOR" and not is_parameter(value)) or tokens[0].leading or tokens[1].leading:
            raise ValueError("Expected one comparison/assignment operator")
        self.operator_token.text = value
        self.operator_token.kind = tokens[0].kind

    @property
    def value(self) -> ValueNode:
        """The value node; assigning a native value constructs/edits that node."""
        return self._value

    @value.setter
    def value(self, value: ValueInput) -> None:
        if isinstance(self._value, Scalar) and isinstance(value, (str, int, float, bool, Decimal, date)):
            self._value.value = value
        else:
            replacement = as_node(value)
            old = self._value
            self._value = replacement
            next(replacement._tokens()).leading = next(old._tokens()).leading

    def _tokens(self) -> Iterator[Token]:
        if self.modifier:
            yield from self.modifier._tokens()
        yield from self.key._tokens()
        yield self.operator_token
        yield from self.value._tokens()

    def _nodes(self) -> Iterator[Node]:
        if self.modifier:
            yield self.modifier
        yield self.key
        yield self.value


def _ensure_space(node: Node, space: str = " ") -> None:
    first = next(node._tokens())
    if not first.leading:
        first.leading = [Trivia("WHITESPACE", space)]


def is_parameter(text: str) -> bool:
    return re.fullmatch(r"\$[^\s$]+\$", text) is not None


class Container(Node):
    """Ordered syntax nodes with data attributes and explicit editing methods.

    A string lookup returns one value node or a list for repeated keys. Integer
    lookup returns a structural child, which may instead be an Assignment or
    Conditional. Missing keys raise KeyError (brackets) or AttributeError (dot).
    """

    _child_list: _Children

    def __init__(self, children: Iterable[Node] | None = None) -> None:
        self._children = list(children) if children is not None else []

    @property
    def _api(self) -> ContainerAPI[Self]:
        """Container operations, separate from the dynamic script data namespace."""
        return api(self)

    @property
    def _children(self) -> list[Node]:
        """Live ordered list; mutations validate ownership but add no spacing."""
        return self._child_list

    @_children.setter
    def _children(self, values: Iterable[Node]) -> None:
        if values is self.__dict__.get("_child_list"):
            return
        values = list(values)
        old = self.__dict__.get("_child_list", ())
        seen = set()
        for node in values:
            if id(node) in seen:
                raise ValueError("A node cannot occur twice; use copy.deepcopy()")
            seen.add(id(node))
            _check_attachment(self, node, allow_owned=True)
        for node in old:
            object.__setattr__(node, "_parent_node", None)
        object.__setattr__(self, "_child_list", _Children(self, values))
        for node in values:
            object.__setattr__(node, "_parent_node", self)

    def __iter__(self) -> Iterator[Node]:
        return iter(self._children)

    def __len__(self) -> int:
        return len(self._children)

    def __getattr__(self, name: str) -> ValueNode | list[ValueNode]:
        # Called only after normal Python lookup. Never expose magic hooks, or
        # fall back to data when an intrinsic descriptor raises AttributeError.
        if not _attribute_name(name) or any(name in cls.__dict__ for cls in type(self).__mro__):
            raise AttributeError(f"{type(self).__name__!s} has no data attribute {name!r}")
        # __getattr__ can run during copying/unpickling, before __init__.
        if "_child_list" not in self.__dict__:
            raise AttributeError(name)
        try:
            return self[name]
        except KeyError:
            raise AttributeError(f"{type(self).__name__!s} has no data attribute {name!r}") from None

    def __dir__(self) -> list[str]:
        names = set(super().__dir__())
        for node in self.__dict__.get("_child_list", ()):
            if isinstance(node, Assignment):
                key = _key_name(node.key)
                if _attribute_name(key):
                    names.add(key)
        return sorted(names)

    def _entries(self, key: str | None = None, *, recursive: bool = False) -> Iterator[Assignment]:
        """Yield assignments in order, optionally filtering/nesting by key."""
        nodes = self._walk() if recursive else self._children
        return (
            node for node in nodes
            if isinstance(node, Assignment)
            and (key is None or _key_name(node.key) == key)
        )

    def _getall(self, key: str) -> list[ValueNode]:
        """Return a snapshot of all matching value nodes, including zero/one."""
        return [entry.value for entry in self._entries(key)]

    def _entry(self, key: str) -> Assignment:
        """Get exactly one assignment; raise KeyError or DuplicateKeyError."""
        matches = list(self._entries(key))
        if not matches:
            raise KeyError(key)
        if len(matches) != 1:
            raise DuplicateKeyError(f"{key!r}: {len(matches)} entries; use _getall() or _entries()")
        return matches[0]

    @overload
    def __getitem__(self, key: int) -> Node: ...

    @overload
    def __getitem__(self, key: str) -> ValueNode | list[ValueNode]: ...

    def __getitem__(self, key: str | int) -> Node | list[ValueNode]:
        """One matching value, or an ordered list when the key is repeated."""
        if isinstance(key, int):
            return self._children[key]
        values = self._getall(key)
        if not values:
            raise KeyError(key)
        return values[0] if len(values) == 1 else values

    def __setitem__(self, key: str, value: ValueInput) -> None:
        """Edit one value or create Assignment(key, as_node(value)) if absent.

        Native scalars become Scalar nodes; sequences become Blocks. Strings
        are data here, never parsed as script fragments. Duplicate keys remain
        ambiguous and raise DuplicateKeyError without modifying the tree.
        """
        if not isinstance(key, str):
            raise TypeError("Use _children[index] to replace a syntax node")
        matches = list(self._entries(key))
        if not matches:
            self._add(key, value)
        else:
            self._entry(key).value = value

    def _append(self, value: ValueInput | Assignment | Conditional) -> Node:
        """Append a detached node/native value, returning the attached node.

        Strings are scalar data, not script source; use _add(source) for source.
        """
        node = value if isinstance(value, (Assignment, Conditional)) else as_node(value)
        self._insert_nodes(len(self._children), [node])
        return node

    @overload
    def _add(self, key: str, value: ValueInput, operator: str = "=") -> Assignment: ...

    @overload
    def _add(self, key: _InsertedNode) -> _InsertedNode: ...

    @overload
    def _add(self, key: str) -> Node | list[Node]: ...

    def _add(
        self, key: str | InsertNode, value: ValueInput | _MissingValue = _MISSING_VALUE,
        operator: str = "=",
    ) -> Node | list[Node]:
        """Append a key/value assignment, detached node, or script fragment.

        _add("gold", 10, ">=") retains the original key/value API. With one
        string argument, parse source such as "OR = { value = 10 }". A fragment
        may contain several statements; return the node for one statement or a
        list for zero/many. Comments, including final fragment comments, survive.
        """
        if isinstance(value, _MissingValue):
            if operator != "=":
                raise TypeError("operator requires the key/value form of _add")
            return self._insert(len(self._children), key)
        if not isinstance(key, str):
            raise TypeError("The key/value form of _add requires a string key")
        return self._append(Assignment(key, value, operator))

    @overload
    def _insert(self, index: SupportsIndex, value: _InsertedNode) -> _InsertedNode: ...

    @overload
    def _insert(self, index: SupportsIndex, value: ValueInput | Assignment | Conditional) -> Node | list[Node]: ...

    def _insert(self, index: SupportsIndex, value: ValueInput | Assignment | Conditional) -> Node | list[Node]:
        """Insert nodes/source before a child index, using list.insert indexing.

        Strings are script source; wrap a string in Scalar to insert literal
        text instead. A parse/ownership error leaves the destination unchanged.
        Existing nodes must be detached first, or copied with copy.deepcopy().
        """
        position = index_operator.index(index)
        if position < 0:
            position = max(0, len(self._children) + position)
        position = min(position, len(self._children))
        if isinstance(value, str):
            from .parser import parse

            if value.startswith("\ufeff"):
                raise ValueError("A script fragment must not contain a file BOM")
            fragment = parse(value, filename="<fragment>")
            nodes = list(fragment._children)
            fragment._children.clear()
            self._insert_nodes(position, nodes, fragment._eof.leading)
            return nodes[0] if len(nodes) == 1 else nodes
        node = value if isinstance(value, (Assignment, Conditional)) else as_node(value)
        self._insert_nodes(position, [node])
        return node

    def _insert_nodes(self, index: int, nodes: list[Node], trailing: Sequence[Trivia] = ()) -> None:
        """Attach a batch atomically, keeping safe lexical boundaries and trivia."""
        for node in nodes:
            _check_attachment(self, node)
        if not nodes and not trailing:
            return
        if index < len(self._children):
            following = next(self._children[index]._tokens())
        elif isinstance(self, Document):
            following = self._eof
        elif isinstance(self, (Block, Conditional)):
            following = self._close
        else:
            raise TypeError("Container must provide a closing token")
        # Resolve tokens before changing ownership, then validate the whole batch.
        starts = [next(node._tokens()) for node in nodes]
        original_leading = list(following.leading)
        preamble: list[Trivia] = []
        if (
            isinstance(self, Document) and index == 0 and original_leading
            and original_leading[0].kind == "WHITESPACE" and original_leading[0].text.startswith("\ufeff")
        ):
            # A file signature belongs at the document start, even after prepend.
            preamble = [original_leading.pop(0)]
        inline: list[Trivia] = []
        # Keep an existing same-line comment with the preceding statement/open
        # brace, rather than accidentally transferring it to an inserted node.
        if index > 0 or not isinstance(self, Document):
            for trivia in original_leading:
                if trivia.kind == "WHITESPACE" and ("\n" in trivia.text or "\r" in trivia.text):
                    break
                inline.append(trivia)
            if not any(t.kind == "COMMENT" for t in inline):
                inline = []
        remaining = original_leading[len(inline):]
        if len(nodes) == 1:
            self._children.insert(index, nodes[0])
        else:
            self._children[index:index] = nodes
        for token in starts:
            # A detached node may have carried its former file's BOM. It is not
            # subtree content and must not introduce a signature mid-document.
            token.leading = [
                Trivia(t.kind, t.text.replace("\ufeff", ""), t.span)
                if t.kind == "WHITESPACE" and "\ufeff" in t.text else t
                for t in token.leading
            ]
        if starts:
            starts[0].leading = [*preamble, *inline, *_newline_before(starts[0].leading)]
        suffix = list(trailing)
        if not nodes:
            suffix = [*inline, *_newline_before(suffix)]
        if suffix and suffix[-1].kind == "WHITESPACE" and any(c in suffix[-1].text for c in "\r\n"):
            following.leading = [*suffix, *remaining]
        else:
            following.leading = [*suffix, *_newline_before(remaining)]
        if not starts:
            following.leading = [*preamble, *following.leading]

    def _nodes(self) -> Iterator[Node]:
        return iter(self._children)


class Block(Container):
    """Brace-delimited ordered content, possibly mixing values and assignments."""

    _open: Token
    _close: Token

    def __init__(self, children: Iterable[Node] | None = None) -> None:
        super().__init__(children)
        self._open = synthetic("LBRACE", "{")
        self._close = synthetic("RBRACE", "}", "\n")

    def _tokens(self) -> Iterator[Token]:
        yield self._open
        for child in self._children:
            yield from child._tokens()
        yield self._close


class Conditional(Container):
    """A scripted parameter guard: [[PARAM] ... ] or [[!PARAM] ... ]."""

    _open: Token
    _close: Token

    def __init__(self, parameter: str, children: Iterable[Node] | None = None) -> None:
        super().__init__(children)
        if not parameter or any(c.isspace() or c in "[]" for c in parameter):
            raise ValueError("Invalid parameter condition")
        self._open = synthetic("CONDITION", f"[[{parameter}]")
        self._close = synthetic("RBRACKET", "]", "\n")

    @property
    def _parameter(self) -> str:
        """Guard parameter, including a leading ! for a negated guard."""
        return self._open.text[2:-1]

    def _tokens(self) -> Iterator[Token]:
        yield self._open
        for child in self._children:
            yield from child._tokens()
        yield self._close


class Prefixed(Node):
    """Tagged value such as rgb { ... } or list \"palette\".

    Both the prefix and the value are child nodes, so ownership navigation also
    works from anonymous values inside a tagged block.
    """

    _child_fields = ("prefix", "value")
    prefix: Scalar
    value: ValueNode

    def __init__(self, prefix: str | Scalar, value: ValueInput) -> None:
        prefix_node = prefix if isinstance(prefix, Scalar) else Scalar(prefix)
        value_node = as_node(value)
        if prefix_node is value_node:
            raise ValueError("A node cannot occur twice; use copy.deepcopy()")
        _check_attachment(self, prefix_node)
        _check_attachment(self, value_node)
        self.prefix = prefix_node
        self.value = value_node
        _ensure_space(self.value)

    def _tokens(self) -> Iterator[Token]:
        yield from self.prefix._tokens()
        yield from self.value._tokens()

    def _nodes(self) -> Iterator[Node]:
        yield self.prefix
        yield self.value


class Document(Container):
    """Root container with trailing EOF trivia and the file's output encoding."""

    _eof: Token
    _encoding: str

    def __init__(self, children: Iterable[Node] | None = None) -> None:
        super().__init__(children)
        self._eof = synthetic("EOF", "")
        self._encoding = "utf-8"

    def _tokens(self) -> Iterator[Token]:
        for child in self._children:
            yield from child._tokens()
        yield self._eof


def _attribute_name(name: str) -> bool:
    return name.isidentifier() and not keyword.iskeyword(name) and not name.startswith("_")


def _newline_before(trivia: Sequence[Trivia]) -> list[Trivia]:
    """Add a statement boundary unless the initial whitespace provides one."""
    if trivia and trivia[0].kind == "WHITESPACE" and any(c in trivia[0].text for c in "\r\n"):
        return list(trivia)
    return [Trivia("WHITESPACE", "\n"), *trivia]


def _key_name(key: Scalar) -> str:
    """Decode quoted names without coercing numeric/boolean unquoted keys."""
    return cast(str, key.value) if key.quoted else key.text


_text_repr = reprlib.Repr()
_text_repr.maxstring = 60


def _node_repr(node: Node) -> str:
    """Summarize only immediate metadata, never recursively preview a tree."""
    name = type(node).__name__
    if isinstance(node, Scalar):
        text = f"{name}(kind={node.kind!r}, text={_text_repr.repr(node.text)})"
    elif isinstance(node, Assignment):
        modifier = f", modifier={_text_repr.repr(node.modifier.text)}" if node.modifier is not None else ""
        text = (
            f"{name}(key={_text_repr.repr(node.key.text)}, "
            f"operator={_text_repr.repr(node.operator)}{modifier}, "
            f"value={_value_summary(node.value)})"
        )
    elif isinstance(node, Prefixed):
        text = f"{name}(prefix={_text_repr.repr(node.prefix.text)}, value={_value_summary(node.value)})"
    elif isinstance(node, Container):
        parameter = f"parameter={_text_repr.repr(node._parameter)}, " if isinstance(node, Conditional) else ""
        text = f"{name}({parameter}children={len(node._children)})"
    else:
        text = f"{name}()"
    return text if len(text) <= 300 else text[:296] + "...)"


def _value_summary(node: Node) -> str:
    if isinstance(node, Scalar):
        return _text_repr.repr(node.text)
    return type(node).__name__


def _following_token(node: Node) -> Token | None:
    """Find the next token using ownership, without flattening the document."""
    while node._parent is not None:
        parent = node._parent
        if isinstance(parent, Container):
            index = parent._children.index(node)
            if index + 1 < len(parent._children):
                return next(parent._children[index + 1]._tokens())
            if isinstance(parent, Document):
                return parent._eof
            if isinstance(parent, (Block, Conditional)):
                return parent._close
            raise TypeError("Container must provide a closing token")
        if isinstance(parent, Assignment):
            if node is parent.modifier:
                return next(parent.key._tokens())
            if node is parent.key:
                return parent.operator_token
        if isinstance(parent, Prefixed) and node is parent.prefix:
            return next(parent.value._tokens())
        node = parent
    return None


def _check_attachment(parent: Node, node: Node, *, allow_owned: bool = False) -> None:
    """Reject sharing/cycles before mutating any ownership links."""
    if not isinstance(node, Node):
        raise TypeError("Children must be syntax nodes")
    if node._parent is not None and not (allow_owned and node._parent is parent):
        raise ValueError("Node already has a parent; detach it or use copy.deepcopy()")
    ancestor: Node | None = parent
    while ancestor is not None:
        if ancestor is node:
            raise ValueError("A syntax tree cannot contain cycles")
        ancestor = ancestor._parent


class _Children(list[Node]):
    """Live list of structural children, maintaining single-parent ownership.

    Validate a replacement in full before detaching anything. Lists replaced
    through Container._children become inactive and must not be mutated later.
    No whitespace is inserted here: that is Container._append's responsibility.
    """

    def __init__(self, owner: Container, values: Iterable[Node]) -> None:
        self.owner = owner
        super().__init__(values)

    def __reduce_ex__(self, protocol: SupportsIndex) -> tuple[type[list[Node]], tuple[list[Node]]]:
        # A copied child collection is a plain list of independent nodes, not
        # another live collection bound to the original owner.
        return list, (list(self),)

    def _active(self) -> None:
        """Reject writes through an outdated reference to a replaced list."""
        if self.owner.__dict__.get("_child_list") is not self:
            raise ValueError("This children list was replaced; use node._children")

    def append(self, node: Node) -> None:
        self._active()
        _check_attachment(self.owner, node)
        super().append(node)
        object.__setattr__(node, "_parent_node", self.owner)

    def insert(self, index: SupportsIndex, node: Node) -> None:
        self._active()
        _check_attachment(self.owner, node)
        super().insert(index, node)
        object.__setattr__(node, "_parent_node", self.owner)

    def extend(self, values: Iterable[Node]) -> None:
        self[len(self):] = list(values)

    @overload
    def __setitem__(self, index: SupportsIndex, value: Node) -> None: ...

    @overload
    def __setitem__(self, index: slice, value: Iterable[Node]) -> None: ...

    def __setitem__(self, index: SupportsIndex | slice, value: Node | Iterable[Node]) -> None:
        self._active()
        replacement = list(self)
        if isinstance(index, slice):
            replacement[index] = list(cast(Iterable[Node], value))
        else:
            replacement[index] = cast(Node, value)
        self._replace(replacement)

    def __delitem__(self, index: SupportsIndex | slice) -> None:
        self._active()
        replacement = list(self)
        del replacement[index]
        self._replace(replacement)

    def _replace(self, values: list[Node]) -> None:
        """Commit a validated full-list replacement, preserving this list's id."""
        seen = set()
        for node in values:
            if id(node) in seen:
                raise ValueError("A node cannot occur twice; use copy.deepcopy()")
            seen.add(id(node))
            _check_attachment(self.owner, node, allow_owned=True)
        for node in self:
            object.__setattr__(node, "_parent_node", None)
        super().clear()
        super().extend(values)
        for node in self:
            object.__setattr__(node, "_parent_node", self.owner)

    def pop(self, index: SupportsIndex = -1) -> Node:
        self._active()
        node = super().pop(index)
        object.__setattr__(node, "_parent_node", None)
        return node

    def remove(self, node: Node) -> None:
        self.pop(self.index(node))

    def clear(self) -> None:
        self.__delitem__(slice(None))

    # mypy compares __iadd__ to list.__add__, whose widening overload accepts
    # list[T] for arbitrary T. Mutation must instead accept only Node, exactly
    # like list[Node].__iadd__; widening would violate our ownership invariant.
    def __iadd__(self, values: Iterable[Node]) -> Self:  # type: ignore[override, misc]
        self.extend(values)
        return self

    def __imul__(self, count: SupportsIndex) -> Self:
        self._active()
        replacement = list(self) * count
        self._replace(replacement)
        return self


class _ValueSequence(Protocol):
    """Structural element contract for recursive sequence inputs.

    Indirection through this protocol avoids infinitely expanding a recursive
    union in IDE/Jedi signature matching. Ordinary Sequence implementations such
    as list[str] and tuple[int, ...] satisfy the contract covariantly. Runtime
    construction still accepts actual Sequence objects, not arbitrary iterators.
    """

    def __getitem__(self, index: int, /) -> ValueInput: ...

    def __iter__(self) -> Iterator[ValueInput]: ...

    def __len__(self) -> int: ...


ValueNode: TypeAlias = Scalar | Block | Prefixed
ValueInput: TypeAlias = ScalarInput | ValueNode | _ValueSequence
InsertNode: TypeAlias = ValueNode | Assignment | Conditional
