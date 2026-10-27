import copy
import pickle
import unittest

from cklang import Block, Conditional, Document, DuplicateKeyError, Scalar, parse


class AttributeNavigationTests(unittest.TestCase):
    def test_nested_navigation_and_editing(self):
        tree = parse('root = { trigger = { gold >= 001 } }')
        self.assertIs(tree.root, tree["root"])
        self.assertIs(tree.root.trigger.gold, tree["root"]["trigger"]["gold"])
        tree.root.trigger.gold.value = 250
        self.assertEqual(tree._api.render(), 'root = { trigger = { gold >= 250 } }')

    def test_python_identifiers_and_keywords(self):
        tree = parse('époque=1066 _hidden=yes match=1 "quoted_name"=2 class=3 "a.b"=4 001=5 "a b"=6')
        for name in ["époque", "match", "quoted_name"]:
            self.assertIs(getattr(tree, name), tree[name])
            self.assertIn(name, dir(tree))
        for name in ["class", "a.b", "001", "a b", "_hidden"]:
            self.assertNotIn(name, dir(tree))
            with self.assertRaises(AttributeError):
                getattr(tree, name)
            self.assertIsInstance(tree[name], Scalar)

    def test_intrinsic_attributes_keep_priority(self):
        tree = parse('children=1 render=2 entries=3 span=4 encoding=5 open=6 __dict__=7')
        self.assertIsInstance(tree._children, list)
        self.assertTrue(callable(tree._api.render))
        self.assertTrue(callable(tree._entries))
        self.assertEqual(tree._span.start, 0)
        self.assertEqual(tree._encoding, "utf-8")
        self.assertIsInstance(tree.__dict__, dict)
        self.assertEqual(tree["children"].value, 1)
        self.assertEqual(tree["render"].value, 2)
        self.assertEqual(tree.children.value, 1)
        self.assertEqual(tree.render.value, 2)
        self.assertEqual(tree.entries.value, 3)
        self.assertEqual(tree.span.value, 4)
        self.assertEqual(tree.encoding.value, 5)
        self.assertEqual(tree.open.value, 6)
        block = parse('x={ open=1 close=2 }').x
        self.assertEqual(block._open.text, "{")
        self.assertEqual(block.open.value, 1)
        self.assertEqual(block["open"].value, 1)

    def test_missing_and_duplicate_keys(self):
        tree = parse('trait=brave trait=calm')
        self.assertIn("trait", dir(tree))
        self.assertEqual(tree.trait, tree._getall("trait"))
        self.assertTrue(hasattr(tree, "trait"))
        with self.assertRaises(DuplicateKeyError):
            tree._entry("trait")
        with self.assertRaises(AttributeError):
            _ = tree.missing
        self.assertFalse(hasattr(tree, "missing"))
        self.assertEqual(getattr(tree, "missing", "default"), "default")
        self.assertEqual([node.value for node in tree._getall("trait")], ["brave", "calm"])

    def test_dir_tracks_add_remove_and_rename(self):
        tree = parse('initial=1')
        self.assertIn("initial", dir(tree))
        entry = tree._entry("initial")
        entry.key.value = "renamed"
        self.assertNotIn("initial", dir(tree))
        self.assertIn("renamed", dir(tree))
        self.assertEqual(tree.renamed.value, 1)
        tree._add("added", 2)
        self.assertIn("added", dir(tree))
        tree._children.remove(entry)
        self.assertNotIn("renamed", dir(tree))
        self.assertNotIn("added", vars(tree))  # no duplicated/cache data

    def test_conditional_and_new_containers(self):
        tree = Document()
        tree["block"] = Block()
        tree.block._add("gold", 3)
        guard = Conditional("PARAM")
        guard._add("value", 4)
        self.assertEqual(tree.block.gold.value, 3)
        self.assertEqual(guard.value.value, 4)
        self.assertIn("gold", dir(tree.block))
        self.assertIn("value", dir(guard))

    def test_magic_hooks_and_copying(self):
        tree = parse('__deepcopy__=1 __setstate__=2 nested={ gold=3 }')
        self.assertNotIn("__deepcopy__", dir(tree))
        with self.assertRaises(AttributeError):
            _ = tree.__deepcopy__
        self.assertEqual(tree["__deepcopy__"].value, 1)
        for cloned in [copy.deepcopy(tree), pickle.loads(pickle.dumps(tree))]:
            self.assertEqual(cloned._api.render(), tree._api.render())
            self.assertIsNot(cloned.nested, tree.nested)
            self.assertEqual(cloned.nested.gold.value, 3)

    def test_uninitialized_container_is_safe_to_inspect(self):
        tree = Block.__new__(Block)
        self.assertIsInstance(dir(tree), list)
        self.assertFalse(hasattr(tree, "missing"))


class RepresentationTests(unittest.TestCase):
    def test_scalars_show_type_and_original_spelling(self):
        scalar = parse('gold=001').gold
        self.assertEqual(repr(scalar), "Scalar(kind='integer', text='001')")
        self.assertEqual(str(scalar), repr(scalar))
        self.assertEqual(scalar._api.render(), "001")

    def test_assignment_and_declaration(self):
        tree = parse('gold >= 100 scripted_trigger valid={ check=yes }')
        text = repr(tree._entry("gold"))
        for part in ["Assignment", "key='gold'", "operator='>='", "value='100'"]:
            self.assertIn(part, text)
        self.assertIn("modifier='scripted_trigger'", repr(tree._entry("valid")))

    def test_containers_are_summaries_without_previews(self):
        tree = parse('x={ 1 trait=brave trait=calm }')
        text = repr(tree.x)
        self.assertEqual(text, "Block(children=3)")
        self.assertNotIn("preview", text)
        self.assertEqual(str(tree), "Document(children=1)")

    def test_prefix_and_conditional(self):
        tree = parse('color=rgb { 1 2 3 } [[!PARAM] gold=4 ]')
        self.assertIn("Prefixed(prefix='rgb'", repr(tree.color))
        self.assertIn("Block", repr(tree.color))
        self.assertIn("parameter='!PARAM'", repr(tree[1]))
        self.assertNotIn("gold", repr(tree[1]))

    def test_summaries_are_bounded_and_do_not_change_source(self):
        source = 'text="' + 'long\\path\n' * 1000 + '" ' + ' '.join(f"key_{i}={i}" for i in range(100))
        tree = parse(source)
        for node in tree._walk():
            self.assertLessEqual(len(repr(node)), 300)
            self.assertEqual(str(node), repr(node))
            self.assertNotIn("\n", repr(node))
        self.assertIn("children=101", repr(tree))
        self.assertNotIn("preview", repr(tree))
        self.assertEqual(tree._api.render(), source)

    def test_depth_is_bounded(self):
        tree = parse("x={" * 100 + "leaf=42" + "}" * 100)
        text = repr(tree)
        self.assertLessEqual(len(text), 300)
        self.assertEqual(text, "Document(children=1)")
        self.assertNotIn("leaf", text)


if __name__ == "__main__":
    unittest.main()
