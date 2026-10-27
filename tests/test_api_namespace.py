import unittest

from cklang import Assignment, Block, Conditional, Document, Prefixed, Scalar, parse


class ApiNamespaceTests(unittest.TestCase):
    def test_all_former_container_api_names_are_available_as_data(self):
        keys = [
            "parent", "assignment", "span", "tokens", "render", "walk", "comments",
            "leading_comments", "trailing_comments", "children", "entry", "entries",
            "getall", "append", "add", "open", "close", "parameter", "eof", "encoding",
            "value", "text", "kind", "quoted", "key", "operator", "modifier", "prefix",
        ]
        source = " ".join(f"{key}={index}" for index, key in enumerate(keys))
        tree = parse(source)
        for index, key in enumerate(keys):
            with self.subTest(key=key):
                self.assertIs(getattr(tree, key), tree[key])
                self.assertEqual(getattr(tree, key).value, index)
        self.assertEqual(tree._api.render(), source)
        self.assertEqual([name for name in dir(tree) if not name.startswith("_")], sorted(keys))

    def test_reserved_keys_remain_available_by_brackets_only(self):
        tree = parse('_parent=1 _children=2 _render=3 _custom=4 __dict__=5')
        self.assertIsNone(tree._parent)
        self.assertIsInstance(tree._children, list)
        self.assertTrue(callable(tree._api.render))
        self.assertFalse(hasattr(tree, "_render"))
        self.assertIsInstance(tree.__dict__, dict)
        self.assertEqual(tree["_parent"].value, 1)
        self.assertEqual(tree["_children"].value, 2)
        self.assertEqual(tree["_render"].value, 3)
        self.assertEqual(tree["__dict__"].value, 5)
        self.assertNotIn("_custom", dir(tree))
        with self.assertRaises(AttributeError):
            _ = tree._custom

    def test_every_container_has_only_prefixed_intrinsics(self):
        for node in [Document(), Block(), Conditional("PARAM")]:
            self.assertEqual([name for name in dir(node) if not name.startswith("_")], [])
            node._add("parent", 1)
            node._add("render", 2)
            node._add("parameter", 3)
            self.assertEqual(node.parent.value, 1)
            self.assertEqual(node.render.value, 2)
            self.assertEqual(node.parameter.value, 3)
            self.assertIsNone(node._parent)
            self.assertIn("_getall", dir(node))
            self.assertEqual([n.value for n in node._getall("render")], [2])
        self.assertEqual(node._parameter, "PARAM")

    def test_type_specific_properties_keep_their_names(self):
        scalar = Scalar(100)
        entry = Assignment("gold", scalar, ">=")
        self.assertEqual(scalar.value, 100)
        scalar.set(250)
        self.assertEqual(scalar.text, "250")
        self.assertEqual(scalar.kind, "integer")
        self.assertFalse(scalar.quoted)
        self.assertEqual(entry.key.value, "gold")
        self.assertIs(entry.value, scalar)
        self.assertIsNone(entry.modifier)
        scalar._assignment.operator = "<="
        self.assertEqual(entry.operator, "<=")
        self.assertIs(scalar._parent, entry)
        prefixed = Prefixed("rgb", [1, 2, 3])
        self.assertEqual(prefixed.prefix.value, "rgb")
        self.assertIsInstance(prefixed.value, Block)
        self.assertEqual(prefixed.value[0].value, 1)

    def test_common_api_and_comments_work_on_all_node_types(self):
        tree = parse('# heading\ncolor=rgb { # number\n1 } # inline\n')
        for node in tree._walk():
            self.assertTrue(callable(node._tokens))
            self.assertTrue(callable(node._api.render))
            self.assertTrue(callable(node._walk))
            self.assertIsNotNone(node._span)
            self.assertIsInstance(node._leading_comments, list)
            self.assertIsInstance(node._trailing_comments, list)
        self.assertEqual([c.text for c in tree._comments], ["# heading", "# number", "# inline"])
        self.assertEqual(tree.color._trailing_comments[0].text, "# inline")
        self.assertIs(tree.color.value[0]._assignment, tree._entry("color"))

    def test_freed_names_still_handle_duplicates_and_dir_updates(self):
        tree = parse('parent=1 parent=2')
        self.assertEqual([node.value for node in tree.parent], [1, 2])
        tree._children.pop()
        self.assertEqual(tree.parent.value, 1)
        tree._entry("parent").key.value = "render"
        self.assertNotIn("parent", dir(tree))
        self.assertIn("render", dir(tree))
        self.assertEqual(tree.render.value, 1)
        with self.assertRaises(AttributeError):
            _ = tree.parent


if __name__ == "__main__":
    unittest.main()
