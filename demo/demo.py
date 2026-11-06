#!/usr/bin/env python3
"""Demo runner: the arithmetic beats of the 90-second video in one pass.

No LLM call here on purpose — this is the layer that has to be fast and identical every run. The
extraction beat is a live `hermes -z` call in the recording, because that one really does need a
model, and pretending otherwise would be dishonest about what the model is for.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import engine  # noqa: E402

BOLD, DIM, GREEN, RED, YELLOW, OFF = "\033[1m", "\033[2m", "\033[32m", "\033[31m", "\033[33m", "\033[0m"


def head(text):
    print(f"\n{BOLD}{text}{OFF}\n{'─' * 66}")


def money(v):
    return f"${v:,.0f}" if v is not None else "—"


def pct(v, places=3):
    return f"{v:.{places}f}%" if v is not None else "—"


def beat_screen(deal):
    r = engine.screen(deal)
    head("1 · uw_screen — NOI rebuilt from the rent roll, not from the seller's claim")
    units = f"{deal['units']:.0f} units · " if deal.get("units") else ""
    print(f"  {r['deal']} · {units}{money(r['price'])} ({money(r['price_per_unit'])}/unit)")
    print(f"  Gross potential rent   {money(r['gross_potential_rent'])}")
    print(f"  Effective gross income {money(r['egi'])}")
    print(f"  Operating expenses     {money(r['total_opex'])}  "
          f"{DIM}({pct(r['expense_ratio_pct'], 2)} of EGI){OFF}")
    print(f"  Rebuilt NOI            {BOLD}{money(r['noi'])}{OFF}")
    gap = r["noi_claim"] - r["noi"]
    print(f"  Seller's claim         {money(r['noi_claim'])}   {YELLOW}(seller is "
          f"{money(abs(gap))} {'LOW' if gap < 0 else 'HIGH'}){OFF}")
    print(f"  Cap rate               {pct(r['cap_rate_pct'])}")
    print(f"  Breakeven occupancy    {pct(r['breakeven_occupancy_pct'], 2)}")
    print()
    for t in r["tests"]:
        mark = f"{GREEN}PASS{OFF}" if t["pass"] else f"{RED}FAIL{OFF}"
        print(f"    {mark}  {t['test']:<32} actual {t['actual']}")
    cp = r["counter_price"]
    print(f"\n  {BOLD}Verdict: {r['verdict']}{OFF}   bound by {cp['binding_constraint']}")
    print(f"  {BOLD}Counter-price: {money(cp['price'])}{OFF}  "
          f"{DIM}({cp['vs_ask_pct']:+.1f}% vs ask — {money(deal['price'] - cp['price'])} less){OFF}")
    return r


def beat_triage(deal):
    t = engine.triage(deal, steps=9)
    head("2 · uw_triage — where the deal flips (taxes re-run at every price)")
    print(f"  {'price':>12}  {'verdict':<9}{'cap':>8}{'DSCR':>7}")
    for s in t["steps"]:
        color = GREEN if s["verdict"] == "PASS" else RED
        print(f"  {money(s['price']):>12}  {color}{s['verdict']:<9}{OFF}"
              f"{pct(s['cap_rate_pct']):>8}{s['dscr']:>7.2f}")
    print(f"\n  Highest price that still clears every test: "
          f"{BOLD}{money(t['sweet_spot']['price'])}{OFF}")


def beat_reserve_caveat(deal):
    head("3 · the honest part — the same NOI, two conventions, two conclusions")
    base = engine.screen(deal)                      # reserves below the line, per type default
    seller = json.loads(json.dumps(deal))
    seller["reserves"] = 0                          # the seller's convention: reserves ignored
    as_seller = engine.screen(seller)
    for label, r in (("seller's convention (no reserves)", as_seller),
                     ("with reserves, $300/unit", base)):
        after = r["noi"] - (r["reserves"] or 0.0)
        gap = r["noi_claim"] - after
        print(f"  {label:<32} NOI {money(after):>10}   reserves {money(r['reserves']):>7}   "
              f"claim vs model {gap:+,.0f}")
    print(f"\n  {DIM}Same property. The seller's claim is conservative under one convention and "
          f"optimistic under the other.{OFF}")


def main():
    deal = json.loads((ROOT / "examples" / "grandview.json").read_text())
    beat_screen(deal)
    beat_triage(deal)
    beat_reserve_caveat(deal)
    print(f"\n{DIM}github.com/johnnyminer/hermes-underwriting{OFF}\n")


if __name__ == "__main__":
    main()
