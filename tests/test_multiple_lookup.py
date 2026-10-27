import unittest

from cklang import Block, DuplicateKeyError, Scalar, parse


class MultipleLookupTests(unittest.TestCase):
    def test_single_and_multiple_values(self):
        tree = parse('root={ gold=100 trait=brave trait=calm }')
        self.assertIsInstance(tree.root.gold, Scalar)
        self.assertIs(tree.root.gold, tree.root["gold"])
        self.assertEqual(tree.root.trait, tree.root["trait"])
        self.assertEqual([node.value for node in tree.root.trait], ["brave", "calm"])
        self.assertEqual(tree.root._getall("gold"), [tree.root.gold])
        self.assertEqual(tree.root._getall("missing"), [])

    def test_blocks_are_not_confused_with_multiple_occurrences(self):
        tree = parse('traits={ brave calm } option={ name=a } option={ name=b }')
        self.assertIsInstance(tree.traits, Block)
        self.assertIsInstance(tree.option, list)
        self.assertEqual([option.name.value for option in tree.option], ["a", "b"])
        self.assertIs(tree.option[0], tree["option"][0])
        self.assertIs(tree[0], tree._entry("traits"))

    def test_values_are_live_nodes_but_list_is_a_snapshot(self):
        tree = parse('gold>=100 gold<=200')
        source = tree._api.render()
        values = tree.gold
        values.pop()
        self.assertEqual(len(tree.gold), 2)
        self.assertEqual(tree._api.render(), source)
        values[0].value = 150
        values[0]._assignment.operator = ">"
        self.assertEqual(tree._api.render(), 'gold>150 gold<=200')
        self.assertIs(values[0]._parent._parent, tree)

    def test_mutations_change_lookup_cardinality(self):
        tree = parse('trait=brave')
        scalar = tree.trait
        tree._add("trait", "calm")
        self.assertIs(tree.trait[0], scalar)
        tree._children.pop()
        self.assertIs(tree.trait, scalar)
        tree._children.clear()
        with self.assertRaises(KeyError):
            _ = tree["trait"]
        with self.assertRaises(AttributeError):
            _ = tree.trait

    def test_strict_assignment_and_writes_still_reject_duplicates(self):
        tree = parse('trait=brave trait=calm')
        source = tree._api.render()
        with self.assertRaises(DuplicateKeyError):
            tree._entry("trait")
        with self.assertRaises(DuplicateKeyError):
            tree["trait"] = "honest"
        self.assertEqual(tree._api.render(), source)
        tree.trait[1].value = "honest"
        self.assertEqual([node.value for node in tree.trait], ["brave", "honest"])


if __name__ == "__main__":
    unittest.main()
