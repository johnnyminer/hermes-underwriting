"""Deterministic commercial real estate underwriting engine.

Rules this module enforces, because they are the rules that keep an analyst honest:

1. **Nothing is invented.** A missing income or expense line is 0 plus a warning, never a
   type default. Defaults only fill *behavioral* gaps (vacancy assumption, management fee).
2. **Seller NOI is a claim, not a fact.** It is carried as `t12_noi_claim` and compared to the
   rebuilt NOI; the difference is reported, never averaged.
3. **Incomplete is not bad.** A deal missing a rent roll gets INCOMPLETE with the missing
   fields named, not a REJECT that hides why.
4. **Every rejection comes with a number.** `max_price` inverts the price-dependent tests, so
   the output is a counter-offer, not an opinion.
5. **Price changes taxes.** Reassessment is recomputed at every triage price, so the sweep is
   not a straight line.

Pure stdlib. No LLM arithmetic anywhere: the model is arithmetic, the model call is prose.
"""

from __future__ import annotations

import math

try:  # loaded as hermes_plugins.<slug>.engine
    from .assumptions import (
        DEFAULT_CLOSING_COST_PCT,
        DEFAULT_CREDIT_LOSS_PCT,
        DEFAULT_GROWTH,
        DEFAULT_TAX_RATE_PCT,
        type_defaults,
    )
except ImportError:  # loaded flat (tests, direct import)
    from assumptions import (
        DEFAULT_CLOSING_COST_PCT,
        DEFAULT_CREDIT_LOSS_PCT,
        DEFAULT_GROWTH,
        DEFAULT_TAX_RATE_PCT,
        type_defaults,
    )

OPEX_LINES = (
    "taxes",
    "insurance",
    "utilities",
    "repairs_maintenance",
    "payroll",
    "general_admin",
    "management",
    "other_opex",
)

# Fields whose absence makes a screen INCOMPLETE rather than a verdict.
REQUIRED = ("price",)
INCOME_REQUIRED = ("gross_potential_rent", "t12_egi", "occupancy_pct", "avg_rent_monthly")


def num(value, default=None):
    """Coerce to float, treating '', None and junk as absent."""
    if value is None or isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    try:
        cleaned = str(value).replace(",", "").replace("$", "").replace("%", "").strip()
        if cleaned in ("", "-", "n/a", "na", "none", "null"):
            return default
        return float(cleaned)
    except (TypeError, ValueError):
        return default


def _flag(provenance, field, source="assumption", quote=""):
    """Record where a number came from. Anything not from a document is an assumption."""
    provenance[field] = {"source": source, "quote": quote, "verified": source in ("om", "rent_roll", "t12")}


def _first(*values):
    """First present value. `or` chains lose explicit zeros, which in underwriting are answers."""
    for v in values:
        if v is not None and v != "":
            return v
    return None


def normalize(deal: dict) -> dict:
    """Canonicalize a loose deal dict into the shape the model expects.

    Idempotent: normalizing an already-normalized deal is a no-op, which is what lets triage
    and the sensitivity grid re-price the same deal without losing its income basis.
    """
    d = dict(deal or {})
    ptype = str(d.get("property_type") or "other").strip().lower().replace("-", "_").replace(" ", "_")
    td = type_defaults(ptype)
    income = dict(d.get("income") or {})
    opex = dict(d.get("opex") or {})
    growth = {**DEFAULT_GROWTH, **{k: v for k, v in (d.get("growth") or {}).items() if v is not None}}

    price = num(_first(d.get("price"), d.get("asking_price")))
    units = num(d.get("units"))
    nra = num(_first(d.get("nra_sf"), d.get("building_sf")))

    # Income basis, in order of evidence quality.
    gpr = num(_first(income.get("gross_potential_rent"), income.get("gpr"), d.get("gross_potential_rent")))
    occupancy = num(_first(income.get("occupancy_pct"), d.get("occupancy_pct")))
    avg_rent = num(_first(income.get("avg_rent_monthly"), d.get("avg_rent_monthly")))
    if gpr is None and avg_rent is not None and units:
        gpr = avg_rent * units * 12.0
    t12_egi = num(_first(income.get("t12_egi"), d.get("t12_egi")))
    other_income = num(_first(income.get("other_income"), d.get("other_income")), 0.0) or 0.0
    if gpr is None and t12_egi is not None and occupancy:
        occ_frac = min(max(occupancy / 100.0, 0.01), 1.0)
        gpr = max(t12_egi - other_income, 0.0) / occ_frac

    if occupancy is not None:
        vacancy_pct = max(0.0, 100.0 - occupancy)
    else:
        vacancy_pct = num(_first(income.get("vacancy_pct"), d.get("vacancy_pct")), td["vacancy_pct"])

    out = {
        "name": d.get("name") or d.get("address") or "Untitled deal",
        "market": d.get("market") or "",
        "property_type": ptype if ptype in ("multifamily", "office", "retail", "industrial",
                                           "self_storage", "mixed", "other") else "other",
        "price": price,
        "units": units,
        "nra_sf": nra,
        "year_built": num(d.get("year_built")),
        "gross_potential_rent": gpr,
        "occupancy_pct": occupancy if occupancy is not None else (100.0 - vacancy_pct),
        "vacancy_pct": vacancy_pct,
        "credit_loss_pct": num(_first(income.get("credit_loss_pct"), d.get("credit_loss_pct")),
                               td["credit_loss_pct"]),
        "other_income": other_income,
        "recoveries": num(_first(income.get("recoveries"), d.get("recoveries")), 0.0) or 0.0,
        "t12_noi_claim": num(_first(income.get("t12_noi"), d.get("t12_noi"), d.get("t12_noi_claim"))),
        "t12_egi": t12_egi,
        "t12_opex": num(_first(income.get("t12_opex"), d.get("t12_opex"))),
        "opex": {k: num(opex.get(k)) for k in OPEX_LINES},
        "management_pct_egi": num(_first(opex.get("management_pct_egi"), d.get("management_pct_egi")),
                                  td["management_pct_egi"]),
        "reserves": num(_first(opex.get("reserves"), d.get("reserves"))),
        "growth": growth,
        "debt": d.get("debt") or d.get("debt_scenarios") or [],
        "closing_cost_pct": num(d.get("closing_cost_pct"), DEFAULT_CLOSING_COST_PCT),
        "tax_rate_pct": num(d.get("tax_rate_pct"), DEFAULT_TAX_RATE_PCT),
        "type_defaults": td,
        "notes": d.get("notes") or "",
    }
    return out


def _reserves(deal: dict, egi: float) -> float:
    if deal["reserves"] is not None:
        return deal["reserves"]
    td = deal["type_defaults"]
    if deal["units"] and td.get("reserves_per_unit"):
        return deal["units"] * td["reserves_per_unit"]
    if deal["nra_sf"] and td.get("reserves_per_sf"):
        return deal["nra_sf"] * td["reserves_per_sf"]
    return egi * (td.get("reserves_pct_egi") or 0.0) / 100.0


def build_noi(deal: dict, price=None) -> dict:
    """Rebuild NOI from the bottom up at *price*. Returns lines, warnings and provenance."""
    price = num(price, deal["price"])
    warnings, provenance = [], {}
    gpr = deal["gross_potential_rent"]

    if gpr is None:
        return {
            "ok": False,
            "noi": None,
            "warnings": ["No income basis: need a rent roll, gross potential rent, T-12 EGI, "
                         "or units x average rent."],
            "provenance": provenance,
            "incomplete": ["gross_potential_rent"],
        }

    occ_frac = min(max((deal["occupancy_pct"] or 0.0) / 100.0, 0.0), 1.0)
    vacancy_loss = gpr * (1.0 - occ_frac)
    occupied_gpr = gpr * occ_frac
    credit_loss = occupied_gpr * (deal["credit_loss_pct"] or 0.0) / 100.0
    rental_revenue = occupied_gpr - credit_loss
    other_income = deal["other_income"] or 0.0
    recoveries = deal["recoveries"] or 0.0
    egi = rental_revenue + recoveries + other_income

    opex = {}
    for line in OPEX_LINES:
        opex[line] = deal["opex"].get(line) or 0.0

    # Management: explicit amount wins, else a percentage of EGI.
    if not opex["management"]:
        opex["management"] = egi * (deal["management_pct_egi"] or 0.0) / 100.0
        _flag(provenance, "management", "assumption",
              f"{deal['management_pct_egi']:.1f}% of EGI")

    # Taxes follow price. If the seller's bill is higher, use the seller's.
    if price:
        buyer_tax = price * (deal["tax_rate_pct"] or 0.0) / 100.0
        if buyer_tax > opex["taxes"]:
            if opex["taxes"]:
                warnings.append(
                    f"Taxes reassessed at the purchase price: ${opex['taxes']:,.0f} seller bill -> "
                    f"${buyer_tax:,.0f} at {deal['tax_rate_pct']:.2f}%. NOI follows the buyer's bill."
                )
            opex["taxes"] = buyer_tax
            _flag(provenance, "taxes", "assumption", f"{deal['tax_rate_pct']:.2f}% of price")
        else:
            _flag(provenance, "taxes", "t12", "seller's bill, price check applied")

    total_opex = sum(opex.values())
    noi = egi - total_opex
    reserves = _reserves(deal, egi)
    expense_ratio = (total_opex / egi * 100.0) if egi else None

    if not any(deal["opex"].get(k) for k in OPEX_LINES if k != "management"):
        warnings.append("No expense detail supplied: NOI is a rent-roll figure, not an operating "
                        "figure. Get a T-12 or the seller's operating statement before relying on it.")
    if deal["property_type"] in ("office", "retail", "industrial") and not recoveries:
        warnings.append("No recoveries supplied for a NNN-type asset: NOI may be understated, or the "
                        "lease is gross. Confirm the lease form.")
    if reserves == 0:
        warnings.append("Reserves are 0. Nothing in this model funds a roof.")
    if noi <= 0:
        warnings.append("Rebuilt NOI is zero or negative at this price.")

    claim = deal["t12_noi_claim"]
    if claim and noi:
        gap = noi - claim
        if abs(gap) > max(1000.0, abs(claim) * 0.05):
            warnings.append(
                f"Rebuilt NOI ${noi:,.0f} vs seller's claim ${claim:,.0f} "
                f"({gap:+,.0f}). The gap is the negotiation."
            )

    return {
        "ok": True,
        "price": price,
        "gross_potential_rent": gpr,
        "vacancy_loss": -vacancy_loss,
        "credit_loss": -credit_loss,
        "rental_revenue": rental_revenue,
        "recoveries": recoveries,
        "other_income": other_income,
        "egi": egi,
        "occupancy_pct": deal["occupancy_pct"],
        "credit_loss_pct": deal["credit_loss_pct"],
        "opex": opex,
        "total_opex": total_opex,
        "noi": noi,
        "reserves": reserves,
        "noi_after_reserves": noi - reserves,
        "expense_ratio_pct": expense_ratio,
        "warnings": warnings,
        "provenance": provenance,
        "incomplete": [],
    }


def amort_payment(principal: float, rate_pct: float, years: int, io: bool = False) -> float:
    """Annual debt service. Monthly amortization, annualized — the bank's number, not a guess."""
    if principal <= 0:
        return 0.0
    if io or not years:
        return principal * (rate_pct or 0.0) / 100.0
    r = (rate_pct or 0.0) / 100.0 / 12.0
    n = int(years) * 12
    if r == 0:
        return principal / years
    return principal * r / (1.0 - (1.0 + r) ** -n) * 12.0


def loan_balance(principal: float, rate_pct: float, years: int, months_elapsed: int, io_years: float = 0) -> float:
    if principal <= 0:
        return 0.0
    r = (rate_pct or 0.0) / 100.0 / 12.0
    if r == 0 or not years:
        return principal
    n = int(years) * 12
    pay = principal * r / (1.0 - (1.0 + r) ** -n)
    io_months = int(min(io_years or 0, years) * 12)
    k = max(0, months_elapsed)
    if k <= io_months:
        return principal
    k -= io_months
    return principal * ((1.0 + r) ** k) - pay * (((1.0 + r) ** k - 1.0) / r)


def irr(cashflows: list) -> float | None:
    """Bisection IRR. Returns None when the sign pattern has no reasonable root."""
    if not cashflows or min(cashflows) >= 0 or max(cashflows) <= 0:
        return None

    def npv(rate):
        return sum(cf / (1.0 + rate) ** i for i, cf in enumerate(cashflows))

    lo, hi = -0.90, 10.0
    f_lo, f_hi = npv(lo), npv(hi)
    if f_lo * f_hi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2.0
        f_mid = npv(mid)
        if abs(f_mid) < 1e-7 or (hi - lo) < 1e-9:
            return mid
        if f_lo * f_mid <= 0:
            hi, f_hi = mid, f_mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2.0


def npv(rate_pct: float, cashflows: list) -> float:
    r = rate_pct / 100.0
    return sum(cf / (1.0 + r) ** i for i, cf in enumerate(cashflows))


def debt_scenarios(deal: dict, noi: float, price: float) -> list:
    scen = deal["debt"] or []
    if not scen:
        try:
            from .assumptions import DEFAULT_DEBT
        except ImportError:
            from assumptions import DEFAULT_DEBT
        scen = DEFAULT_DEBT
    out = []
    equity_total = price * (1.0 - 0.0) + price * deal["closing_cost_pct"] / 100.0
    for s in scen:
        ltv = num(s.get("ltv_pct"), 0.0) or 0.0
        rate = num(s.get("rate_pct"), 0.0) or 0.0
        amort = int(num(s.get("amort_years"), 0) or 0)
        io_years = num(s.get("io_years"), 0) or 0
        loan = price * ltv / 100.0
        ds = amort_payment(loan, rate, amort, io=bool(io_years) and not amort)
        equity = price - loan + price * deal["closing_cost_pct"] / 100.0
        dscr = (noi / ds) if ds else None
        loan_constant = (ds / loan * 100.0) if loan else None
        cap = (noi / price * 100.0) if price else None
        out.append({
            "name": s.get("name") or f"{ltv:.0f}% LTV",
            "ltv_pct": ltv,
            "rate_pct": rate,
            "amort_years": amort,
            "io_years": io_years,
            "loan": loan,
            "equity": equity,
            "debt_service": ds,
            "dscr": dscr,
            "debt_yield_pct": (noi / loan * 100.0) if loan else None,
            "loan_constant_pct": loan_constant,
            "cash_on_cash_pct": ((noi - (deal["_reserves_cache"] if "_reserves_cache" in deal else 0.0) - ds) / equity * 100.0) if equity else None,
            "negative_leverage": bool(cap and loan_constant and loan_constant > cap),
            "all_cash": ltv == 0,
        })
    return out


def _buy_box(deal: dict, overrides: dict | None) -> dict:
    td = deal["type_defaults"]
    box = {
        "min_cap_pct": td["min_cap_pct"],
        "max_expense_ratio_pct": td["max_expense_ratio_pct"],
        "min_occupancy_pct": td["min_occupancy_pct"],
        "min_dscr": 1.25,
        "max_price_per_unit": None,
        "max_price_per_sf": None,
    }
    for k, v in (overrides or {}).items():
        if v is not None:
            box[k] = v
    return box


def max_price(deal: dict, box: dict) -> dict:
    """Highest price at which the price-dependent tests still pass.

    Two constraints bind: the minimum cap rate, and the DSCR floor on the primary loan.
    Returns both plus the binding one — that is the counter-offer.
    """
    noi = deal.get("_noi")
    if not noi or noi <= 0:
        return {"price": None, "reason": "no positive NOI to capitalize"}
    caps = []
    if box.get("min_cap_pct"):
        caps.append({"constraint": f"cap >= {box['min_cap_pct']:.2f}%",
                     "price": noi / (box["min_cap_pct"] / 100.0)})
    primary = next((s for s in debt_scenarios(deal, noi, deal["price"]) if not s["all_cash"]), None)
    if primary and box.get("min_dscr"):
        ds_max = noi / box["min_dscr"]
        if primary["amort_years"]:
            r = primary["rate_pct"] / 100.0 / 12.0
            n = primary["amort_years"] * 12
            loan_max = ds_max / 12.0 * (1.0 - (1.0 + r) ** -n) / r if r else ds_max * primary["amort_years"]
        else:
            loan_max = ds_max / (primary["rate_pct"] / 100.0) if primary["rate_pct"] else 0.0
        if primary["ltv_pct"]:
            caps.append({"constraint": f"DSCR >= {box['min_dscr']:.2f} ({primary['name']})",
                         "price": loan_max / (primary["ltv_pct"] / 100.0)})
    if not caps:
        return {"price": None, "reason": "no price-dependent test configured"}
    binding = min(caps, key=lambda c: c["price"])
    return {
        "price": binding["price"],
        "binding_constraint": binding["constraint"],
        "detail": caps,
        "vs_ask_pct": ((binding["price"] / deal["price"] - 1.0) * 100.0) if deal["price"] else None,
    }


def screen(deal: dict, buy_box: dict | None = None) -> dict:
    """Full screen: rebuilt NOI, price metrics, debt, verdict, and the counter price."""
    deal = normalize(deal)
    box = _buy_box(deal, buy_box)
    price = deal["price"]

    if price is None:
        return {
            "deal": deal["name"], "verdict": "INCOMPLETE",
            "missing": ["price"],
            "reason": "No asking price: cap rate, DSCR and price-per-unit are all price-dependent.",
            "warnings": [], "box": box,
        }

    noi_block = build_noi(deal, price)
    if not noi_block["ok"]:
        return {
            "deal": deal["name"], "verdict": "INCOMPLETE",
            "missing": noi_block["incomplete"],
            "reason": noi_block["warnings"][0],
            "warnings": noi_block["warnings"], "box": box,
            "price": price,
        }

    noi = noi_block["noi"]
    deal["_noi"] = noi
    deal["_reserves_cache"] = noi_block["reserves"]
    cap = noi / price * 100.0
    scenarios = debt_scenarios(deal, noi, price)

    # The screen judges the primary amortizing loan; IO structures get tested again below.
    primary = next((s for s in scenarios if not s["all_cash"] and s["amort_years"]), None) or \
              next((s for s in scenarios if not s["all_cash"]), None)

    tests = []

    def add_test(name, passed, actual, threshold, hard=True):
        tests.append({"test": name, "pass": bool(passed), "actual": actual,
                      "threshold": threshold, "hard": hard})

    if box.get("min_cap_pct"):
        add_test(f"cap rate >= {box['min_cap_pct']:.2f}%", cap >= box["min_cap_pct"],
                 round(cap, 3), box["min_cap_pct"])
    if box.get("max_expense_ratio_pct") and noi_block["expense_ratio_pct"] is not None:
        add_test(f"expense ratio <= {box['max_expense_ratio_pct']:.0f}%",
                 noi_block["expense_ratio_pct"] <= box["max_expense_ratio_pct"],
                 round(noi_block["expense_ratio_pct"], 2), box["max_expense_ratio_pct"])
    if box.get("min_occupancy_pct"):
        add_test(f"occupancy >= {box['min_occupancy_pct']:.0f}%",
                 deal["occupancy_pct"] >= box["min_occupancy_pct"],
                 round(deal["occupancy_pct"], 2), box["min_occupancy_pct"])
    if primary and primary["dscr"] is not None:
        add_test(f"DSCR >= {box['min_dscr']:.2f} ({primary['name']})",
                 primary["dscr"] >= box["min_dscr"], round(primary["dscr"], 3), box["min_dscr"])
    if deal["units"] and box.get("max_price_per_unit"):
        add_test(f"price/unit <= ${box['max_price_per_unit']:,.0f}",
                 price / deal["units"] <= box["max_price_per_unit"],
                 round(price / deal["units"], 0), box["max_price_per_unit"])
    if deal["nra_sf"] and box.get("max_price_per_sf"):
        add_test(f"price/SF <= ${box['max_price_per_sf']:,.2f}",
                 price / deal["nra_sf"] <= box["max_price_per_sf"],
                 round(price / deal["nra_sf"], 2), box["max_price_per_sf"])

    hard_fails = [t for t in tests if not t["pass"] and t["hard"]]
    verdict = "PASS" if not hard_fails else "REJECT"

    warnings = list(noi_block["warnings"])
    if primary and primary["negative_leverage"]:
        warnings.append(
            f"Negative leverage: loan constant {primary['loan_constant_pct']:.2f}% exceeds the "
            f"{cap:.2f}% cap rate. Every dollar of debt reduces cash-on-cash."
        )
    if primary and primary["dscr"] and 1.25 <= primary["dscr"] < 1.35:
        warnings.append(f"DSCR {primary['dscr']:.2f} clears the floor but leaves no room for a "
                        "vacancy bump. Thin.")

    m = max_price(deal, box) if verdict != "PASS" else None

    out = {
        "deal": deal["name"],
        "property_type": deal["property_type"],
        "market": deal["market"],
        "verdict": verdict,
        "price": price,
        "noi": noi,
        "noi_claim": deal["t12_noi_claim"],
        "cap_rate_pct": round(cap, 3),
        "expense_ratio_pct": round(noi_block["expense_ratio_pct"], 2) if noi_block["expense_ratio_pct"] else None,
        "gross_potential_rent": noi_block["gross_potential_rent"],
        "egi": noi_block["egi"],
        "total_opex": noi_block["total_opex"],
        "reserves": noi_block["reserves"],
        "breakeven_occupancy_pct": _breakeven(noi_block, primary),
        "price_per_unit": round(price / deal["units"], 0) if deal["units"] else None,
        "price_per_sf": round(price / deal["nra_sf"], 2) if deal["nra_sf"] else None,
        "noi_bridge": {k: noi_block[k] for k in ("gross_potential_rent", "vacancy_loss", "credit_loss",
                                                 "rental_revenue", "recoveries", "other_income", "egi",
                                                 "opex", "total_opex", "noi")},
        "debt": scenarios,
        "tests": tests,
        "warnings": warnings,
        "box": box,
        "assumptions": noi_block["provenance"],
        "counter_price": m,
        "reasons": [f"{t['test']} — actual {t['actual']}, needed {t['threshold']}" for t in hard_fails],
    }
    return out


def _breakeven(noi_block: dict, primary: dict | None) -> float | None:
    """Occupancy at which collections cover opex, reserves and debt service. The real risk number:
    it is the vacancy you can absorb before you start feeding the deal."""
    gpr = noi_block["gross_potential_rent"]
    if not gpr or gpr <= 0:
        return None
    income_at_full = gpr * (1.0 - (noi_block.get("credit_loss_pct") or 0.0) / 100.0) + \
        (noi_block.get("recoveries") or 0.0)
    need = noi_block["total_opex"] + (noi_block.get("reserves") or 0.0) + \
        ((primary or {}).get("debt_service") or 0.0) - (noi_block.get("other_income") or 0.0)
    if income_at_full <= 0:
        return None
    return max(0.0, need / income_at_full * 100.0)


def triage(deal: dict, lo: float | None = None, hi: float | None = None, steps: int = 25,
           buy_box: dict | None = None) -> dict:
    """Sweep price and report where the deal flips. Taxes are re-run at every price."""
    deal = normalize(deal)
    if not deal["price"]:
        raise ValueError("triage needs an asking price to anchor the range")
    lo = num(lo, deal["price"] * 0.75)
    hi = num(hi, deal["price"] * 1.15)
    steps = max(2, min(int(steps or 25), 200))
    box = _buy_box(deal, buy_box)
    rows, passing = [], []
    for i in range(steps):
        p = lo + (hi - lo) * i / (steps - 1)
        d = dict(deal, price=p)
        r = screen(d, buy_box)
        if r.get("verdict") not in ("PASS", "REJECT"):
            continue
        row = {"price": round(p, -2), "verdict": r["verdict"], "cap_rate_pct": r["cap_rate_pct"],
               "noi": round(r["noi"], -1)}
        primary = next((s for s in r["debt"] if not s["all_cash"] and s["amort_years"]), None)
        row["dscr"] = round(primary["dscr"], 2) if primary and primary["dscr"] else None
        rows.append(row)
        if r["verdict"] == "PASS":
            passing.append(row)
    sweet = max(passing, key=lambda r: r["price"]) if passing else None
    return {
        "deal": deal["name"],
        "range": [round(lo, -2), round(hi, -2)],
        "steps": rows,
        "sweet_spot": sweet,
        "note": "Highest price that still clears every test. Above it, the deal stops working; "
                "below it you are leaving money on the table. Taxes re-run at each price.",
    }
