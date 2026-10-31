import json
import os
import re
import unittest

from _load import ROOT

SKILLS = ["prop-scanner", "prop-entry", "prop-exit", "prop-timemachine", "prop-budget", "prop-risk", "prop-broker"]


def every_text_file():
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in (".git", "__pycache__", "fixtures")]
        for f in files:
            if f.endswith((".md", ".py", ".json")) or f == "LICENSE":
                yield os.path.join(base, f)


class Repo(unittest.TestCase):
    def test_skill_folders(self):
        found = sorted(d for d in os.listdir(ROOT) if os.path.isfile(os.path.join(ROOT, d, "SKILL.md")))
        self.assertEqual(found, sorted(SKILLS))

    def test_frontmatter_and_safety_line(self):
        for s in SKILLS:
            with open(os.path.join(ROOT, s, "SKILL.md"), encoding="utf-8") as fh:
                text = fh.read()
            m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
            self.assertTrue(m, s)
            self.assertIn("name: %s\n" % s, m.group(1) + "\n", s)
            self.assertIn("description:", m.group(1), s)
            low = " ".join(text.lower().split())
            self.assertIn("not financial advice", low, s)
            self.assertIn("yes", low, s)

    def test_strategy_is_easy_to_find(self):
        with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as fh:
            readme = fh.read()
        self.assertIn("## Where the strategy is", readme)
        self.assertIn("strategies/orb.py", readme)
        for f in ("orb.py", "template.py", "README.md"):
            self.assertTrue(os.path.exists(os.path.join(ROOT, "strategies", f)), f)

    def test_plugin_manifest(self):
        with open(os.path.join(ROOT, ".claude-plugin", "plugin.json")) as fh:
            plugin = json.load(fh)
        with open(os.path.join(ROOT, ".claude-plugin", "marketplace.json")) as fh:
            market = json.load(fh)
        self.assertEqual(plugin["name"], "day-trader-propfirm")
        self.assertEqual(market["plugins"][0]["name"], "day-trader-propfirm")

    def test_no_em_dashes_and_license_kept(self):
        for path in every_text_file():
            with open(path, encoding="utf-8", errors="replace") as fh:
                self.assertNotIn("\u2014", fh.read(), os.path.relpath(path, ROOT))
        with open(os.path.join(ROOT, "LICENSE")) as fh:
            self.assertIn("MIT", fh.read())

    def test_python_3_8_syntax(self):
        for base, dirs, files in os.walk(ROOT):
            dirs[:] = [d for d in dirs if d not in (".git", "__pycache__", "tests")]
            for f in files:
                if not f.endswith(".py"):
                    continue
                with open(os.path.join(base, f), encoding="utf-8") as fh:
                    src = fh.read()
                rel = os.path.relpath(os.path.join(base, f), ROOT)
                self.assertNotIn("zoneinfo", src, rel)
                self.assertNotIn(".removeprefix(", src, rel)
                self.assertNotRegex(src, r"(?<![\w.\"'])(list|dict|tuple)\[", rel)
                self.assertNotRegex(src, r"(?m)^\s+match \w+.*:$", rel)

    def test_no_secrets_in_example_config(self):
        with open(os.path.join(ROOT, "config.example.json")) as fh:
            text = fh.read().lower()
        self.assertNotIn("api_key", text)


if __name__ == "__main__":
    unittest.main()
