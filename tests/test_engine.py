"""Engine tests. Every expected number here was computed by hand from the stated inputs —
if one of these changes, either the model changed or it broke.

Stdlib ``unittest`` on purpose: a judge can run ``python3 -m unittest discover tests`` with no
install step, and pytest picks the same file up unchanged.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import engine  # noqa: E402
import returns  # noqa: E402

# 20,000 SF office, 90% occupied, $5.0M ask.
#   GPI 400,000 - vacancy 40,000 = 360,000 occupied
#   - credit loss 2% = 7,200 -> rental 352,800
#   + recoveries 60,000 + other 10,000 = EGI 422,800
#   opex: taxes 60,000 (5.0M x 1.2%), insurance 12,000, utilities 8,000,
#         R&M 15,000, G&A 4,000, other 3,000, mgmt 3% of EGI = 12,684
#         total 114,684
#   NOI = 308,116  -> cap 6.163%
DEAL = {
    "name": "Test Office",
    "market": "Columbus, OH",
    "property_type": "office",
    "price": 5_000_000,
    "nra_sf": 20_000,
    "year_built": 1988,
    "income": {
        "gross_potential_rent": 400_000,
        "occupancy_pct": 90,
        "credit_loss_pct": 2.0,
        "recoveries": 60_000,
        "other_income": 10_000,
    },
    "opex": {
        "taxes": 60_000,
        "insurance": 12_000,
        "utilities": 8_000,
        "repairs_maintenance": 15_000,
        "general_admin": 4_000,
        "other_opex": 3_000,
        "management_pct_egi": 3.0,
    },
    "tax_rate_pct": 1.2,
    "debt": [{"name": "Bank 65", "ltv_pct": 65, "rate_pct": 6.75, "amort_years": 25}],
}


class EngineTest(unittest.TestCase):
    def test_noi_bridge_exact(self):
        b = engine.build_noi(engine.normalize(DEAL), 5_000_000)
        self.assertTrue(b["ok"])
        self.assertAlmostEqual(b["vacancy_loss"], -40_000, places=6)
        self.assertAlmostEqual(b["credit_loss"], -7_200, places=6)
        self.assertAlmostEqual(b["rental_revenue"], 352_800, places=6)
        self.assertAlmostEqual(b["egi"], 422_800, places=6)
        self.assertAlmostEqual(b["opex"]["management"], 12_684, places=6)
        self.assertAlmostEqual(b["total_opex"], 114_684, places=6)
        self.assertAlmostEqual(b["noi"], 308_116, places=6)
        self.assertAlmostEqual(b["expense_ratio_pct"], 114_684 / 422_800 * 100, places=6)

    def test_cap_and_verdict(self):
        r = engine.screen(DEAL)
        self.assertEqual(r["verdict"], "REJECT")
        self.assertAlmostEqual(r["cap_rate_pct"], 6.163, places=2)
        failed = {t["test"].split()[0].lower() for t in r["tests"] if not t["pass"]}
        self.assertIn("cap", failed)
        self.assertIn("dscr", failed)

    def test_debt_service_matches_bank_math(self):
        # 65% of 5.0M = 3.25M at 6.75%, 25-year amortization -> ~$269.5k/yr
        ds = engine.amort_payment(3_250_000, 6.75, 25)
        self.assertAlmostEqual(ds, 269_463, delta=300)

    def test_counter_price_binds_on_cap(self):
        r = engine.screen(DEAL)
        cp = r["counter_price"]
        self.assertAlmostEqual(cp["price"], 308_116 / 0.075, delta=cp["price"] * 0.01)
        self.assertIn("cap", cp["binding_constraint"])
        self.assertLess(cp["price"], DEAL["price"])

    def test_counter_price_is_a_pass_when_re_underwritten(self):
        """The counter-offer must actually clear the box — otherwise it is just a lower number."""
        r = engine.screen(DEAL)
        again = engine.screen({**DEAL, "price": r["counter_price"]["price"]})
        self.assertEqual(again["verdict"], "PASS", again.get("reasons"))

    def test_tax_reassessment_follows_price(self):
        """Raising the price must raise the tax line, not just the denominator."""
        low = engine.build_noi(engine.normalize(DEAL), 3_000_000)
        high = engine.build_noi(engine.normalize(DEAL), 9_000_000)
        self.assertGreater(high["opex"]["taxes"], low["opex"]["taxes"])

    def test_incomplete_when_no_income(self):
        r = engine.screen({"name": "No Rent Roll", "price": 1_000_000, "property_type": "office"})
        self.assertEqual(r["verdict"], "INCOMPLETE")
        self.assertIn("gross_potential_rent", r["missing"])

    def test_incomplete_when_no_price(self):
        r = engine.screen({k: v for k, v in DEAL.items() if k != "price"})
        self.assertEqual(r["verdict"], "INCOMPLETE")
        self.assertIn("price", r["missing"])

    def test_irr_exact_single_period(self):
        self.assertAlmostEqual(engine.irr([-100.0, 110.0]), 0.10, places=6)

    def test_irr_multi_year(self):
        # -1000 then 1331 in year 3 -> 10%
        self.assertAlmostEqual(engine.irr([-1000.0, 0.0, 0.0, 1331.0]), 0.10, places=6)

    def test_triage_sweet_spot_below_ask(self):
        t = engine.triage(DEAL, steps=12)
        self.assertIsNotNone(t["sweet_spot"])
        self.assertLess(t["sweet_spot"]["price"], DEAL["price"])
        self.assertEqual(t["sweet_spot"]["verdict"], "PASS")


class ReturnsTest(unittest.TestCase):
    def test_proforma_year_one_is_in_place_and_exit_is_forward_noi(self):
        p = returns.proforma(DEAL)
        y1 = p["years"][0]
        self.assertAlmostEqual(y1["noi"], 308_116, places=6)
        self.assertAlmostEqual(y1["cf_unlevered"], 308_116 - 4_000, places=6)  # office reserves $0.20/SF
        self.assertAlmostEqual(p["exit_cap_pct"], p["going_in_cap_pct"], places=6)
        self.assertIsNotNone(p["unlevered_irr_pct"])
        self.assertIsNotNone(p["equity_multiple"])

    def test_proforma_shape(self):
        p = returns.proforma(DEAL)
        self.assertIsNotNone(p["levered_irr_pct"])
        self.assertEqual(len(p["cashflows_levered"]), p["hold_years"] + 1)
        self.assertEqual(len(p["cashflows_unlevered"]), p["hold_years"] + 1)

    def test_sensitivity_grid_populated(self):
        s = returns.sensitivity(DEAL, exit_cap_deltas=(-50, 0, 50), rent_growth_deltas=(-100, 0, 100))
        self.assertEqual(len(s["grid"]), 3)
        self.assertTrue(all(len(row["irr_pct"]) == 3 for row in s["grid"]))
        self.assertGreater(s["spread_pct"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
