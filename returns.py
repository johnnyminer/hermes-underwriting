"""Hold-period returns: levered/unlevered IRR, equity multiple, and the exit sensitivity grid.

The screen answers "is this a deal at this price". This module answers "what happens if I hold it",
which is the question every broker's proforma is built to make look easy.

Same discipline as engine.py: in-place numbers first, growth explicit, exit cap explicit, and no
soft "IRR" that quietly assumes the broker's rent growth.
"""

from __future__ import annotations

try:
    from .engine import amort_payment, build_noi, debt_scenarios, irr, loan_balance, normalize, num, npv
except ImportError:
    from engine import amort_payment, build_noi, debt_scenarios, irr, loan_balance, normalize, num, npv



def _reserves(deal: dict) -> float:
    return deal.get("_reserves_cache") or 0.0


def proforma(deal: dict, price=None, scenario_name: str | None = None,
             growth: dict | None = None) -> dict:
    """Annual proforma through the hold, for the named (or primary) debt scenario."""
    deal = normalize(deal)
    g = {**deal["growth"], **{k: v for k, v in (growth or {}).items() if v is not None}}
    price = num(price, deal["price"])
    if not price:
        raise ValueError("proforma needs a price")

    noi_block = build_noi(deal, price)
    if not noi_block["ok"]:
        raise ValueError(noi_block["warnings"][0])
    noi0 = noi_block["noi"]
    reserves0 = noi_block["reserves"]
    egi0 = noi_block["egi"]
    opex0 = noi_block["total_opex"]

    hold = int(num(g.get("hold_years"), 5) or 5)
    rent_g = num(g.get("rent_pct"), 3.0) or 0.0
    exp_g = num(g.get("expense_pct"), 3.0) or 0.0
    go_cap = noi0 / price * 100.0
    exit_cap = num(g.get("exit_cap_pct"), go_cap) or go_cap
    sale_cost_pct = num(g.get("sale_cost_pct"), 2.0) or 0.0
    disc = num(g.get("discount_rate_pct"), 9.0) or 0.0

    # Debt: the named scenario, else the first amortizing one.
    scen = [s for s in debt_scenarios(deal, noi0, price) if not s["all_cash"]]
    primary = next((s for s in scen if s["name"] == scenario_name), None) or \
              next((s for s in scen if s["amort_years"]), None) or (scen[0] if scen else None)

    closing = price * deal["closing_cost_pct"] / 100.0
    loan = primary["loan"] if primary else 0.0
    equity = price - loan + closing
    ds = primary["debt_service"] if primary else 0.0

    years = []
    for t in range(1, hold + 1):
        egi_t = egi0 * (1.0 + rent_g / 100.0) ** (t - 1)
        opex_t = opex0 * (1.0 + exp_g / 100.0) ** (t - 1)
        noi_t = egi_t - opex_t
        res_t = reserves0 * (1.0 + exp_g / 100.0) ** (t - 1)
        cf_unlev = noi_t - res_t
        cf_lev = cf_unlev - ds
        dscr = (noi_t / ds) if ds else None
        years.append({
            "year": t, "egi": egi_t, "opex": opex_t, "noi": noi_t, "reserves": res_t,
            "cf_unlevered": cf_unlev, "debt_service": ds, "cf_levered": cf_lev,
            "dscr": dscr, "cash_on_cash_pct": (cf_lev / equity * 100.0) if equity else None,
        })

    # Exit on forward NOI — the one convention buyers and sellers argue about forever.
    noi_next = (egi0 * (1.0 + rent_g / 100.0) ** hold) - (opex0 * (1.0 + exp_g / 100.0) ** hold)
    exit_value = noi_next / (exit_cap / 100.0) if exit_cap else 0.0
    sale_net = exit_value * (1.0 - sale_cost_pct / 100.0)
    balance = loan_balance(loan, primary["rate_pct"], primary["amort_years"] if primary else 0,
                          hold * 12, primary["io_years"] if primary else 0) if loan else 0.0

    unlev_cf = [-price - closing] + [y["cf_unlevered"] for y in years]
    unlev_cf[-1] += sale_net
    lev_cf = [-equity] + [y["cf_levered"] for y in years]
    lev_cf[-1] += sale_net - balance

    cash_back = sum(lev_cf[1:])
    return {
        "deal": deal["name"],
        "price": price,
        "going_in_cap_pct": round(go_cap, 3),
        "exit_cap_pct": round(exit_cap, 3),
        "hold_years": hold,
        "rent_growth_pct": rent_g,
        "expense_growth_pct": exp_g,
        "debt": primary["name"] if primary else "all cash",
        "loan": loan,
        "equity": equity,
        "years": years,
        "exit_value": exit_value,
        "sale_proceeds_net": sale_net,
        "loan_balance_at_exit": balance,
        "cashflows_unlevered": unlev_cf,
        "cashflows_levered": lev_cf,
        "unlevered_irr_pct": _pct(irr(unlev_cf)),
        "levered_irr_pct": _pct(irr(lev_cf)),
        "equity_multiple": (cash_back / equity) if equity else None,
        "npv_at_discount": npv(disc, lev_cf),
        "discount_rate_pct": disc,
        "min_dscr": min((y["dscr"] for y in years if y["dscr"]), default=None),
        "avg_cash_on_cash_pct": (sum(y["cash_on_cash_pct"] or 0 for y in years) / len(years)) if years else None,
        "warnings": [
            w for w in (
                "Levered returns assume the loan amortizes on schedule and the exit happens on the "
                "forward NOI at the exit cap." if loan else None,
                f"Exit cap {exit_cap:.2f}% is below the going-in {go_cap:.2f}%: that is cap "
                "compression, an assumption the seller benefits from." if exit_cap < go_cap - 0.001 else None,
                f"Exit cap {exit_cap:.2f}% above going-in {go_cap:.2f}%: conservative." if exit_cap > go_cap + 0.001 else None,
            ) if w
        ],
    }


def _pct(value):
    return round(value * 100.0, 2) if value is not None else None


def sensitivity(deal: dict, price=None, exit_cap_deltas=(-75, -50, -25, 0, 25, 50, 75),
                rent_growth_deltas=(-200, -100, 0, 100, 200), base_growth: dict | None = None) -> dict:
    """Levered IRR across exit cap and rent growth. A flat grid means the deal is insensitive;
    a steep one means the exit assumption is the deal."""
    deal = normalize(deal)
    g = {**deal["growth"], **{k: v for k, v in (base_growth or {}).items() if v is not None}}
    base_cap = num(g.get("exit_cap_pct")) or ((deal["price"] and build_noi(deal, deal["price"])["noi"] / deal["price"] * 100.0) or 6.0)
    base_growth_pct = num(g.get("rent_pct"), 3.0) or 0.0

    grid = []
    for dcap in exit_cap_deltas:
        row = []
        for dg in rent_growth_deltas:
            try:
                r = proforma(deal, price, growth={**g, "exit_cap_pct": base_cap + dcap / 100.0,
                                                  "rent_pct": base_growth_pct + dg / 100.0})
                row.append(r["levered_irr_pct"])
            except ValueError:
                row.append(None)
        grid.append({"exit_cap_bps": dcap, "irr_pct": row})

    values = [v for row in grid for v in row["irr_pct"] if v is not None]
    return {
        "deal": deal["name"],
        "base_exit_cap_pct": round(base_cap, 3),
        "base_rent_growth_pct": base_growth_pct,
        "exit_cap_axis_bps": list(exit_cap_deltas),
        "rent_growth_axis_bps": list(rent_growth_deltas),
        "grid": grid,
        "min_irr_pct": min(values) if values else None,
        "max_irr_pct": max(values) if values else None,
        "spread_pct": (max(values) - min(values)) if values else None,
    }
