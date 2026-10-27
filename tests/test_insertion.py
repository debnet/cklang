import copy
import unittest

from cklang import Assignment, Block, Conditional, DuplicateKeyError, ParseError, Scalar, parse


class InsertionTests(unittest.TestCase):
    def test_add_and_insert_detached_nodes(self):
        tree = parse('root={ existing=yes }')
        block = tree.root
        entry = Assignment("gold", 100, ">=")
        self.assertIs(block._add(entry), entry)
        first = Assignment("first", True)
        self.assertIs(block._insert(0, first), first)
        scalar = Scalar("anonymous")
        self.assertIs(block._append(scalar), scalar)
        self.assertEqual([n.key.value for n in block if isinstance(n, Assignment)], ["first", "existing", "gold"])
        self.assertIs(entry._parent, block)
        self.assertIs(entry.value._assignment, entry)
        self.assertIs(scalar._parent, block)
        self.assertEqual(parse(tree._api.render()).root.gold.value, 100)

    def test_index_semantics(self):
        block = Block()
        for value in [1, 2, 3]:
            block._append(value)
        block._insert(-1, Scalar(4))
        block._insert(-100, Scalar(0))
        block._insert(100, Scalar(5))
        self.assertEqual([n.value for n in block], [0, 1, 2, 4, 3, 5])

    def test_setitem_automatically_constructs_assignment_and_scalar(self):
        block = Block()
        block["gold"] = 10
        entry = block._entry("gold")
        self.assertIsInstance(entry, Assignment)
        self.assertIsInstance(entry.value, Scalar)
        self.assertEqual(entry.operator, "=")
        self.assertEqual(entry.value.value, 10)
        self.assertIs(entry._parent, block)
        self.assertIs(entry.value._assignment, entry)
        entry.operator = ">="
        scalar = entry.value
        block["gold"] = 20
        self.assertIs(entry.value, scalar)
        self.assertEqual(entry.operator, ">=")
        self.assertEqual(entry.value.value, 20)
        block["literal"] = "OR = { value = 10 }"
        self.assertIsInstance(block.literal, Scalar)
        self.assertTrue(block.literal.quoted)

    def test_add_complex_script_source(self):
        tree = parse('root={}')
        entry = tree.root._add('OR = { value = 10 scope:actor ?= { alive = yes } }')
        self.assertIsInstance(entry, Assignment)
        self.assertIs(entry, tree.root._entry("OR"))
        self.assertIs(entry.value._parent, entry)
        self.assertEqual(tree.root.OR.value.value, 10)
        self.assertEqual(tree.root.OR["scope:actor"].alive.value, True)
        self.assertEqual(tree.root.OR._entry("scope:actor").operator, "?=")
        self.assertEqual(parse(tree._api.render()).root.OR.value.value, 10)

    def test_multiple_statements_and_guard_fragments(self):
        tree = parse('root={last=yes}')
        added = tree.root._insert(0, 'a=1 a=2 [[PARAM] b=yes ]')
        self.assertIsInstance(added, list)
        self.assertEqual(len(added), 3)
        self.assertIsInstance(added[2], Conditional)
        self.assertEqual([n.value for n in tree.root.a], [1, 2])
        self.assertIs(tree.root[-1], tree.root._entry("last"))
        for node in added:
            self.assertIs(node._parent, tree.root)
        tree.root._add("a", 3)
        with self.assertRaises(DuplicateKeyError):
            tree.root["a"] = 4
        self.assertEqual([n.value for n in parse(tree._api.render()).root.a], [1, 2, 3])

    def test_append_string_is_data_insert_string_is_source(self):
        block = Block()
        literal = block._append("x=1")
        source = block._insert(0, "x=1")
        self.assertIsInstance(literal, Scalar)
        self.assertEqual(literal.value, "x=1")
        self.assertIsInstance(source, Assignment)
        self.assertEqual(block.x.value, 1)

    def test_fragment_comments_and_destination_inline_comments_survive(self):
        tree = parse('root={ old=1 # old inline\n next=2 } # root inline\n')
        added = tree.root._insert(1, '# fragment heading\nnew=3 # fragment tail')
        self.assertEqual([c.text for c in tree.root.old._trailing_comments], ["# old inline"])
        self.assertEqual([c.text for c in added._trailing_comments], ["# fragment tail"])
        self.assertEqual([c.text for c in tree._comments], [
            "# old inline", "# fragment heading", "# fragment tail", "# root inline",
        ])
        rebuilt = parse(tree._api.render())
        self.assertEqual(rebuilt.root.next.value, 2)
        self.assertEqual(rebuilt.root.new.value, 3)
        self.assertEqual([c.text for c in rebuilt._comments], [c.text for c in tree._comments])

    def test_multi_statement_fragment_keeps_its_internal_inline_comments(self):
        tree = parse('root={}')
        first, second = tree.root._add('a=1 # a\nb=2 # b')
        self.assertEqual([c.text for c in first._trailing_comments], ["# a"])
        self.assertEqual([c.text for c in second._trailing_comments], ["# b"])
        self.assertIn('a=1 # a\nb=2 # b', tree._api.render())
        self.assertEqual(tree._api.render(pretty=True), 'root = {\n    a = 1 # a\n    b = 2 # b\n}\n')

    def test_comment_after_opening_brace_stays_before_inserted_statement(self):
        tree = parse('root={ # about root\nold=1 }')
        tree.root._insert(0, "new=2")
        self.assertEqual(tree._api.render(pretty=True), 'root = { # about root\n    new = 2\n    old = 1\n}\n')

    def test_comment_only_and_empty_fragments(self):
        tree = parse('root={}')
        before = tree._api.render()
        self.assertEqual(tree.root._add(""), [])
        self.assertEqual(tree._api.render(), before)
        self.assertEqual(tree.root._add("# only a comment"), [])
        self.assertEqual([c.text for c in tree._comments], ["# only a comment"])
        self.assertEqual(len(tree.root), 0)
        self.assertEqual(len(parse(tree._api.render()).root), 0)

    def test_rejected_operations_do_not_modify_destination_or_shared_node(self):
        tree = parse('root={ old=1 } other={ value=2 }')
        before = tree._api.render()
        for source in ['OR={', 'a="unterminated', '\ufeffa=1']:
            with self.subTest(source=source), self.assertRaises((ParseError, ValueError)):
                tree.root._add(source)
            self.assertEqual(tree._api.render(), before)
        for operation in [
            lambda: tree.root._add(tree.other._entry("value")),
            lambda: tree.root._insert(0, tree.other),
            lambda: tree.root._insert(0, tree.root),
        ]:
            with self.assertRaises(ValueError):
                operation()
            self.assertEqual(tree._api.render(), before)
        clone = copy.deepcopy(tree.other._entry("value"))
        tree.root._add(clone)
        self.assertIs(clone._parent, tree.root)
        self.assertEqual(tree.other.value.value, 2)

    def test_old_key_value_call_and_invalid_argument_combinations(self):
        block = Block()
        entry = block._add(key="gold", value=100, operator=">=")
        self.assertEqual(entry.operator, ">=")
        self.assertIs(entry, block._entry("gold"))
        before = block._api.render()
        with self.assertRaises(TypeError):
            block._add(Scalar("key"), 1)
        with self.assertRaises(TypeError):
            block._add("gold=1", operator=">=")
        self.assertEqual(block._api.render(), before)

    def test_prepend_keeps_destination_bom_at_document_start(self):
        for source in ['\ufeffold=1', '\ufeff# heading\nold=1', '\ufeff']:
            with self.subTest(source=source):
                tree = parse(source)
                tree._insert(0, 'new=2')
                output = tree._api.render()
                self.assertTrue(output.startswith('\ufeff'))
                self.assertEqual(output.count('\ufeff'), 1)
                self.assertEqual(parse(output).new.value, 2)
                self.assertTrue(tree._api.render(pretty=True).startswith('\ufeff'))
        tree = parse('\ufeff')
        tree._add('# comment')
        self.assertTrue(tree._api.render().startswith('\ufeff'))

    def test_detached_file_node_does_not_insert_its_old_bom_inside_a_block(self):
        source = parse('\ufeffx=1')
        node = source._children.pop()
        target = parse('root={}')
        target.root._add(node)
        self.assertNotIn('\ufeff', target._api.render())
        self.assertEqual(parse(target._api.render()).root.x.value, 1)


if __name__ == "__main__":
    unittest.main()
