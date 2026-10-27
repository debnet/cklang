import tempfile
import unittest
from pathlib import Path

from cklang import Block, dump, load, parse, render


def significant(node):
    return [(token.kind, token.text) for token in node._tokens()]


class PrettyTests(unittest.TestCase):
    def test_nested_assignments_and_spacing(self):
        tree = parse('root={gold>=100 OR={value=10 other!=no} empty={}}')
        expected = (
            'root = {\n    gold >= 100\n    OR = {\n        value = 10\n'
            '        other != no\n    }\n    empty = {}\n}\n'
        )
        self.assertEqual(tree._api.render(pretty=True), expected)
        self.assertEqual(render(tree, pretty=True), expected)

    def test_indentation_string_int_tab_and_zero(self):
        tree = parse('root={x={a=1}}')
        two_spaces = 'root = {\n  x = {\n    a = 1\n  }\n}\n'
        self.assertEqual(tree._api.render(pretty=True, indent=2), two_spaces)
        self.assertEqual(tree._api.render(pretty=True, indent="  "), two_spaces)
        self.assertEqual(tree._api.render(pretty=True, indent="\t"), two_spaces.replace("  ", "\t"))
        self.assertEqual(tree._api.render(pretty=True, indent=0), two_spaces.replace("  ", ""))
        self.assertEqual(tree._api.render(pretty=True, indent=""), two_spaces.replace("  ", ""))

    def test_original_whitespace_does_not_influence_layout(self):
        first = parse('a={ b=1 c={ d=2 } }')
        second = parse('\r\n  a\t=\r\n{\r\n\t\t b = 1\n c = {\n d=2\r\n}\r\n}\r\n')
        self.assertEqual(first._api.render(pretty=True), second._api.render(pretty=True))

    def test_comments_keep_order_and_inline_status(self):
        source = '# heading\nroot={ a=1 # a\n# before b\nb={ # open\nc=2 # c\n# before close\n} # b\n} # root\n# eof'
        expected = (
            '# heading\nroot = {\n    a = 1 # a\n    # before b\n    b = { # open\n'
            '        c = 2 # c\n        # before close\n    } # b\n} # root\n# eof\n'
        )
        tree = parse(source)
        self.assertEqual(tree._api.render(pretty=True), expected)
        self.assertEqual([c.text for c in parse(expected)._comments], [c.text for c in tree._comments])

    def test_strings_expressions_prefixes_dates_and_declarations(self):
        source = 'scripted_trigger valid={s="line 1\r\n  line 2 # literal" x=@[ a * 2 ] color=rgb{1 2 3} palette=list "colors" d=1066.9.15}'
        tree = parse(source)
        output = tree._api.render(pretty=True, indent=2)
        self.assertIn('s = "line 1\r\n  line 2 # literal"', output)
        self.assertIn('x = @[ a * 2 ]', output)
        self.assertIn('color = rgb {\n    1\n    2\n    3\n  }', output)
        self.assertIn('palette = list "colors"', output)
        self.assertTrue(output.startswith("scripted_trigger valid = {"))
        self.assertEqual(significant(parse(output)), significant(tree))

    def test_conditionals_mixed_blocks_and_operator_parameters(self):
        tree = parse('[[PARAM] x={one a=1 {2 3}} [[!OTHER] y=yes ] ] OPERATOR = <= count $OPERATOR$ $COUNT$')
        output = tree._api.render(pretty=True)
        self.assertIn('[[PARAM]\n    x = {', output)
        self.assertIn('    [[!OTHER]\n        y = yes\n    ]', output)
        self.assertIn('OPERATOR = <=\ncount $OPERATOR$ $COUNT$', output)
        self.assertEqual(significant(parse(output)), significant(tree))

    def test_comment_trivia_between_key_operator_and_value(self):
        tree = parse('a # key\n= # operator\n{ b=1 }')
        output = tree._api.render(pretty=True)
        rebuilt = parse(output)
        self.assertEqual(significant(rebuilt), significant(tree))
        self.assertEqual([c.text for c in rebuilt._comments], ["# key", "# operator"])

    def test_empty_comment_only_and_bom_documents(self):
        for source, expected in [
            ("", ""), (" \n\t", ""), ("\ufeff", "\ufeff"),
            ("# a\r\n\t# b", "# a\n# b\n"),
            ("\ufeff# heading\r\nx=1", "\ufeff# heading\nx = 1\n"),
            ("x={# inside\n}", "x = { # inside\n}\n"),
        ]:
            with self.subTest(source=source):
                self.assertEqual(parse(source)._api.render(pretty=True), expected)

    def test_non_mutating_and_idempotent(self):
        source = '\ufeff# heading\r\nx={ a=1 # inline\r\nb="text" }\r\n'
        tree = parse(source)
        tokens = [(t.text, t.span, [(x.kind, x.text, x.span) for x in t.leading]) for t in tree._tokens()]
        output = tree._api.render(pretty=True)
        self.assertEqual(tree._api.render(), source)
        self.assertEqual(tree._api.render(pretty=False), source)
        self.assertEqual(tokens, [(t.text, t.span, [(x.kind, x.text, x.span) for x in t.leading]) for t in tree._tokens()])
        self.assertEqual(parse(output)._api.render(pretty=True), output)

    def test_subtree_formatting_and_ignore_comments(self):
        tree = parse('root={ a=1 }')
        self.assertEqual(tree.root._api.render(pretty=True), '{\n    a = 1\n}')
        self.assertEqual(tree.root.a._api.render(pretty=True), "1")
        ignored = parse('root={ # ignored\na=1 } # ignored', ignore_comments=True)
        self.assertEqual(ignored._api.render(pretty=True), 'root = {\n    a = 1\n}\n')
        self.assertEqual(Block()._api.render(pretty=True), "{}")

    def test_invalid_indentation_and_lossless_default(self):
        tree = parse('x=1')
        for indent in [-1, "\n", "--", "\r", True, None]:
            with self.subTest(indent=indent), self.assertRaises((TypeError, ValueError)):
                tree._api.render(pretty=True, indent=indent)
        self.assertEqual(tree._api.render(indent="unused"), 'x=1')

    def test_pretty_file_output(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pretty.txt"
            tree = parse('\ufeffroot={a=1}\r\n')
            dump(tree, path, pretty=True, indent=2)
            self.assertEqual(path.read_bytes(), '\ufeffroot = {\n  a = 1\n}\n'.encode())
            self.assertEqual(load(path)._api.render(), tree._api.render(pretty=True, indent=2))
            original = path.read_bytes()
            with self.assertRaises(ValueError):
                dump(tree, path, pretty=True, indent=-1)
            self.assertEqual(path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
