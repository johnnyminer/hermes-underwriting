"""Property-type defaults and buy-box assumptions.

Every number here is a *default*, not a market constant, and the UI/README says so.
Overriding them is expected; silently inheriting them is what kills deals.
"""

from __future__ import annotations

# Defaults keyed by property type. Values are deliberately conservative: a deal
# should have to argue its way in, not out.
TYPE_DEFAULTS = {
    "multifamily": {
        "vacancy_pct": 5.0,
        "credit_loss_pct": 1.0,
        "management_pct_egi": 3.0,
        "reserves_per_unit": 300.0,
        "min_cap_pct": 6.0,
        "max_expense_ratio_pct": 45.0,
        "min_occupancy_pct": 85.0,
        "recoverable_opex": "none",
    },
    "office": {
        "vacancy_pct": 10.0,
        "credit_loss_pct": 2.0,
        "management_pct_egi": 3.0,
        "reserves_per_sf": 0.20,
        "min_cap_pct": 7.5,
        "max_expense_ratio_pct": 50.0,
        "min_occupancy_pct": 80.0,
        "recoverable_opex": "nnn",
    },
    "retail": {
        "vacancy_pct": 6.0,
        "credit_loss_pct": 1.5,
        "management_pct_egi": 3.0,
        "reserves_per_sf": 0.15,
        "min_cap_pct": 7.0,
        "max_expense_ratio_pct": 45.0,
        "min_occupancy_pct": 85.0,
        "recoverable_opex": "nnn",
    },
    "industrial": {
        "vacancy_pct": 5.0,
        "credit_loss_pct": 0.5,
        "management_pct_egi": 3.0,
        "reserves_per_sf": 0.10,
        "min_cap_pct": 6.5,
        "max_expense_ratio_pct": 40.0,
        "min_occupancy_pct": 85.0,
        "recoverable_opex": "nnn",
    },
    "self_storage": {
        "vacancy_pct": 10.0,
        "credit_loss_pct": 1.5,
        "management_pct_egi": 5.0,
        "reserves_pct_egi": 2.0,
        "min_cap_pct": 8.0,
        "max_expense_ratio_pct": 45.0,
        "min_occupancy_pct": 80.0,
        "recoverable_opex": "none",
    },
    "mixed": {
        "vacancy_pct": 7.0,
        "credit_loss_pct": 1.5,
        "management_pct_egi": 3.5,
        "reserves_pct_egi": 1.5,
        "min_cap_pct": 7.0,
        "max_expense_ratio_pct": 48.0,
        "min_occupancy_pct": 82.0,
        "recoverable_opex": "partial",
    },
    "other": {
        "vacancy_pct": 7.0,
        "credit_loss_pct": 1.5,
        "management_pct_egi": 3.5,
        "reserves_pct_egi": 1.5,
        "min_cap_pct": 7.5,
        "max_expense_ratio_pct": 50.0,
        "min_occupancy_pct": 80.0,
        "recoverable_opex": "partial",
    },
}

# Debt scenarios offered when the caller does not name one. LTV-based, so the
# equity requirement is visible rather than assumed.
DEFAULT_DEBT = [
    {"name": "Bank (65% LTV)", "ltv_pct": 65.0, "rate_pct": 6.75, "amort_years": 25, "io_years": 0},
    {"name": "Agency (60% LTV)", "ltv_pct": 60.0, "rate_pct": 6.25, "amort_years": 30, "io_years": 0},
    {"name": "Bridge (70% LTV, IO)", "ltv_pct": 70.0, "rate_pct": 8.50, "amort_years": 0, "io_years": 3},
    {"name": "All cash", "ltv_pct": 0.0, "rate_pct": 0.0, "amort_years": 0, "io_years": 0},
]

DEFAULT_GROWTH = {
    "rent_pct": 3.0,
    "expense_pct": 3.0,
    "exit_cap_pct": None,  # None -> exit at the going-in cap (no expansion assumed)
    "hold_years": 5,
    "sale_cost_pct": 2.0,
    "discount_rate_pct": 9.0,
}

DEFAULT_CLOSING_COST_PCT = 2.5
# Ohio convention: the auditor picks up a recent sale at the next reappraisal, so
# the buyer's tax bill follows the price, not the seller's bill.
DEFAULT_TAX_RATE_PCT = 1.2
DEFAULT_CREDIT_LOSS_PCT = 1.5

PROPERTY_TYPES = tuple(TYPE_DEFAULTS)


def type_defaults(property_type: str) -> dict:
    key = (property_type or "other").strip().lower().replace("-", "_").replace(" ", "_")
    if key not in TYPE_DEFAULTS:
        key = "other"
    return dict(TYPE_DEFAULTS[key])
