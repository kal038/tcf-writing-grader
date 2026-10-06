"""Unit tests for TCF writing grader CLI."""

import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from main import get_default_prompt_path, load_evaluator_prompt, read_input


class TestTCFEvaluator(unittest.TestCase):
    def test_default_prompt_exists(self):
        prompt_path = get_default_prompt_path()
        self.assertTrue(prompt_path.is_file(), f"Expected {prompt_path} to exist.")
        content = load_evaluator_prompt(prompt_path)
        self.assertIn("TCF Canada", content)
        self.assertIn("Respect de la consigne", content)
        self.assertIn("Cohérence et cohésion", content)
        self.assertIn("Compétence lexicale", content)
        self.assertIn("Compétence grammaticale", content)

    def test_read_input_from_file(self):
        with tempfile.NamedTemporaryFile("w+", encoding="utf-8", delete=False) as f:
            f.write("Bonjour, voici mon essai.")
            temp_path = f.name

        try:
            content = read_input(temp_path)
            self.assertEqual(content, "Bonjour, voici mon essai.")
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_read_input_from_stdin(self):
        with patch("sys.stdin", io.StringIO("Texte depuis stdin")):
            content = read_input("-")
            self.assertEqual(content, "Texte depuis stdin")

    def test_read_input_empty_raises(self):
        with tempfile.NamedTemporaryFile("w+", encoding="utf-8", delete=False) as f:
            f.write("   \n  ")
            temp_path = f.name

        try:
            with self.assertRaises(SystemExit) as cm:
                read_input(temp_path)
            self.assertIn("empty", str(cm.exception))
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_read_input_missing_file_raises(self):
        with self.assertRaises(SystemExit) as cm:
            read_input("non_existent_file_xyz.md")
        self.assertIn("File not found", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
