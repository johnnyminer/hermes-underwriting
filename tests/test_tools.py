"""End-to-end tool tests against a fake plugin context.

Covers the parts a judge can actually check without an LLM: registration, screening, the memo
artifact, the deal book, and the graceful failure when the host LLM is unavailable.
"""

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class FakeState:
    def __init__(self, data_dir):
        self._data = {}
        self.data_dir = Path(data_dir)

    def get(self, key, default=None):
        return self._data.get(key, default)

    def set(self, key, value):
        self._data[key] = value


class FakeCtx:
    def __init__(self):
        self.tools = {}
        self.commands = {}
        self.skills = {}
        self.state = FakeState(tempfile.mkdtemp())
        self.llm = None  # exercised by the graceful-failure test

    def register_tool(self, name, toolset=None, schema=None, handler=None, **kw):
        self.tools[name] = handler

    def register_command(self, name, handler, description="", args_hint=""):
        self.commands[name] = handler

    def register_skill(self, name, path, description="", frontmatter=None):
        self.skills[name] = path


def load_plugin():
    """Load the plugin the way Hermes does: as a package, so relative imports resolve."""
    spec = importlib.util.spec_from_file_location(
        "uw_test_pkg", ROOT / "__init__.py", submodule_search_locations=[str(ROOT)]
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["uw_test_pkg"] = module
    spec.loader.exec_module(module)
    return module


class PluginTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = FakeCtx()
        cls.plugin = load_plugin()
        cls.plugin.register(cls.ctx)

    def test_registers_seven_tools_command_and_skill(self):
        self.assertEqual(len(self.ctx.tools), 7)
        self.assertIn("uw_screen", self.ctx.tools)
        self.assertIn("underwrite", self.ctx.commands)
        self.assertIn("screen", self.ctx.skills)
        self.assertTrue(Path(self.ctx.skills["screen"]).exists())

    def test_screen_from_example_file(self):
        deal = json.loads((ROOT / "examples" / "maple-ridge.json").read_text())
        out = json.loads(self.ctx.tools["uw_screen"]({"deal": deal}))
        self.assertEqual(out["verdict"], "PASS")
        self.assertGreater(out["noi"], 0)
        self.assertIsNotNone(out["cap_rate_pct"])
        self.assertTrue(out["tests"])

    def test_office_example_rejects_and_prices_a_counter(self):
        deal = json.loads((ROOT / "examples" / "bethel-office.json").read_text())
        out = json.loads(self.ctx.tools["uw_screen"]({"deal": deal}))
        self.assertEqual(out["verdict"], "REJECT")
        self.assertIsNotNone(out["counter_price"]["price"])
        self.assertLess(out["counter_price"]["price"], deal["price"])

    def test_triage_returns_steps_and_sweet_spot(self):
        deal = json.loads((ROOT / "examples" / "bethel-office.json").read_text())
        out = json.loads(self.ctx.tools["uw_triage"]({"deal": deal, "steps": 9}))
        self.assertEqual(len(out["steps"]), 9)
        self.assertIsNotNone(out["sweet_spot"])

    def test_returns_with_sensitivity(self):
        deal = json.loads((ROOT / "examples" / "maple-ridge.json").read_text())
        out = json.loads(self.ctx.tools["uw_returns"]({"deal": deal, "sensitivity": True}))
        self.assertIsNotNone(out["levered_irr_pct"])
        self.assertEqual(len(out["years"]), 5)
        self.assertEqual(len(out["sensitivity"]["grid"]), 7)

    def test_memo_is_written_and_states_the_verdict(self):
        deal = json.loads((ROOT / "examples" / "bethel-office.json").read_text())
        out = json.loads(self.ctx.tools["uw_memo"]({"deal": deal}))
        self.assertTrue(Path(out["memo"]).exists())
        text = Path(out["memo"]).read_text()
        self.assertIn("REJECT", text)
        self.assertIn("The counter", text)
        self.assertIn("Bethel Road Medical Office", text)

    def test_deal_book_roundtrip(self):
        deal = json.loads((ROOT / "examples" / "maple-ridge.json").read_text())
        saved = json.loads(self.ctx.tools["uw_save"]({"deal": deal}))
        self.assertEqual(saved["saved"], "Maple Ridge Apartments")
        listed = json.loads(self.ctx.tools["uw_deals"]({"action": "list"}))
        self.assertGreaterEqual(listed["count"], 1)
        got = json.loads(self.ctx.tools["uw_deals"]({"action": "get", "name": "Maple Ridge Apartments"}))
        self.assertEqual(got["deal"]["price"], 4_550_000)

    def test_extract_without_host_llm_fails_gracefully(self):
        out = json.loads(self.ctx.tools["uw_extract"]({"text": "Some offering memorandum text"}))
        self.assertIn("error", out)

    def test_command_lists_book_and_screens_a_file(self):
        deal = json.loads((ROOT / "examples" / "maple-ridge.json").read_text())
        self.ctx.tools["uw_save"]({"deal": deal})
        book = self.ctx.commands["underwrite"]("list")
        self.assertIn("Deal book", book)
        memo_text = self.ctx.commands["underwrite"](str(ROOT / "examples" / "bethel-office.json"))
        self.assertIn("REJECT", memo_text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
