import tempfile
import unittest
from pathlib import Path

from cklang import ParseError, dump, lex, load, parse


class IgnoreCommentsTests(unittest.TestCase):
    def test_default_and_explicit_false_preserve_comments(self):
        source = '# heading\nx=1 # inline\n# eof'
        for options in [{}, {"ignore_comments": False}]:
            with self.subTest(options=options):
                tree = parse(source, **options)
                self.assertEqual(tree._api.render(), source)
                self.assertEqual(len(list(tree._comments)), 3)

    def test_discards_comments_at_every_position(self):
        source = '# heading\r\nx # key\r\n= # value\r\n{ a=1# inline\r\n# close\r\n}# after\r\n# eof'
        expected = '\r\nx \r\n= \r\n{ a=1\r\n\r\n}\r\n'
        tree = parse(source, ignore_comments=True)
        self.assertEqual(tree._api.render(), expected)
        self.assertEqual(tree.x.a.value, 1)
        self.assertEqual(parse(expected)._api.render(), expected)
        for node in tree._walk():
            self.assertEqual(list(node._comments), [])
            self.assertEqual(node._leading_comments, [])
            self.assertEqual(node._trailing_comments, [])
        self.assertTrue(all(t.kind != "COMMENT" for token in tree._tokens() for t in token.leading))

    def test_hashes_inside_strings_and_expressions_are_untouched(self):
        body = 's="a # string \\"quote\\"\n# still string" e=@[ x # opaque ]'
        tree = parse(body + ' # real comment\n', ignore_comments=True)
        self.assertEqual(tree._api.render(), body + ' \n')
        self.assertIn("# string", tree.s.value)
        self.assertEqual(tree.e.text, '@[ x # opaque ]')
        self.assertEqual(list(tree._comments), [])

    def test_empty_and_comment_only_documents(self):
        for source, expected in [
            ("", ""), ("# comment", ""), ("# one\n# two", "\n"),
            ("\ufeff# comment\r\n", "\ufeff\r\n"), ("# comment\r", "\r"),
        ]:
            with self.subTest(source=source):
                tree = parse(source, ignore_comments=True)
                self.assertEqual(len(tree), 0)
                self.assertEqual(tree._api.render(), expected)
                self.assertEqual(list(tree._comments), [])

    def test_tokens_and_locations_still_refer_to_original_source(self):
        source = '# heading\r\nx={ a=1 # inline\r\nb=2 } # eof'
        before = list(lex(source))
        after = list(lex(source, ignore_comments=True))
        self.assertEqual(len(before), len(after))
        for original, stripped in zip(before, after):
            self.assertEqual(original.kind, stripped.kind)
            self.assertEqual(original.text, stripped.text)
            self.assertEqual(original.span, stripped.span)
            self.assertEqual([t for t in original.leading if t.kind != "COMMENT"], stripped.leading)
        preserved = parse(source)
        ignored = parse(source, ignore_comments=True)
        self.assertEqual(preserved.x.b._span, ignored.x.b._span)
        self.assertEqual(preserved.x.b._assignment._parent, preserved.x)
        self.assertIs(ignored.x.b._assignment._parent, ignored.x)

    def test_errors_keep_filename_and_original_location(self):
        source = '# heading\r\nx={\r\n# another comment\r\ny=}'
        errors = []
        for ignore_comments in [False, True]:
            with self.assertRaises(ParseError) as caught:
                parse(source, filename="test.txt", ignore_comments=ignore_comments)
            errors.append(caught.exception)
        self.assertEqual(errors[0].span, errors[1].span)
        self.assertEqual(str(errors[0]), str(errors[1]))

    def test_load_and_dump_preserve_bom_crlf_and_explicit_encoding(self):
        for encoding, source, expected in [
            ("utf-8", '\ufeff# tête\r\ns="été # texte" # fin\r\n', '\ufeff\r\ns="été # texte" \r\n'),
            ("cp1252", '# tête\r\ns="été" # fin\r\n', '\r\ns="été" \r\n'),
        ]:
            with self.subTest(encoding=encoding), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "source.txt"
                output = Path(directory) / "output.txt"
                original = source.encode(encoding)
                path.write_bytes(original)
                self.assertEqual(load(path, encoding=encoding)._api.render(), source)
                tree = load(path, encoding=encoding, ignore_comments=True)
                self.assertEqual(tree._encoding, encoding)
                self.assertEqual(list(tree._comments), [])
                dump(tree, output)
                self.assertEqual(output.read_bytes(), expected.encode(encoding))
                self.assertEqual(path.read_bytes(), original)

    def test_ignoring_comments_does_not_affect_duplicates_or_edits(self):
        tree = parse('gold>=1 # first\ngold<=2 # second', ignore_comments=True)
        self.assertEqual([node.value for node in tree.gold], [1, 2])
        tree.gold[0]._assignment.operator = ">"
        tree.gold[1].value = 3
        self.assertEqual(tree._api.render(), 'gold>1 \ngold<=3 ')


if __name__ == "__main__":
    unittest.main()
