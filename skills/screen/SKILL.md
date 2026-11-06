---
name: screen
description: Underwrite a commercial property the way an analyst does — rebuild the NOI, test the box, name the counter-price, and keep facts separate from assumptions.
---

# Underwriting a deal

Use this when someone hands you a commercial property — an OM, a rent roll, a listing, a
"what do you think of this?" — and wants a number, not a vibe.

## The order of operations

1. **Extract, don't assume.** If you have a document, `uw_extract` it. The tool returns every
   field with the quote it came from and `null` for anything the document did not state. Do not
   fill those nulls yourself. A null is a question for the broker.
2. **Screen.** `uw_screen` with the extracted deal. Read the `verdict`, then read `warnings` —
   the verdict is the headline, the warnings are the deal.
3. **Handle INCOMPLETE honestly.** If the screen comes back INCOMPLETE, say exactly what is
   missing and ask for it. Never substitute an estimate to force a verdict. An INCOMPLETE screen
   with a specific ask is more useful than a PASS built on a guess.
4. **Get to the counter.** On a REJECT, `counter_price` is the number at which the deal clears
   the box, with the binding constraint named. Lead with it: "at $4.1M this works; at $5.0M it
   doesn't" is the whole conversation.
5. **Sweep the range.** `uw_triage` when the seller is negotiable or the ask is soft — it shows
   where the deal flips and what the cap/DSCR look like at each price. Taxes re-run at every
   price, so the curve is not a straight line.
6. **Only then talk returns.** `uw_returns` with `sensitivity: true`. A levered IRR without an
   exit-cap sensitivity is marketing, not analysis.
7. **Write it down.** `uw_memo` produces a memo from the computed screen — deterministic, so it
   cannot disagree with the numbers. `uw_save` puts the deal in the book for comparison.

## Hard rules

- **Never produce a number the engine did not compute.** No mental arithmetic in the reply, no
  "roughly a 7 cap" when the screen said 6.16%. If you want a figure, run the tool.
- **Separate facts from assumptions in every reply.** Documented: rents, occupancy, opex, price.
  Assumed: vacancy, credit loss, management fee, reserves, growth, exit cap. Say which is which.
- **The seller's NOI is a claim.** Report the gap between `noi` and `noi_claim` when it exists and
  treat the gap as the negotiation, not an error to smooth over.
- **Never hide a warning to make a deal look better.** Every warning the screen raised appears in
  your answer, in the same words.
- **Say what would change the answer.** "This passes at 6.16% only because taxes stay at the
  seller's bill" is the sentence that makes the analysis useful.

## What the defaults are and why they are not facts

Vacancy, credit loss, management % and reserves come from the property type
(`assumptions.py`) and are labeled as assumptions in the output. Ohio property taxes are
reassessed at the purchase price by default (`tax_rate_pct`, 1.2%) — the buyer's bill, not the
seller's. If a deal only works at the seller's tax bill, that is the finding.

## Buy box

Defaults are per property type (multifamily 6.0% min cap, office 7.5%, industrial 6.5%, storage
8.0%, min DSCR 1.25). Override with `buy_box` when the investor's mandate differs — and say in
the reply which thresholds you used, because "it doesn't pencil" is meaningless without them.
