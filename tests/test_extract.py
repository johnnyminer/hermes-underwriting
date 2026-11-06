"""Extraction handler logic, with the host LLM stubbed.

The extraction itself depends on a model, so what is worth testing deterministically is everything
around it: the prompt contract being enforced, provenance surviving the round trip, the artifact
being written to disk, and the warning when a model returns numbers it cannot cite.
"""

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CANNED = {
    "deal": {
        "name": "1420 Grandview Ave",
        "property_type": "multifamily",
        "price": 2950000,
        "units": 24,
        "nra_sf": None,
        "income": {
            "gross_potential_rent": 315360,
            "occupancy_pct": 91.67,
            "other_income": 9600,
            "t12_noi": 188000,
        },
        "opex": {"taxes": 38400, "insurance": 11200, "management": None},
    },
    "provenance": {
        "price": {"source": "om", "quote": "Asking $2,950,000."},
        "units": {"source": "om", "quote": "24-unit multifamily"},
        "income.gross_potential_rent": {
            "source": "derived", "quote": "24 units x $1,095 x 12 = $315,360"},
        "income.occupancy_pct": {"source": "derived", "quote": "22 occupied of 24 units = 91.67%"},
        "income.other_income": {"source": "om", "quote": "Other income: $9,600/yr laundry."},
        "income.t12_noi": {"source": "om", "quote": "Seller's stated NOI: $188,000"},
        "opex.taxes": {"source": "t12", "quote": "real estate taxes $38,400"},
        "opex.insurance": {"source": "t12", "quote": "insurance $11,200"},
    },
}


DOC = ("Asking $2,950,000 for the property. 24-unit multifamily. Taxes were $38,400 last year. "
       "Seller's stated NOI: $188,000.")


class FakeLLM:
    """Stands in for ctx.llm; records what the plugin asked for."""

    def __init__(self, text):
        self.text = text
        self.prompts = []

    def complete(self, messages=None, **kwargs):
        self.prompts.append(messages[0]["content"])

        class R:
            text = self.text

        return R()


class FakeState:
    def __init__(self):
        self.data_dir = Path(tempfile.mkdtemp())
        self._data = {}

    def get(self, key, default=None):
        return self._data.get(key, default)

    def set(self, key, value):
        self._data[key] = value


class FakeCtx:
    def __init__(self, llm_text=None):
        self.state = FakeState()
        self.llm = FakeLLM(llm_text) if llm_text else None


def load_plugin():
    spec = importlib.util.spec_from_file_location(
        "uw_test_extract", ROOT / "__init__.py", submodule_search_locations=[str(ROOT)]
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["uw_test_extract"] = module
    spec.loader.exec_module(module)
    return module


class ExtractTest(unittest.TestCase):
    def setUp(self):
        self.plugin = load_plugin()
        self.ctx = FakeCtx(json.dumps(CANNED))
        self.plugin.tools.bind(self.ctx)
        self.tools = self.plugin.tools.HANDLERS
        self.doc = DOC

    def test_figures_are_matched_back_to_the_document(self):
        out = json.loads(self.tools["uw_extract"]({"text": DOC}))
        self.assertEqual(out["deal"]["price"], 2950000)
        entry = out["provenance"]["price"]
        self.assertTrue(entry["verified"])
        self.assertIn("2,950,000", entry["quote"])
        self.assertGreaterEqual(out["fields_verified"], 4)

    def test_prompt_requires_provenance_and_forbids_invented_numbers(self):
        self.tools["uw_extract"]({"text": "some document"})
        prompt = self.ctx.llm.prompts[0]
        self.assertIn("EVERY non-null field", prompt)
        self.assertIn("data-integrity failure", prompt)

    def test_a_citation_the_document_cannot_support_is_flagged(self):
        invented = json.loads(json.dumps(CANNED))
        invented["deal"]["opex"]["utilities"] = 14800
        invented["provenance"]["opex.utilities"] = {"source": "t12", "quote": "utilities $14,800"}
        plugin = load_plugin()
        plugin.tools.bind(FakeCtx(json.dumps(invented)))
        out = json.loads(plugin.tools.HANDLERS["uw_extract"]({"text": DOC}))
        entry = out["provenance"]["opex.utilities"]
        self.assertFalse(entry["verified"])
        self.assertTrue(any("does not appear" in w for w in out["warnings"]))

    def test_zero_is_not_treated_as_a_missing_verification(self):
        zeroed = json.loads(json.dumps(CANNED))
        zeroed["deal"]["income"]["recoveries"] = 0
        plugin = load_plugin()
        plugin.tools.bind(FakeCtx(json.dumps(zeroed)))
        out = json.loads(plugin.tools.HANDLERS["uw_extract"]({"text": DOC}))
        self.assertNotIn("income.recoveries", out["provenance"])

    def test_writes_artifact_when_asked(self):
        out_path = self.ctx.state.data_dir / "nested" / "extract.json"
        out = json.loads(self.tools["uw_extract"]({"text": DOC, "out_path": str(out_path)}))
        self.assertTrue(out_path.exists())
        saved = json.loads(out_path.read_text())
        self.assertEqual(saved["deal"]["units"], 24)
        self.assertIn("verified", saved["provenance"]["price"])
        self.assertEqual(out["written_to"], str(out_path))

    def test_non_json_model_reply_is_reported_not_crashed(self):
        plugin = load_plugin()
        plugin.tools.bind(FakeCtx("I could not read that document."))
        out = json.loads(plugin.tools.HANDLERS["uw_extract"]({"text": "doc"}))
        self.assertIn("error", out)
        self.assertIn("raw", out)

    def test_missing_document_is_a_clean_error(self):
        out = json.loads(self.tools["uw_extract"]({"path": "/nonexistent/om.pdf"}))
        self.assertIn("could not read the document", out["error"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
