import copy
import pickle
import unittest

from cklang import Assignment, Block, Document, Prefixed, Scalar, parse


class OwnershipTests(unittest.TestCase):
    def assert_links(self, node):
        for child in node._nodes():
            self.assertIs(child._parent, node)
            self.assert_links(child)

    def test_every_parsed_node_has_a_parent_except_root(self):
        tree = parse('scripted_trigger check={ x=1 color=rgb { 1 2 3 } [[PARAM] foo=yes ] }')
        self.assertIsNone(tree._parent)
        self.assertIsNone(tree._assignment)
        self.assert_links(tree)

    def test_assignment_from_scalar_key_modifier_block_and_prefix(self):
        tree = parse('scripted_trigger check={ gold>=100 color=rgb { 1 2 3 } }')
        check = tree._entry("check")
        self.assertIs(check._assignment, check)
        self.assertIs(check.key._assignment, check)
        self.assertIs(check.modifier._assignment, check)
        self.assertIs(tree.check._assignment, check)
        gold = tree.check.gold
        self.assertIs(gold._assignment, tree.check._entry("gold"))
        gold._assignment.operator = "<="
        self.assertEqual(gold._assignment.operator, "<=")
        color = tree.check.color
        for node in [color, color.prefix, color.value, color.value[0]]:
            self.assertIs(node._assignment, tree.check._entry("color"))
        self.assertIn("gold<=100", tree._api.render())

    def test_standalone_and_anonymous_nodes(self):
        self.assertIsNone(Scalar(1)._assignment)
        tree = parse('1 { 2 } [[PARAM] 3 ] x={ { 4 } }')
        for node in [tree[0], tree[1], tree[1][0], tree[2][0]]:
            self.assertIsNone(node._assignment)
        self.assertIs(tree.x[0][0]._assignment, tree._entry("x"))

    def test_constructed_trees_and_replaced_fields(self):
        tree = Document()
        tree["color"] = Prefixed("rgb", [1, 2, 3])
        entry = tree._entry("color")
        old_prefix = tree.color.prefix
        tree.color.prefix = Scalar("hsv")
        self.assertIsNone(old_prefix._parent)
        old_value = entry.value
        entry.value = [4, 5]
        self.assertIsNone(old_value._assignment)
        self.assertIs(entry.value[0]._assignment, entry)
        old_key = entry.key
        entry.key = Scalar("renamed")
        self.assertIsNone(old_key._parent)
        self.assertIs(tree.renamed._assignment, entry)
        self.assert_links(tree)

    def test_replacement_by_scalar_and_no_op(self):
        tree = parse('a=1 b={ 2 }')
        scalar = tree.a
        tree["a"] = 3
        self.assertIs(tree.a, scalar)
        entry = tree._entry("b")
        block = tree.b
        entry.value = entry.value
        self.assertIs(block._assignment, entry)
        tree["b"] = False
        self.assertIsNone(block._parent)
        self.assertIs(tree.b._assignment, entry)

    def test_children_remove_and_move(self):
        tree = parse('a={ x=1 } b={}')
        entry = tree.a._children.pop()
        self.assertIsNone(entry._parent)
        self.assertIs(entry.value._assignment, entry)
        tree.b._children.append(entry)
        self.assertIs(entry._parent, tree.b)
        self.assertIs(entry.value._assignment._parent, tree.b)
        self.assert_links(tree)

    def test_list_mutations_keep_links(self):
        block = Block()
        first, second, third = Scalar(1), Scalar(2), Scalar(3)
        block._children.extend([first, second])
        block._children.insert(1, third)
        block._children.reverse()
        block._children.sort(key=lambda n: n.value)
        self.assert_links(block)
        replacement = Scalar(4)
        block._children[1] = replacement
        self.assertIsNone(second._parent)
        self.assertIs(replacement._parent, block)
        del block._children[::2]
        self.assertIsNone(first._parent)
        self.assertIsNone(third._parent)
        block._children += [Scalar(5)]
        self.assert_links(block)
        block._children *= 1
        self.assert_links(block)
        block._children *= 0
        self.assertIsNone(replacement._parent)
        block._children.append(first)
        block._children.clear()
        self.assertIsNone(first._parent)

    def test_replacing_whole_collection(self):
        tree = parse('a=1 b=2')
        first, second = tree._children
        old_collection = tree._children
        tree._children = [second]
        self.assertIsNone(first._parent)
        self.assertIs(second._parent, tree)
        with self.assertRaises(ValueError):
            old_collection.append(Scalar(3))
        tree._children = tree._children
        self.assert_links(tree)

    def test_failed_construction_does_not_adopt_external_nodes(self):
        tree = parse('x=1')
        key, prefix = Scalar("key"), Scalar("rgb")
        with self.assertRaises(ValueError):
            Assignment(key, tree.x)
        self.assertIsNone(key._parent)
        with self.assertRaises(ValueError):
            Prefixed(prefix, tree.x)
        self.assertIsNone(prefix._parent)
        with self.assertRaises(ValueError):
            Assignment(key, key)
        self.assertIsNone(key._parent)

    def test_rejects_sharing_and_cycles_without_changing_tree(self):
        tree = parse('a={ x=1 } b={ y=2 }')
        source = tree._api.render()
        for operation in [
            lambda: tree.b._children.append(tree.a._children[0]),
            lambda: tree.b._children.extend([tree.a._children[0]]),
            lambda: tree.b._children.__setitem__(0, tree.a._children[0]),
            lambda: tree.a._children.append(tree),
            lambda: tree._entry("a").__setattr__("value", tree),
            lambda: tree._entry("b").__setattr__("value", tree.a),
            lambda: tree._children.__imul__(2),
            lambda: tree.__setattr__("_children", [tree[0], tree[0]]),
        ]:
            with self.subTest(operation=operation):
                with self.assertRaises((ValueError, TypeError)):
                    operation()
                self.assertEqual(tree._api.render(), source)
                self.assert_links(tree)
        with self.assertRaises(TypeError):
            tree._children.append("not a node")
        block = Block()
        entry = block._add("x", 1)
        with self.assertRaises(ValueError):
            entry.value = block
        self.assert_links(block)

    def test_deepcopy_and_pickle_rebuild_local_ownership(self):
        tree = parse('a={ x=1 }')
        for clone in [copy.deepcopy(tree), pickle.loads(pickle.dumps(tree))]:
            self.assertIsNone(clone._parent)
            self.assert_links(clone)
            self.assertIsNot(clone.a.x._assignment, tree.a.x._assignment)
        for clone in [copy.deepcopy(tree.a), pickle.loads(pickle.dumps(tree.a))]:
            self.assertIsNone(clone._parent)
            self.assertIsNone(clone._assignment)
            self.assert_links(clone)
            self.assertIs(clone.x._assignment._parent, clone)
        scalar = copy.deepcopy(tree.a.x)
        self.assertIsNone(scalar._assignment)
        children = copy.deepcopy(tree.a._children)
        self.assertIsNone(children[0]._parent)
        self.assertIs(children[0].value._assignment, children[0])

    def test_api_names_do_not_hide_data(self):
        tree = parse('parent=1 assignment=2 leading_comments=3 trailing_comments=4')
        self.assertIsNone(tree._parent)
        self.assertIsNone(tree._assignment)
        self.assertEqual(tree.parent.value, 1)
        self.assertEqual(tree.assignment.value, 2)
        self.assertEqual(tree.leading_comments.value, 3)
        self.assertEqual(tree.trailing_comments.value, 4)
        self.assertEqual(tree["assignment"].value, 2)
        with self.assertRaises(AttributeError):
            tree._parent = Scalar(1)


class CommentAccessTests(unittest.TestCase):
    def test_leading_and_inline_comments(self):
        tree = parse('# heading\ngold >= # value comment\n100 # inline\n# next\nx=yes\n')
        gold = tree.gold
        self.assertEqual([c.text for c in gold._leading_comments], ["# value comment"])
        self.assertEqual([c.text for c in gold._assignment._leading_comments], ["# heading"])
        self.assertEqual([c.text for c in gold._trailing_comments], ["# inline"])
        self.assertEqual([c.text for c in gold._assignment._trailing_comments], ["# inline"])
        self.assertEqual([c.text for c in gold._assignment._comments], ["# heading", "# value comment"])
        gold._trailing_comments[0].text = "# edited"
        self.assertIn("100 # edited\n", tree._api.render())

    def test_block_and_closing_token_comments(self):
        tree = parse('x={\n# child\ngold=1 # inner inline\n# before close\n} # block inline\n')
        self.assertEqual([c.text for c in tree.x._comments], ["# child", "# inner inline", "# before close"])
        self.assertEqual([c.text for c in tree.x.gold._trailing_comments], ["# inner inline"])
        self.assertEqual([c.text for c in tree.x._trailing_comments], ["# block inline"])
        self.assertEqual([c.text for c in tree.x._assignment._trailing_comments], ["# block inline"])
        self.assertEqual(list(tree.x.gold._comments), [])

    def test_empty_detached_and_next_line_comments(self):
        for node in [Scalar(1), Document(), Block(), Assignment("x", 1)]:
            self.assertEqual(node._trailing_comments, [])
        tree = parse('x=1\n# separate\ny=2')
        self.assertEqual(tree.x._trailing_comments, [])
        self.assertEqual([c.text for c in tree.y._assignment._leading_comments], ["# separate"])
        self.assertEqual(tree.y._trailing_comments, [])


if __name__ == "__main__":
    unittest.main()
