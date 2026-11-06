"""Investment memo from a screen result.

Deterministic template on purpose: a memo that restates the model cannot drift from the model.
If a number is in here, it is a number the screen computed, and every warning the screen raised
is in the memo with the same wording.
"""

from __future__ import annotations


def _money(v, dash="—"):
    if v is None:
        return dash
    return f"${v:,.0f}"


def _pct(v, places=2, dash="—"):
    if v is None:
        return dash
    return f"{v:.{places}f}%"


def build_memo(screen: dict, deal_inputs: dict | None = None) -> str:
    s = screen or {}
    name = s.get("deal") or "Untitled deal"
    lines = [f"# Underwriting memo — {name}", ""]

    verdict = s.get("verdict", "INCOMPLETE")
    verdict_line = {
        "PASS": "**PASS** — clears the buy box at the asking price.",
        "REJECT": "**REJECT** — does not clear the buy box at the asking price.",
        "INCOMPLETE": "**INCOMPLETE** — not enough data to reach a verdict.",
    }.get(verdict, f"**{verdict}**")
    lines += [verdict_line, ""]

    if s.get("market") or s.get("property_type"):
        lines += [f"{s.get('property_type', '').replace('_', ' ').title()} · {s.get('market', '')}".strip(" ·"), ""]

    if verdict == "INCOMPLETE":
        lines += ["## What is missing", ""]
        for m in s.get("missing") or []:
            lines.append(f"- `{m}`")
        if s.get("reason"):
            lines += ["", s["reason"]]
        lines += ["", "No valuation is offered because every valuation metric is price- or "
                      "income-dependent, and inventing either would be the one thing this tool "
                      "will not do.", ""]
        return "\n".join(lines)

    lines += ["## At a glance", ""]
    rows = [
        ("Asking price", _money(s.get("price"))),
        ("Rebuilt NOI", _money(s.get("noi"))),
        ("Seller's NOI claim", _money(s.get("noi_claim"))),
        ("Cap rate", _pct(s.get("cap_rate_pct"))),
        ("Expense ratio", _pct(s.get("expense_ratio_pct"))),
        ("Price / unit", _money(s.get("price_per_unit"))),
        ("Price / SF", f"${s['price_per_sf']:,.2f}" if s.get("price_per_sf") else "—"),
        ("Breakeven occupancy", _pct(s.get("breakeven_occupancy_pct"), 1)),
    ]
    lines += ["| Metric | Value |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in rows]
    lines += [""]

    bridge = s.get("noi_bridge") or {}
    if bridge:
        lines += ["## NOI bridge", "", "| Line | Amount |", "|---|---|"]
        lines.append(f"| Gross potential rent | {_money(bridge.get('gross_potential_rent'))} |")
        lines.append(f"| Vacancy loss | {_money(bridge.get('vacancy_loss'))} |")
        lines.append(f"| Credit loss | {_money(bridge.get('credit_loss'))} |")
        lines.append(f"| Recoveries | {_money(bridge.get('recoveries'))} |")
        lines.append(f"| Other income | {_money(bridge.get('other_income'))} |")
        lines.append(f"| **Effective gross income** | **{_money(bridge.get('egi'))}** |")
        for line, value in (bridge.get("opex") or {}).items():
            if value:
                lines.append(f"| {line.replace('_', ' ').title()} | {_money(-value)} |")
        lines.append(f"| **Total operating expenses** | **{_money(-(bridge.get('total_opex') or 0))}** |")
        lines.append(f"| **Net operating income** | **{_money(bridge.get('noi'))}** |")
        lines += [""]

    debt = s.get("debt") or []
    if debt:
        lines += ["## Debt capacity", "",
                  "| Structure | LTV | Loan | Debt service | DSCR | Debt yield | Cash-on-cash |",
                  "|---|---|---|---|---|---|---|"]
        for d in debt:
            dscr = f"{d['dscr']:.2f}" if d.get("dscr") else "n/a"
            lines.append(
                f"| {d['name']} | {_pct(d.get('ltv_pct'), 0)} | {_money(d.get('loan'))} | "
                f"{_money(d.get('debt_service'))} | {dscr} | "
                f"{_pct(d.get('debt_yield_pct'))} | {_pct(d.get('cash_on_cash_pct'))} |"
            )
        lines += [""]

    tests = s.get("tests") or []
    if tests:
        lines += ["## Buy-box tests", "", "| Test | Result | Actual | Threshold |", "|---|---|---|---|"]
        for t in tests:
            lines.append(f"| {t['test']} | {'PASS' if t['pass'] else 'FAIL'} | {t['actual']} | {t['threshold']} |")
        lines += [""]

    cp = s.get("counter_price") or {}
    if cp.get("price"):
        lines += ["## The counter", "",
                  f"At **{_money(cp['price'])}** the deal clears the box — bound by "
                  f"{cp.get('binding_constraint', 'the cap rate')}. "
                  + (f"That is {cp['vs_ask_pct']:+.1f}% against the ask." if cp.get("vs_ask_pct") is not None else ""),
                  ""]

    if s.get("warnings"):
        lines += ["## Warnings", ""]
        lines += [f"- {w}" for w in s["warnings"]]
        lines += [""]

    if s.get("assumptions"):
        lines += ["## Assumptions (not from the document)", ""]
        for field, prov in s["assumptions"].items():
            lines.append(f"- **{field}**: {prov.get('source')} — {prov.get('quote') or 'default'}")
        lines += [""]

    lines += ["---",
              "Generated by the Hermes `underwriting` plugin. Every figure above is arithmetic on "
              "the inputs you supplied; no figure is estimated by a language model. Verify the "
              "inputs before you sign anything.", ""]
    return "\n".join(lines)
