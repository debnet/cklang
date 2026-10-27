import tempfile
import unittest
import random
from datetime import date
from decimal import Decimal
from pathlib import Path

from cklang import (
    Assignment, Block, Conditional, DuplicateKeyError, ParseError, Prefixed,
    Scalar, dump, lex, load, parse,
)


class RoundTripTests(unittest.TestCase):
    def test_syntax(self):
        samples = [
            "", "\ufeff# uniquement un commentaire\r\n\r\n",
            "a=1 a=1 a>2 a>=3 a<=4 a<5 a!=6 a?=7 a==8 a?!=9",
            'scope:actor = { prev.top_liege ?= root x = flag:test }',
            'mixed = { 1 two x = yes { no } x = no } empty = {}',
            'color=rgb{001 2 .5} color=hsv360 { 10 20 30 } x=list "colors"',
            '@x = 1\n@y = @[ x * (2 + 1) ]\na = @y\ndate = 1066.9.15',
            'scripted_trigger test = { a=yes } scripted_effect other={ x=no }',
            '[[PARAM] x = $PARAM$ [[!OTHER] y = yes ] ]',
            'OPERATOR = <= count $OPERATOR$ $COUNT$',
            's = "line 1\nline 2 # not comment { }" # comment\r\n',
            's="a \\"quote\\" and \\\\path"',
            '# heading\na # key\n = # operator\n{ x=1 # inline\n} # end',
            'key = "" "quoted key"="yes"\nvalues = { yes "yes" 001 +2 -0.00 }',
        ]
        for source in samples:
            with self.subTest(source=source):
                self.assertEqual(parse(source)._api.render(), source)
                self.assertEqual("".join(t.render() for t in lex(source)), source)

    def test_file_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.txt"
            output = Path(directory) / "output.txt"
            raw = '\ufeff# é\r\na="été"\r\n'.encode()
            source.write_bytes(raw)
            dump(load(source), output)
            self.assertEqual(output.read_bytes(), raw)

    def test_explicit_encoding(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.txt"
            output = Path(directory) / "output.txt"
            source.write_bytes('s="été"\r\n'.encode("cp1252"))
            dump(load(source, encoding="cp1252"), output)
            self.assertEqual(output.read_bytes(), source.read_bytes())


class TreeTests(unittest.TestCase):
    def test_duplicates_are_not_lost(self):
        tree = parse("a=1 a=1 a>2")
        self.assertEqual([s.value for s in tree._getall("a")], [1, 1, 2])
        self.assertEqual([e.operator for e in tree._entries("a")], ["=", "=", ">"])
        self.assertEqual(tree["a"], tree._getall("a"))
        self.assertEqual([node.value for node in tree["a"]], [1, 1, 2])
        with self.assertRaises(DuplicateKeyError):
            tree._entry("a")
        with self.assertRaises(DuplicateKeyError):
            tree["a"] = 10
        with self.assertRaises(KeyError):
            _ = tree["missing"]

    def test_keys_are_names_not_typed_values(self):
        tree = parse('001=yes 1=no yes=1 no=2 "quoted key"=3 "001"=4')
        self.assertEqual([node.value for node in tree._getall("001")], [True, 4])
        self.assertIs(tree["1"].value, False)
        self.assertEqual(tree["yes"].value, 1)
        self.assertEqual(tree["no"].value, 2)
        self.assertEqual(tree["quoted key"].value, 3)

    def test_local_edit(self):
        source = '\ufeff# heading\r\nx = {\r\n\tgold >= 001.00 # keep\r\n\tname = "old"\r\n}\r\n'
        tree = parse(source)
        tree["x"]["gold"].value = Decimal("12.50")
        tree["x"]["name"] = 'A "new" name'
        tree["x"]._entry("gold").operator = "<="
        expected = source.replace(">= 001.00", "<= 12.50").replace('"old"', '"A \\"new\\" name"')
        self.assertEqual(tree._api.render(), expected)
        self.assertEqual(parse(tree._api.render())["x"]["name"].value, 'A "new" name')

    def test_structures(self):
        tree = parse('c=rgb { 1 2 3 } x={ one n=2 { inner=yes } } scripted_trigger check={ yes }')
        self.assertIsInstance(tree["c"], Prefixed)
        self.assertEqual(tree["c"].prefix.value, "rgb")
        self.assertEqual([s.value for s in tree["c"].value], [1, 2, 3])
        self.assertEqual(tree._entry("check").modifier.value, "scripted_trigger")
        self.assertIsInstance(tree["x"][0], Scalar)
        self.assertIsInstance(tree["x"][1], Assignment)
        self.assertIsInstance(tree["x"][2], Block)
        self.assertEqual(len(list(tree._entries("inner", recursive=True))), 1)

    def test_construction_and_removal(self):
        tree = parse("a={}")
        tree["a"]._add("gold", 100, ">=")
        tree["a"]._add("gold", 200)
        tree["a"]["traits"] = ["brave", "calm"]
        tree["color"] = Prefixed("rgb", [10, 20, 30])
        tree["a"]._children.remove(next(tree["a"]._entries("gold")))
        rebuilt = parse(tree._api.render())
        self.assertEqual(rebuilt["a"]["gold"].value, 200)
        self.assertEqual([s.value for s in rebuilt["a"]["traits"]], ["brave", "calm"])
        self.assertEqual(rebuilt["color"].prefix.value, "rgb")

    def test_sequence_construction(self):
        tree = parse("")
        tree["numbers"] = range(3)
        tree["nested"] = ("symbol", (True, False))
        self.assertEqual([node.value for node in tree.numbers], [0, 1, 2])
        self.assertEqual(tree.nested[0].value, "symbol")
        self.assertEqual([node.value for node in tree.nested[1]], [True, False])
        tree["plain"] = "symbol"
        self.assertIsInstance(tree.plain, Scalar)
        rebuilt = parse(tree._api.render())
        self.assertEqual([node.value for node in rebuilt.numbers], [0, 1, 2])

    def test_comments(self):
        tree = parse('# before\na = # value\n1 # final\n')
        self.assertEqual([c.text for c in tree._comments], ["# before", "# value", "# final"])
        list(tree._comments)[1].text = "# changed"
        self.assertIn("# changed", tree._api.render())

    def test_conditional(self):
        tree = parse("[[!PARAM] x=$PARAM$ ]")
        self.assertIsInstance(tree[0], Conditional)
        self.assertEqual(tree[0]._parameter, "!PARAM")
        tree[0]["x"] = 42
        self.assertEqual(parse(tree._api.render())[0]["x"].value, 42)

    def test_parameterized_operator(self):
        tree = parse("OPERATOR = <= count $OPERATOR$ $COUNT$")
        self.assertEqual(tree["OPERATOR"].kind, "operator")
        self.assertEqual(tree["OPERATOR"].value, "<=")
        self.assertEqual(tree._entry("count").operator, "$OPERATOR$")
        self.assertEqual(tree["count"].value, "$COUNT$")
        tree["OPERATOR"].text = ">="
        tree._entry("count").operator = "$OTHER$"
        self.assertEqual(parse(tree._api.render())._entry("count").operator, "$OTHER$")

    def test_native_values_and_spelling(self):
        tree = parse('a=001 b=-0.00 c=yes d="yes" e=1066.9.15 f=@x g=@[x+1]')
        self.assertEqual(tree["a"].value, 1)
        self.assertEqual(tree["a"].text, "001")
        self.assertEqual(tree["b"].value, Decimal("-0.00"))
        self.assertIs(tree["c"].value, True)
        self.assertEqual(tree["d"].value, "yes")
        self.assertEqual(tree["e"].kind, "date")
        self.assertEqual(tree["e"].value, "1066.9.15")
        self.assertEqual(tree["f"].kind, "variable")
        self.assertEqual(tree["g"].kind, "expression")
        self.assertEqual(Scalar(date(1066, 9, 15)).text, "1066.9.15")

    def test_unknown_escapes(self):
        scalar = parse(r's="a\n\t\p"')["s"]
        self.assertEqual(scalar.value, r"a\n\t\p")
        scalar.value = scalar.value
        self.assertEqual(parse("s=" + scalar.text)["s"].value, scalar.value)

    def test_original_locations(self):
        scalar = parse("# head\n  x=1")["x"]
        self.assertEqual((scalar._span.start, scalar._span.line, scalar._span.column), (11, 2, 5))
        scalar.value = 100
        self.assertEqual(scalar._span.start, 11)


class ErrorTests(unittest.TestCase):
    def test_malformed_source(self):
        for source in ['a="unfinished', 'a="trailing\\', "a={", "}", "a=", "a= = =", "a=@[1+2", "[[P] x=1", "[[", "[[]]", "[[A B]]", "a=1 ]"]:
            with self.subTest(source=source), self.assertRaises(ParseError):
                parse(source, filename="example.txt")

    def test_error_location(self):
        with self.assertRaises(ParseError) as caught:
            parse("x=1\ny=}", filename="test.txt")
        self.assertEqual(str(caught.exception), "test.txt:2:3: Expected scalar, got RBRACE")

    def test_invalid_edits(self):
        scalar = Scalar("ok")
        for text in ["a b", "", "# comment", "{}", "a\n", " x"]:
            with self.subTest(text=text), self.assertRaises(ValueError):
                scalar.text = text
        with self.assertRaises(ValueError):
            parse("a=1")._entry("a").operator = "bad"
        for value in [None, {}, object()]:
            with self.subTest(value=value), self.assertRaises(TypeError):
                Scalar(value)
        with self.assertRaises(ValueError):
            Scalar(float("nan"))


class GeneratedTests(unittest.TestCase):
    def test_generated_trees_and_local_edits(self):
        rng = random.Random(42)
        for index in range(200):
            tree = parse("# generated\r\n")
            block = Block()
            tree["event"] = block
            for entry_index in range(rng.randrange(1, 10)):
                key = f"key_{entry_index}"
                value = rng.choice([
                    rng.randrange(-1000, 1000), True, False,
                    'a "quoted" string \\ path # { }',
                    Decimal("-0.1250"), ["brave", "calm"],
                    Prefixed("rgb", [1, 2, 3]),
                ])
                block._add(key, value, rng.choice(["=", ">=", "!=", "?="]))
            source = tree._api.render()
            rebuilt = parse(source)
            self.assertEqual(rebuilt._api.render(), source)
            formatted = tree._api.render(pretty=True)
            pretty_tree = parse(formatted)
            self.assertEqual(
                [(t.kind, t.text) for t in pretty_tree._tokens()],
                [(t.kind, t.text) for t in tree._tokens()],
            )
            self.assertEqual(pretty_tree._api.render(pretty=True), formatted)
            block["edited"] = index
            self.assertEqual(parse(tree._api.render())["event"]["edited"].value, index)

    def test_scanner_arbitrary_input(self):
        rng = random.Random(123)
        alphabet = 'abc012 {}[]=?!<>#@\\"$\r\n\t!é'
        for _ in range(1000):
            source = "".join(rng.choices(alphabet, k=rng.randrange(60)))
            try:
                tokens = list(lex(source))
            except ParseError:
                continue
            self.assertEqual("".join(t.render() for t in tokens), source)
            try:
                tree = parse(source)
            except ParseError:
                continue
            self.assertEqual(tree._api.render(), source)


if __name__ == "__main__":
    unittest.main()
