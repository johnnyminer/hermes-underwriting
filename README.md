# hermes-underwriting

Commercial real estate underwriting for [Hermes Agent](https://hermes-agent.nousresearch.com) that
shows its work — and refuses to invent a number it was not given.

Every figure comes from arithmetic on your inputs. The language model writes the prose; it never
touches the math. That means the same deal always produces the same verdict, the same memo, and the
same counter-price, on any machine, with no network calls.

```text
> underwrite 1420 Grandview Ave — 24 units, $2.95M ask

Ask price          $2,950,000  ($122,917/unit, 24 units)
Rebuilt NOI        $190,526
Cap rate           6.458%   (pass, min 6.00%)
Expense ratio      35.59%   (pass, max 45%)
Occupancy          91.67%   (pass, min 85%)
Breakeven occ.     83.87%
Counter-price      $2,828,306 (−4.1%, $121,694 off ask), bound by DSCR
```

## Why it exists

A broker's OM is an argument, not a dataset. The seller's NOI is a claim. The tax bill you inherit
is not the one in the T-12. The vacancy assumption is the previous owner's, not yours. Most tools
smooth all of that into one confident cap rate.

This plugin does the opposite:

- **Nothing is invented.** An omitted line is 0 with a warning, never a type default. `null` comes
  back as `null`.
- **The seller's NOI is a claim.** It's carried as `t12_noi_claim` and diffed against the rebuilt
  NOI. A gap is the negotiation, not an error to smooth over.
- **Incomplete is not bad.** Missing data returns `INCOMPLETE` with the missing fields named — not
  a silent REJECT and not a guessed PASS.
- **Every rejection comes with a number.** `counter_price` solves for the price at which the deal
  actually clears the box, with the binding constraint named.
- **Price changes taxes.** Property taxes are reassessed at the purchase price, and re-run at every
  price in a triage sweep, so the cap/price curve bends instead of being a straight line.

## Install

```bash
git clone https://github.com/johnnyminer/hermes-underwriting ~/hermes-underwriting
ln -s ~/hermes-underwriting ~/.hermes/plugins/underwriting
hermes plugins enable underwriting
hermes plugins validate ~/.hermes/plugins/underwriting
```

Python 3.10+. No third-party packages, nothing to `pip install`. PDFs need `poppler-utils`
(`pdftotext`) for `uw_extract`; everything else runs on the standard library.

## Tools

| Tool | What it does |
|---|---|
| `uw_extract` | Pull deal terms out of an OM, rent roll, T-12 or listing. Every field returns with its verbatim quote and source label; unstated fields return `null`. |
| `uw_screen` | Rebuild NOI line by line, compute cap rate, price/unit, price/SF, breakeven occupancy, size four debt structures against DSCR and debt yield, run the buy-box tests, return a verdict and the counter-price. |
| `uw_triage` | Sweep a price range: cap, DSCR and verdict at each price; the highest price that still passes; the price where it stops working. Taxes re-run at every price. |
| `uw_returns` | Annual proforma through the hold, levered/unlevered IRR, equity multiple, NPV, cash-on-cash and DSCR by year, exit on forward NOI, optional exit-cap × rent-growth sensitivity grid. |
| `uw_memo` | Deterministic investment memo from the computed screen — verdict, NOI bridge, debt table, tests, counter, warnings, assumptions. |
| `uw_save` | Save a screened deal to the deal book. |
| `uw_deals` | List, fetch or compare saved deals by cap rate, DSCR and verdict. |

Plus a `/underwrite` slash command (`/underwrite deal.json`, `/underwrite list`) and a bundled
`screen` skill that encodes the analyst workflow: extract → screen → counter → sweep → returns.

## Example

```bash
python3 -m unittest discover -s tests      # 23 tests, no pytest needed
hermes -z "Underwrite examples/bethel-office.json and tell me where the deal flips"
```

`examples/maple-ridge.json` passes at ask. `examples/bethel-office.json` does not — it needs a
20.9% cut, bound by the office 7.5% cap floor, not by debt.

## Input shape

Only include numbers you actually have. Omitted fields are reported, not filled.

```json
{
  "name": "1420 Grandview Ave",
  "market": "Columbus, OH",
  "property_type": "multifamily",
  "price": 2950000,
  "units": 24,
  "year_built": 1972,
  "tax_rate_pct": 1.2,
  "income": {
    "gross_potential_rent": 315360,
    "occupancy_pct": 91.67,
    "credit_loss_pct": 1.0,
    "recoveries": 0,
    "other_income": 9600,
    "t12_noi": 188000
  },
  "opex": {
    "taxes": 38400, "insurance": 11200, "utilities": 14800,
    "repairs_maintenance": 19500, "payroll": 8400,
    "general_admin": 4100, "management_pct_egi": 3.0
  },
  "debt": [
    {"name": "Bank 65%", "ltv_pct": 65, "rate_pct": 6.75, "amort_years": 25}
  ]
}
```

`buy_box` overrides the per-type thresholds; omit it and the defaults for the property type apply
(multifamily 6.0% min cap, office 7.5%, retail 6.75%, industrial 6.5%, self-storage 8.0%; min DSCR
1.25). Defaults live in `assumptions.py` and every one of them is labeled an assumption in the
output, never presented as a market fact.

## How it's put together

```
__init__.py      registration: tools, /underwrite command, skill
schemas.py       tool schemas, plain dicts
tools.py         handlers: I/O, extraction, deal book
engine.py        NOI rebuild, tests, verdict, counter-price, triage, IRR/NPV primitives
returns.py       proforma, levered/unlevered IRR, exit, sensitivity grid
memo.py          deterministic memo template
assumptions.py   per-property-type defaults, explicitly labeled as defaults
tests/           23 tests: hand-computed engine numbers + end-to-end tool calls
```

The engine is pure arithmetic over a normalized deal dict. `screen()` is idempotent-safe, so
triaging a deal re-prices the same income basis instead of re-deriving it.

## Limitations — read this

- **Not investment advice.** It is a screening model. Verify inputs; it cannot verify them for you.
- **No market data.** No comps, no rent comps, no cap-rate surveys. It underweights what you give
  it, which is why `INCOMPLETE` is a common and honest answer.
- **Conventions are choices.** Exit is on forward (year N+1) NOI at the exit cap. Debt amortizes on
  schedule with no refinance modeled. Both are stated in the output.
- **Extraction is LLM-backed.** Document reading can miss or misread a line; the arithmetic around
  it cannot. Check `provenance` on anything that matters.
- **No OCR.** A scanned PDF needs a text layer.

## License

MIT
