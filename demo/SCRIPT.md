# 90-second demo — shot list and narration

**What the video has to prove:** the arithmetic is code, not prose, and the code argues with its
own assumptions. One deal, one verdict, one counter.

**Setup before recording**
- Terminal 120×36, ~16pt, dark theme, prompt visible, `cd ~/hermes-underwriting && clear`.
- Notifications off. 1080p. Cursor parked out of the way.
- Two takes: **A** = live extraction (`hermes -z`), **B** = the arithmetic
  (`python3 demo/demo.py`). Cut them together. Never show a model thinking for 40 seconds.

---

## Beat 1 — the problem (0:00–0:11)

*On screen:* `cat examples/om-grandview.txt`

> "Every offering memorandum has a net operating income in it. It's never yours. It's the seller's
> rent roll, the seller's expenses, and a tax bill that changes the day you buy it."

## Beat 2 — extract, live (0:11–0:30)

*On screen:* run the real call:

```
hermes -z "uw_extract on examples/om-grandview.txt, then uw_screen the deal"
```

> "So first, extraction — and it shows its receipts: every number with the line of the document it
> came from, verified against the text, not taken on faith. Where the document is silent —
> rentable square feet, reserves — it returns null. It does not guess."

## Beat 3 — the rebuild (0:30–0:55)

*On screen:* `python3 demo/demo.py` — block 1.

> "Now the arithmetic. Gross potential rent from the rent roll, vacancy, credit loss, ten expense
> lines: a rebuilt NOI of a hundred ninety thousand five hundred. The seller claims a hundred
> eighty-eight — two thousand five hundred *low*, which is the first time that's happened.
>
> Cap rate six-four-six. Expenses pass, occupancy passes, debt service fails at one-nineteen-eight
> against a one-twenty-five floor. So: reject — and every rejection comes with a number.
> Two million eight hundred twenty-eight thousand. Four percent under ask, bound by DSCR."

## Beat 4 — the sweep (0:55–1:08)

*On screen:* block 2, the nine-row table.

> "Which begs the only question a broker cares about: where does it flip? Sweep the price and re-run
> every test at each step — including the taxes, because your tax bill follows what you pay. It
> flips between two-eighty and two-ninety-five. That's the negotiation, in one table."

## Beat 5 — the honest part (1:08–1:23)

*On screen:* block 3, the two conventions.

> "And here's the part I'd want a judge to see. Under the seller's convention, reserves ignored, my
> NOI sits twenty-five hundred *above* his claim. Add reserves — three hundred a unit — and the same
> NOI sits forty-seven hundred *below* it. Nothing changed but a convention, and it decides whether
> his number is conservative or optimistic."

## Beat 6 — close (1:23–1:30)

*On screen:* scroll the memo, then the repo URL.

> "Seven tools, a slash command, thirty-two tests, no dependencies, no network calls. The math is
> code. The model only does language. Hermes underwriting — link below."

---

## Voiceover budget

≈240 words ≈ 88 seconds at an even analytic pace. If you run long, cut "which begs the only
question a broker cares about" and the "first time that's happened" aside.

## Post text

> Most "AI underwriting" is a prompt that invents a cap rate. This one won't.
>
> 7 tools for Hermes Agent: rebuild NOI from the rent roll, test the box, solve for the
> counter-price, sweep where the deal flips, model the hold. Returns `null` when the document
> doesn't say — and checks every number against the line it came from.
>
> Pure stdlib. No network calls. 32 tests. @NousResearch
> github.com/johnnyminer/hermes-underwriting

Tag `@NousResearch` in the post body, repo link in the same post, video under 90 seconds.

## What not to do

- Don't narrate features. Every second should be a number changing for a reason.
- Don't use a real OM you don't want public — `examples/om-grandview.txt` is synthetic.
- Don't claim it replaces an underwriter. Say it refuses to invent a number, then stop.

## Numbers on screen (so the narration and the terminal agree)

| item | value |
|---|---|
| ask | $2,950,000 · $122,917/unit |
| gross potential rent | $315,360 |
| EGI | $295,800 |
| opex | $105,274 (35.59% of EGI) |
| rebuilt NOI | $190,526 |
| seller claim | $188,000 (−$2,526) |
| cap | 6.458% |
| breakeven occupancy | 83.87% |
| DSCR | 1.198 vs 1.25 floor |
| counter-price | $2,828,306 (−4.1%, −$121,694) |
| flip point | between $2,802,500 PASS and $2,950,000 REJECT |
| reserves | $7,200 → NOI $183,326 (claim +$4,674) |
