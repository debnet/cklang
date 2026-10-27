import copy
import pickle
import unittest

from cklang import (
    Assignment, Block, Conditional, ContainerAPI, Document, DuplicateKeyError,
    NodeAPI, ParseError, Prefixed, Scalar, api, parse,
)


class FacadeTests(unittest.TestCase):
    def test_function_and_property_wrap_the_same_original_node(self):
        for node in [Document(), Block(), Conditional("PARAM"), Scalar(1), Assignment("x", 2), Prefixed("rgb", [1])]:
            with self.subTest(node=type(node).__name__):
                expected = ContainerAPI if isinstance(node, (Document, Block, Conditional)) else NodeAPI
                self.assertIs(type(api(node)), expected)
                self.assertIs(type(node._api), expected)
                self.assertIs(api(node).node, node)
                self.assertIs(node._api.node, node)
                self.assertIn("_api", dir(node))

    def test_shared_live_state_without_caching_views_in_the_tree(self):
        block = Block()
        before = vars(block).copy()
        first, second = api(block), block._api
        self.assertEqual(vars(block), before)
        first.add("gold", 100)
        self.assertEqual(second.entry("gold").value.value, 100)
        second.entry("gold").value = 200
        self.assertEqual(first.entry("gold").value.value, 200)
        self.assertIs(first.children, block._children)
        with self.assertRaises(AttributeError):
            first.node = Scalar(1)
        with self.assertRaises(AttributeError):
            block._api = None

    def test_common_metadata_rendering_and_traversal(self):
        source = '# heading\nroot={ gold>=100 # inline\n }'
        tree = parse(source)
        gold = tree.root.gold
        view = api(gold)
        self.assertIs(view.parent, gold._assignment)
        self.assertIs(view.assignment, tree.root._entry("gold"))
        self.assertEqual(view.span, gold._span)
        self.assertEqual(view.trailing_comments[0].text, "# inline")
        self.assertIs(api(tree).node, tree)
        self.assertEqual(api(tree).leading_comments[0].text, "# heading")
        self.assertEqual(list(api(tree).tokens()), list(tree._tokens()))
        self.assertEqual(list(api(tree).walk()), list(tree._walk()))
        self.assertEqual(list(api(tree).comments), list(tree._comments))
        self.assertEqual(api(tree).render(), source)
        self.assertEqual(api(tree).render(pretty=True, indent=2), tree._api.render(pretty=True, indent=2))
        api(gold).assignment.operator = "<="
        self.assertEqual(gold._assignment.operator, "<=")

    def test_script_data_namespace_is_separate(self):
        tree = parse('api=1 _api=2 parent=3 add=4 render=5 children=6')
        self.assertEqual(tree.api.value, 1)
        self.assertEqual(tree["_api"].value, 2)
        self.assertEqual(tree.parent.value, 3)
        self.assertEqual(tree.add.value, 4)
        self.assertEqual(tree.render.value, 5)
        self.assertEqual(tree.children.value, 6)
        self.assertIsNone(tree._api.parent)
        self.assertTrue(callable(tree._api.add))
        self.assertTrue(callable(tree._api.render))
        self.assertIsInstance(tree._api.children, list)

    def test_reads_preserve_duplicate_and_missing_key_contracts(self):
        block = parse('root={ trait=brave trait=calm child={ trait=honest } }').root
        view = api(block)
        self.assertEqual([node.value for node in view.getall("trait")], ["brave", "calm"])
        self.assertEqual([entry.value.value for entry in view.entries("trait", recursive=True)], ["brave", "calm", "honest"])
        self.assertIs(view.entry("child"), block._entry("child"))
        with self.assertRaises(DuplicateKeyError):
            view.entry("trait")
        with self.assertRaises(KeyError):
            view.entry("missing")
        self.assertEqual(view.getall("missing"), [])
        snapshot = view.getall("trait")
        snapshot.pop()
        self.assertEqual(len(view.getall("trait")), 2)

    def test_add_constructs_data_but_append_and_insert_accept_only_nodes(self):
        block = Block()
        view = api(block)
        entry = view.add("gold", 100, ">=")
        self.assertIsInstance(entry, Assignment)
        self.assertEqual(entry.operator, ">=")
        self.assertIs(entry._parent, block)
        literal = view.add("literal", "OR = { value = 10 }")
        self.assertIsInstance(literal.value, Scalar)
        self.assertTrue(literal.value.quoted)
        scalar = Scalar("anonymous")
        self.assertIs(view.append(scalar), scalar)
        first = Assignment("prestige", 50)
        self.assertIs(view.insert(0, first), first)
        self.assertIs(view.children[0], first)
        self.assertIs(first._parent, block)
        before = view.render()
        for value in ["OR = {}", 42, Document(), None]:
            with self.subTest(value=value):
                with self.assertRaises(TypeError):
                    view.append(value)
                with self.assertRaises(TypeError):
                    view.insert(0, value)
                self.assertEqual(view.render(), before)

    def test_script_methods_are_explicit_and_preserve_comments(self):
        block = Block()
        view = block._api
        added = view.add_script('# heading\nOR={ value=10 } # tail')
        self.assertIsInstance(added, Assignment)
        self.assertEqual(block.OR.value.value, 10)
        self.assertEqual([t.text for t in view.comments], ["# heading", "# tail"])
        first = view.insert_script(0, 'prestige >= 50')
        self.assertIsInstance(first, Assignment)
        self.assertIs(view.children[0], first)
        self.assertEqual(first.operator, ">=")
        many = view.add_script('a=1 a=2')
        self.assertIsInstance(many, list)
        self.assertEqual([node.value for node in view.getall("a")], [1, 2])
        self.assertEqual(view.add_script("# only a comment"), [])
        before = view.render()
        with self.assertRaises(ParseError):
            view.add_script('OR={')
        with self.assertRaises(ParseError):
            view.insert_script(0, 'a="unterminated')
        with self.assertRaises(TypeError):
            view.add_script(Scalar(1))
        with self.assertRaises(TypeError):
            view.insert_script(0, Scalar(1))
        self.assertEqual(view.render(), before)

    def test_children_assignment_and_ownership_use_existing_guards(self):
        tree = parse('a={ x=1 } b={}')
        first, second = tree.a._api, api(tree.b)
        entry = first.children[0]
        with self.assertRaises(ValueError):
            second.append(entry)
        first.children.remove(entry)
        second.insert(0, entry)
        self.assertIs(entry._parent, tree.b)
        self.assertEqual(tree.b.x.value, 1)
        second.add("y", 2)
        second.children = reversed(second.children)
        self.assertEqual([entry.key.value for entry in second.children], ["y", "x"])
        with self.assertRaises(ValueError):
            second.children = [entry, entry]
        self.assertIs(entry._parent, tree.b)

    def test_accessing_facades_does_not_change_subtree_copying(self):
        tree = parse('root={ gold=100 }')
        views = [tree._api, api(tree.root), tree.root.gold._api]
        for clone in [copy.deepcopy(tree.root), pickle.loads(pickle.dumps(tree.root))]:
            self.assertIsNone(clone._api.parent)
            self.assertIsNone(clone._api.assignment)
            self.assertIs(clone.gold._api.assignment._parent, clone)
            self.assertEqual(api(clone).render(), api(tree.root).render())
        self.assertIs(views[1].node, tree.root)

    def test_node_only_facade_and_invalid_construction(self):
        view = Scalar(1)._api
        self.assertFalse(hasattr(view, "add"))
        self.assertFalse(hasattr(view, "children"))
        self.assertIsNone(view.parent)
        self.assertIsNone(view.assignment)
        self.assertIn("Scalar", repr(view))
        self.assertIn("ContainerAPI", repr(Block()._api))
        for value in [None, [], "source", 1]:
            with self.assertRaises(TypeError):
                api(value)
        with self.assertRaises(TypeError):
            ContainerAPI(Scalar(1))

    def test_legacy_methods_remain_compatible(self):
        block = Block()
        block._add("x", 1)
        block._add("y=2")
        api(block).add("z", 3)
        block._insert(0, "first=yes")
        self.assertEqual(block._api.render(), api(block).render())
        self.assertEqual([entry.key.value for entry in block._api.entries()], ["first", "x", "y", "z"])


if __name__ == "__main__":
    unittest.main()
