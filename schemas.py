"""Tool schemas. Kept as plain dicts so the plugin has no framework dependency."""

DEAL_SCHEMA = {
    "type": "object",
    "description": "A deal as known so far. Only include numbers you actually have: an omitted "
                   "income or expense line is treated as 0 with a warning, never filled with a "
                   "guess. That is deliberate.",
    "properties": {
        "name": {"type": "string", "description": "Property name or street address"},
        "market": {"type": "string", "description": "City/state or submarket"},
        "property_type": {"type": "string",
                          "enum": ["multifamily", "office", "retail", "industrial",
                                   "self_storage", "mixed", "other"]},
        "price": {"type": "number", "description": "Asking price in dollars"},
        "units": {"type": "number", "description": "Units, doors or storage units; null for SF-only assets"},
        "nra_sf": {"type": "number", "description": "Rentable square feet"},
        "year_built": {"type": "number"},
        "tax_rate_pct": {"type": "number",
                         "description": "Effective property tax rate as a percent of price, used to "
                                        "reassess the buyer's bill. Defaults to 1.2."},
        "income": {
            "type": "object",
            "properties": {
                "gross_potential_rent": {"type": "number", "description": "Annual GPI at 100% occupancy"},
                "avg_rent_monthly": {"type": "number"},
                "occupancy_pct": {"type": "number"},
                "vacancy_pct": {"type": "number"},
                "credit_loss_pct": {"type": "number"},
                "recoveries": {"type": "number", "description": "Annual NNN/CAM recoveries"},
                "other_income": {"type": "number"},
                "t12_egi": {"type": "number"},
                "t12_noi": {"type": "number", "description": "Seller's claimed NOI — carried as a claim, not a fact"},
                "t12_opex": {"type": "number"},
            },
        },
        "opex": {
            "type": "object",
            "properties": {
                "taxes": {"type": "number"}, "insurance": {"type": "number"},
                "utilities": {"type": "number"}, "repairs_maintenance": {"type": "number"},
                "payroll": {"type": "number"}, "general_admin": {"type": "number"},
                "management": {"type": "number", "description": "Dollar amount; omit to use management_pct_egi"},
                "management_pct_egi": {"type": "number"},
                "other_opex": {"type": "number"},
                "reserves": {"type": "number", "description": "Below-the-line annual reserves"},
            },
        },
        "debt": {
            "type": "array",
            "description": "Financing scenarios to test. Omit for the four standard structures.",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "ltv_pct": {"type": "number"},
                    "rate_pct": {"type": "number"},
                    "amort_years": {"type": "number"},
                    "io_years": {"type": "number"},
                },
            },
        },
        "growth": {
            "type": "object",
            "properties": {
                "rent_pct": {"type": "number"}, "expense_pct": {"type": "number"},
                "exit_cap_pct": {"type": "number"}, "hold_years": {"type": "number"},
                "sale_cost_pct": {"type": "number"}, "discount_rate_pct": {"type": "number"},
            },
        },
        "closing_cost_pct": {"type": "number"},
        "notes": {"type": "string"},
    },
}

BUY_BOX_SCHEMA = {
    "type": "object",
    "description": "Screening thresholds. Defaults come from the property type; override to match "
                   "your own mandate.",
    "properties": {
        "min_cap_pct": {"type": "number"},
        "max_expense_ratio_pct": {"type": "number"},
        "min_occupancy_pct": {"type": "number"},
        "min_dscr": {"type": "number"},
        "max_price_per_unit": {"type": "number"},
        "max_price_per_sf": {"type": "number"},
    },
}

SCREEN = {
    "name": "uw_screen",
    "description": "Underwrite a commercial property: rebuild NOI from income and expense lines, "
                   "compute cap rate, price/unit and price/SF, size debt against DSCR and debt "
                   "yield, run the buy-box tests, and return a verdict plus the counter-price at "
                   "which the deal would clear. Missing data returns INCOMPLETE with the missing "
                   "fields named — never a guess.",
    "parameters": {
        "type": "object",
        "properties": {"deal": DEAL_SCHEMA, "buy_box": BUY_BOX_SCHEMA},
        "required": ["deal"],
    },
}

TRIAGE = {
    "name": "uw_triage",
    "description": "Sweep a range of prices and report where the deal flips: cap rate and DSCR at "
                   "each price, the highest price that still passes every test, and the price where "
                   "it stops working. Property taxes are re-run at every price, because a buyer's "
                   "bill follows the price.",
    "parameters": {
        "type": "object",
        "properties": {
            "deal": DEAL_SCHEMA,
            "lo": {"type": "number", "description": "Low end of the sweep; defaults to 75% of ask"},
            "hi": {"type": "number", "description": "High end; defaults to 115% of ask"},
            "steps": {"type": "number", "description": "Number of prices to test (default 25, max 200)"},
            "buy_box": BUY_BOX_SCHEMA,
        },
        "required": ["deal"],
    },
}

RETURNS = {
    "name": "uw_returns",
    "description": "Hold-period returns: annual proforma through the hold, levered and unlevered "
                   "IRR, equity multiple, NPV, cash-on-cash by year, DSCR by year, exit on forward "
                   "NOI, and an optional exit-cap x rent-growth sensitivity grid.",
    "parameters": {
        "type": "object",
        "properties": {
            "deal": DEAL_SCHEMA,
            "price": {"type": "number"},
            "scenario": {"type": "string", "description": "Debt scenario name; defaults to the first amortizing one"},
            "hold_years": {"type": "number"},
            "rent_growth_pct": {"type": "number"},
            "expense_growth_pct": {"type": "number"},
            "exit_cap_pct": {"type": "number", "description": "Defaults to the going-in cap"},
            "sensitivity": {"type": "boolean", "description": "Include the exit-cap x rent-growth IRR grid"},
        },
        "required": ["deal"],
    },
}

EXTRACT = {
    "name": "uw_extract",
    "description": "Pull deal terms out of an offering memorandum, rent roll, T-12 or listing. Every "
                   "field comes back with the quote it came from and a source label; anything not "
                   "stated comes back null. Nothing is inferred or filled in — the model, not the "
                   "reader, is allowed to assume.",
    "parameters": {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Raw text pasted from the document"},
            "path": {"type": "string", "description": "Local .txt/.md/.csv/.json/.pdf file to read"},
            "url": {"type": "string", "description": "Listing or document URL to fetch"},
            "property_type": {"type": "string", "description": "Used only when the document does not state it"},
        },
        "required": [],
    },
}

MEMO = {
    "name": "uw_memo",
    "description": "Write an investment memo from a screen result: verdict and reasons, the NOI "
                   "bridge, price metrics, debt capacity, the counter-price, every assumption and "
                   "every warning. Deterministic template — the memo says exactly what the model "
                   "computed, nothing more.",
    "parameters": {
        "type": "object",
        "properties": {
            "deal": DEAL_SCHEMA,
            "buy_box": BUY_BOX_SCHEMA,
            "out_path": {"type": "string", "description": "Where to write the .md file; defaults to the plugin data dir"},
        },
        "required": ["deal"],
    },
}

SAVE = {
    "name": "uw_save",
    "description": "Save a screened deal to the deal book, keeping the screen, the inputs and the "
                   "date. Re-saving the same name updates it.",
    "parameters": {
        "type": "object",
        "properties": {
            "deal": DEAL_SCHEMA,
            "buy_box": BUY_BOX_SCHEMA,
            "name": {"type": "string", "description": "Deal book name; defaults to the deal's own name"},
        },
        "required": ["deal"],
    },
}

DEALS = {
    "name": "uw_deals",
    "description": "List the deal book, fetch one deal, or compare saved deals on cap rate, DSCR, "
                   "price per unit and verdict. Comparison is sorted by cap rate.",
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["list", "get", "compare"], "default": "list"},
            "name": {"type": "string", "description": "For action=get"},
            "names": {"type": "array", "items": {"type": "string"}, "description": "For action=compare"},
        },
    },
}

ALL = [SCREEN, TRIAGE, RETURNS, EXTRACT, MEMO, SAVE, DEALS]
