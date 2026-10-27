"""Keep user-facing examples executable and focused on the public facade."""

import contextlib
import io
import os
from pathlib import Path
import re
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
PYTHON_BLOCK = re.compile(r"^```python[ \t]*\n(.*?)^```[ \t]*$", re.MULTILINE | re.DOTALL)


class DocumentationTests(unittest.TestCase):
    def test_markdown_does_not_promote_legacy_node_members(self):
        # Only the public _api namespace belongs in direct node access examples;
        # metadata, rendering and container methods must use the public facade.
        legacy = re.compile(
            r"\b_(?:assignment|parent|span|tokens|walk|comments|leading_comments|"
            r"trailing_comments|children|entry|entries|getall|add|append|insert|"
            r"encoding|parameter|open|close|eof|nodes|render)\b"
        )
        for path in [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]:
            with self.subTest(path=str(path.relative_to(ROOT))):
                match = legacy.search(path.read_text(encoding="utf-8"))
                self.assertIsNone(match, f"Legacy node member in {path}: {match.group() if match else ''}")

    def test_python_examples_execute_with_synthetic_files(self):
        # Examples in each document share a namespace, as in an interactive
        # session. File-reading examples use these local, synthetic event files,
        # never the user's files or the game installation.
        fixture = (
            'namespace=mon_evenement\nmon_evenement.0001={\n'
            'type=character_event trigger={ gold>=100 }\n'
            'option={ name=first } option={ name=second }\n}\n'
        )
        documents = [ROOT / "README.md", ROOT / "docs" / "api.md", ROOT / "docs" / "development.md"]
        for path in documents:
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=str(path.relative_to(ROOT))), tempfile.TemporaryDirectory() as directory:
                workdir = Path(directory)
                (workdir / "mon_evenement.txt").write_text(fixture, encoding="utf-8")
                namespace = {"__name__": "__documentation__", "source": "root={ gold>=100 }"}
                previous = Path.cwd()
                try:
                    os.chdir(workdir)
                    with contextlib.redirect_stdout(io.StringIO()):
                        for block in PYTHON_BLOCK.finditer(text):
                            line = text[:block.start(1)].count("\n") + 1
                            code = compile(block.group(1), f"{path}:{line}", "exec")
                            exec(code, namespace)
                finally:
                    os.chdir(previous)
                self.assertEqual((workdir / "mon_evenement.txt").read_text(encoding="utf-8"), fixture)


if __name__ == "__main__":
    unittest.main()
