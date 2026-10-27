import unittest

from cklang import Assignment, Block, Conditional, Document, Prefixed, Scalar, Token, api, parse, render


class RenderFunctionTests(unittest.TestCase):
    def test_function_and_views_have_identical_options(self):
        source = '\ufeff# heading\r\nroot={ gold>=100 # inline\r\n}\r\n'
        tree = parse(source)
        for options in [{}, {"pretty": False}, {"pretty": True}, {"pretty": True, "indent": 2}, {"pretty": True, "indent": "\t"}]:
            with self.subTest(options=options):
                expected = render(tree, **options)
                self.assertEqual(render(tree, **options), expected)
                self.assertEqual(api(tree).render(**options), expected)
                self.assertEqual(tree._api.render(**options), expected)
        self.assertEqual(render(tree), source)

    def test_render_accepts_every_syntax_node_type_and_subtrees(self):
        tree = parse('root={ gold=100 color=rgb { 1 2 3 } [[PARAM] alive=yes ] }')
        nodes = [Document(), Block(), Scalar(1), Assignment("x", 2), Prefixed("rgb", [1]), Conditional("P")]
        nodes.extend(tree._walk())
        for node in nodes:
            with self.subTest(node=type(node).__name__):
                self.assertEqual(render(node), node._api.render())
                self.assertEqual(render(node, pretty=True), node._api.render(pretty=True))

    def test_render_is_non_mutating_and_ignored_comments_stay_ignored(self):
        source = '# heading\nx={ a=1 # inline\n}'
        tree = parse(source)
        before = [(t.text, t.span, [(x.kind, x.text, x.span) for x in t.leading]) for t in tree._tokens()]
        render(tree, pretty=True, indent=2)
        self.assertEqual(render(tree), source)
        self.assertEqual(before, [(t.text, t.span, [(x.kind, x.text, x.span) for x in t.leading]) for t in tree._tokens()])
        ignored = parse(source, ignore_comments=True)
        self.assertNotIn("#", render(ignored, pretty=True))

    def test_invalid_input_and_indentation_errors(self):
        for value in [None, "x=1", 42, {}, api(Scalar(1))]:
            with self.subTest(value=value), self.assertRaises(TypeError):
                render(value)
        for indent in [-1, "--", "\n", None]:
            with self.subTest(indent=indent), self.assertRaises((ValueError, TypeError)):
                render(Scalar(1), pretty=True, indent=indent)

    def test_render_data_key_does_not_collide_with_function_or_methods(self):
        tree = parse('render=yes')
        self.assertIs(tree.render.value, True)
        self.assertEqual(render(tree), 'render=yes')
        self.assertEqual(tree._api.render(), 'render=yes')

    def test_lossless_render_uses_the_node_token_stream(self):
        class CustomScalar(Scalar):
            def _tokens(self):
                yield Token("ATOM", "custom")

        node = CustomScalar(1)
        for renderer in [render, lambda value, **kwargs: api(value).render(**kwargs)]:
            self.assertEqual(renderer(node), "custom")

    def test_render_is_available_only_via_function_or_api(self):
        for node in [Document(), Block(), Scalar(1), Assignment("x", 2), Prefixed("rgb", [1]), Conditional("P")]:
            with self.subTest(node=type(node).__name__):
                self.assertNotIn("_render", dir(node))
                self.assertFalse(hasattr(node, "_render"))
                with self.assertRaises(AttributeError):
                    getattr(node, "_render")
                self.assertTrue(callable(node._api.render))


if __name__ == "__main__":
    unittest.main()
