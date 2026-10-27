"""Regression checks for both runtime inspection and actual completion engines.

Jedi/IPython are development dependencies only. Basic installation users can
still run the core tests; integration checks are skipped when not installed.
"""

import importlib.util
import unittest
from typing import Literal, get_origin, get_type_hints

from cklang import Assignment, Prefixed, Scalar, ScalarKind, api, parse


class NodeInspectionTests(unittest.TestCase):
    def test_non_container_properties_are_visible_without_evaluating_them(self):
        objects = [
            (Scalar(1), {"value", "text", "kind", "quoted", "set", "token"}),
            (Assignment("gold", 100), {"key", "value", "operator", "modifier"}),
            (Prefixed("rgb", [1, 2, 3]), {"prefix", "value"}),
        ]
        for node, expected in objects:
            with self.subTest(node=type(node).__name__):
                self.assertTrue(expected.issubset(dir(node)))
                self.assertIn("_api", dir(node))
                self.assertNotIn("_render", dir(node))

    def test_runtime_kind_annotation_is_safe_without_losing_the_public_literal(self):
        self.assertIs(get_origin(ScalarKind), Literal)
        self.assertIs(get_type_hints(Scalar.kind.fget)["return"], str)
        self.assertEqual(Scalar(100).kind, "integer")


@unittest.skipUnless(importlib.util.find_spec("jedi"), "Install .[dev] for Jedi completion tests")
class JediCompletionTests(unittest.TestCase):
    def setUp(self):
        import jedi

        self.jedi = jedi
        tree = parse('root={ prestige>=50 color=rgb{1 2 3} }')
        self.namespace = {
            "tree": tree, "scalar": tree.root.prestige,
            "entry": tree.root.prestige._assignment, "prefixed": tree.root.color,
            "api": api,
        }

    def complete(self, expression):
        return {c.name for c in self.jedi.Interpreter(expression, [self.namespace]).complete()}

    def test_scalar_and_assignment_value_completion(self):
        expected = {"value", "text", "kind", "quoted", "set"}
        for expression in ["scalar.", "tree.root.prestige.", "entry.value."]:
            with self.subTest(expression=expression):
                self.assertTrue(expected.issubset(self.complete(expression)))

    def test_assignment_prefix_and_common_api_completion(self):
        expected = {"key", "operator", "value", "modifier"}
        self.assertTrue(expected.issubset(self.complete("entry.")))
        self.assertTrue(expected.issubset(self.complete("scalar._assignment.")))
        self.assertTrue({"prefix", "value"}.issubset(self.complete("prefixed.")))
        self.assertTrue({"parent", "assignment", "render"}.issubset(self.complete("scalar._api.")))

    def test_static_concrete_node_completion(self):
        for constructor, expected in [
            ("Scalar(1)", {"value", "text", "kind", "quoted"}),
            ('Assignment("gold", 1)', {"key", "value", "operator", "modifier"}),
            ('Prefixed("rgb", [1, 2])', {"prefix", "value"}),
        ]:
            script = f"from cklang import Scalar, Assignment, Prefixed\nnode = {constructor}\nnode."
            with self.subTest(constructor=constructor):
                self.assertTrue(expected.issubset({c.name for c in self.jedi.Script(script).complete()}))

    def test_runtime_facade_completion(self):
        expected = {"add", "append", "insert", "add_script", "insert_script", "getall", "render", "children"}
        self.assertTrue(expected.issubset(self.complete("tree.root._api.")))
        self.assertTrue(expected.issubset(self.complete("api(tree.root).")))
        self.assertTrue({"parent", "assignment", "comments", "render"}.issubset(self.complete("scalar._api.")))

    def test_static_facade_completion(self):
        source = 'from cklang import Block, api\nblock = Block()\n'
        expected = {"add", "append", "insert_script", "entry", "render", "children"}
        for expression in ["block._api.", "api(block)."]:
            with self.subTest(expression=expression):
                completions = self.jedi.Script(source + expression).complete()
                self.assertTrue(expected.issubset({c.name for c in completions}))


@unittest.skipUnless(
    importlib.util.find_spec("IPython") and importlib.util.find_spec("jedi"),
    "Install .[dev] for IPython completion tests",
)
class IPythonCompletionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from IPython.core.interactiveshell import InteractiveShell

        cls.shell = InteractiveShell()
        cls.shell.Completer.use_jedi = True
        tree = parse('root={ prestige>=50 color=rgb{1 2 3} }')
        cls.shell.user_ns.update({"tree": tree, "scalar": tree.root.prestige, "entry": tree.root.prestige._assignment, "api": api})

    def complete(self, expression):
        from IPython.core.completer import provisionalcompleter

        with provisionalcompleter():
            return {c.text.lstrip(".") for c in self.shell.Completer.completions(expression, len(expression))}

    def test_chained_completion_for_non_container_nodes(self):
        for expression, expected in [
            ("scalar.", {"value", "text", "kind", "quoted"}),
            ("tree.root.prestige.", {"value", "text", "kind", "quoted"}),
            ("entry.value.", {"value", "text", "kind"}),
            ("scalar._assignment.", {"key", "operator", "value", "modifier"}),
            ("tree.root.color.", {"prefix", "value"}),
            ("scalar._api.", {"assignment", "parent", "render"}),
        ]:
            with self.subTest(expression=expression):
                self.assertTrue(expected.issubset(self.complete(expression)))

    def test_function_and_property_facade_completion(self):
        expected = {"add", "insert", "append", "add_script", "insert_script", "entry", "children", "render"}
        for expression in ["tree.root._api.", "api(tree.root)."]:
            with self.subTest(expression=expression):
                self.assertTrue(expected.issubset(self.complete(expression)))


if __name__ == "__main__":
    unittest.main()
