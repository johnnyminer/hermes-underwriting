"""Tool handlers. Thin wrappers: the model does the arithmetic, the handlers do I/O and shape."""

from __future__ import annotations

import json
import os
import re
import urllib.request
from datetime import date

try:
    from . import engine, memo, returns
except ImportError:
    import engine
    import memo
    import returns

# Set by register() in __init__.py. Tools get no ctx argument, so the plugin keeps one reference.
_RUNTIME: dict = {"ctx": None}


def bind(ctx) -> None:
    _RUNTIME["ctx"] = ctx


def _ctx():
    return _RUNTIME.get("ctx")


def _out(payload) -> str:
    return json.dumps(payload, indent=2, default=str)


def _err(message: str, **extra) -> str:
    return _out({"error": message, **extra})


# ---------------------------------------------------------------- document input

_TAG_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.S | re.I)
_HTML_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[ \t\r\f\v]+")
_NL_RE = re.compile(r"\n{3,}")


def _html_to_text(html: str) -> str:
    import html as html_mod
    text = _TAG_RE.sub(" ", html)
    text = _HTML_RE.sub("\n", text)
    text = html_mod.unescape(text)
    text = _WS_RE.sub(" ", text)
    return _NL_RE.sub("\n\n", text).strip()


def _pdf_to_text(path: str) -> str:
    import shutil
    import subprocess
    exe = shutil.which("pdftotext")
    if not exe:
        raise RuntimeError("No PDF text layer available: install poppler-utils (`pdftotext`) or "
                           "paste the document text into the tool instead.")
    return subprocess.run([exe, "-layout", path, "-"], capture_output=True, text=True,
                          timeout=120, check=True).stdout


def load_document(text: str | None = None, path: str | None = None, url: str | None = None) -> str:
    """Get plain text from whatever the caller has. No OCR: a scanned PDF is a real wall."""
    if text:
        return text
    if path:
        p = os.path.expanduser(path)
        ext = os.path.splitext(p)[1].lower()
        if ext == ".pdf":
            return _pdf_to_text(p)
        with open(p, encoding="utf-8", errors="replace") as handle:
            return handle.read()
    if url:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (compatible; hermes-underwriting/1.0)",
            "Accept": "text/html,application/pdf,text/plain,*/*",
        })
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            ctype = (resp.headers.get("Content-Type") or "").lower()
        if "pdf" in ctype or url.lower().endswith(".pdf"):
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp.write(raw)
                tmp.flush()
                try:
                    return _pdf_to_text(tmp.name)
                finally:
                    os.unlink(tmp.name)
        return _html_to_text(raw.decode("utf-8", errors="replace"))
    raise ValueError("Nothing to read: pass text, path or url")


# ---------------------------------------------------------------- extraction prompt

EXTRACT_SCHEMA = {
    "name": {"type": "string|null", "note": "Property name or address"},
    "market": {"type": "string|null"},
    "property_type": {"type": "string|null",
                      "note": "one of multifamily, office, retail, industrial, self_storage, mixed, other"},
    "price": {"type": "number|null", "note": "Asking price, dollars"},
    "units": {"type": "number|null"},
    "nra_sf": {"type": "number|null"},
    "year_built": {"type": "number|null"},
    "income": {
        "gross_potential_rent": "number|null", "occupancy_pct": "number|null",
        "vacancy_pct": "number|null", "credit_loss_pct": "number|null",
        "recoveries": "number|null", "other_income": "number|null",
        "t12_egi": "number|null", "t12_noi": "number|null", "t12_opex": "number|null",
    },
    "opex": {
        "taxes": "number|null", "insurance": "number|null", "utilities": "number|null",
        "repairs_maintenance": "number|null", "payroll": "number|null",
        "general_admin": "number|null", "management": "number|null", "other_opex": "number|null",
    },
}

_EXTRACT_INSTRUCTIONS = """You are extracting deal facts from commercial real estate offering material.

Rules, in priority order:
1. Only extract what the document states. If a field is not stated, return null. Do NOT
   estimate, infer, pro-rate or compute a field from other fields. A null is a useful answer
   and an invented number is a data-integrity failure.
2. Annual dollars unless the document labels otherwise. Convert monthly to annual only when the
   document states the figure as monthly (say so in the quote).
3. "t12_noi" is the seller's claim. Put it there even if you think it is wrong. Never put a
   computed NOI there.
4. For every field you fill, record the verbatim quote (max 200 chars) that supports it, and a
   source label: om, rent_roll, t12, listing, or user.
5. If the document gives a rent roll with per-tenant rents, sum to gross potential rent and say
   so in the quote for gross_potential_rent (e.g. "sum of 14 tenant rows").
6. Return ONLY JSON matching this shape:
{schema}

JSON:"""


def _parse_json(text: str):
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\s*", "", t)
        t = re.sub(r"```\s*$", "", t).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        start, end = t.find("{"), t.rfind("}")
        if start >= 0 and end > start:
            return json.loads(t[start:end + 1])
        raise


def tool_extract(args: dict) -> str:
    try:
        doc = load_document(args.get("text"), args.get("path"), args.get("url"))
    except Exception as exc:  # noqa: BLE001 - surfaced to the model verbatim
        return _err(f"could not read the document: {exc}")

    ctx = _ctx()
    if ctx is None:
        return _err("no plugin context: extraction needs ctx.llm")

    trimmed = doc[:60_000]
    instructions = _EXTRACT_INSTRUCTIONS.format(schema=json.dumps(EXTRACT_SCHEMA, indent=1))
    prompt = f"{instructions}\n\n--- DOCUMENT ---\n{trimmed}"
    try:
        result = ctx.llm.complete(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=2000,
            purpose="underwriting-extract",
        )
        raw = getattr(result, "text", "") or ""
    except Exception as exc:  # noqa: BLE001
        return _err(f"extraction call failed: {type(exc).__name__}: {exc}")

    try:
        parsed = _parse_json(raw)
    except Exception:  # noqa: BLE001
        return _err("the model did not return JSON", raw=raw[:2000])

    deal = parsed.get("deal") or parsed
    if args.get("property_type") and not deal.get("property_type"):
        deal["property_type"] = args["property_type"]

    # Count what is actually known so the model can see how thin the evidence is.
    def _known(node, prefix=""):
        found = []
        for k, v in (node or {}).items():
            if isinstance(v, dict):
                found += _known(v, f"{prefix}{k}.")
            elif isinstance(v, (int, float)):
                found.append(f"{prefix}{k}")
        return found

    known = _known(deal)
    return _out({
        "deal": deal,
        "provenance": parsed.get("provenance") or {},
        "fields_extracted": len(known),
        "characters_read": len(doc),
        "truncated": len(doc) > 60_000,
        "next": "Run uw_screen with this deal. Anything null is a question for the broker, not a "
                "gap to fill with an estimate.",
    })


# ---------------------------------------------------------------- screens

def _deal_from(args):
    if not args.get("deal"):
        raise ValueError("this tool needs a `deal` object")
    return args["deal"]


def tool_screen(args: dict) -> str:
    try:
        result = engine.screen(_deal_from(args), args.get("buy_box"))
    except Exception as exc:  # noqa: BLE001
        return _err(f"screen failed: {type(exc).__name__}: {exc}")
    return _out(result)


def tool_triage(args: dict) -> str:
    try:
        result = engine.triage(_deal_from(args), args.get("lo"), args.get("hi"),
                               args.get("steps") or 25, args.get("buy_box"))
    except Exception as exc:  # noqa: BLE001
        return _err(f"triage failed: {type(exc).__name__}: {exc}")
    return _out(result)


def tool_returns(args: dict) -> str:
    try:
        deal = _deal_from(args)
        growth = {k: args[k] for k in ("hold_years", "rent_growth_pct", "expense_growth_pct",
                                       "exit_cap_pct") if args.get(k) is not None}
        pro = returns.proforma(deal, args.get("price"), args.get("scenario"), growth)
        if args.get("sensitivity"):
            pro["sensitivity"] = returns.sensitivity(deal, args.get("price"), base_growth=growth)
        return _out(pro)
    except Exception as exc:  # noqa: BLE001
        return _err(f"returns failed: {type(exc).__name__}: {exc}")


def tool_memo(args: dict) -> str:
    try:
        deal = _deal_from(args)
        result = engine.screen(deal, args.get("buy_box"))
        text = memo.build_memo(result)
        out_path = args.get("out_path")
        if not out_path:
            ctx = _ctx()
            base = ctx.state.data_dir if ctx else os.path.expanduser("~/.hermes/plugin-data/underwriting")
            out_path = os.path.join(str(base), f"memo-{_slug(result.get('deal'))}-{date.today():%Y%m%d}.md")
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return _out({"memo": out_path, "verdict": result.get("verdict"),
                     "bytes": len(text), "memo_text": text if len(text) < 8000 else text[:8000] + "\n…"})
    except Exception as exc:  # noqa: BLE001
        return _err(f"memo failed: {type(exc).__name__}: {exc}")


def _slug(name) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(name or "deal").lower()).strip("-")[:60] or "deal"


# ---------------------------------------------------------------- deal book

def _book() -> dict:
    ctx = _ctx()
    if ctx is None:
        raise RuntimeError("no plugin context: deal book unavailable")
    return ctx.state.get("deals", {}) or {}


def tool_save(args: dict) -> str:
    try:
        deal = _deal_from(args)
        result = engine.screen(deal, args.get("buy_box"))
        name = args.get("name") or result.get("deal") or "Untitled deal"
        book = _book()
        book[name] = {
            "name": name,
            "saved": date.today().isoformat(),
            "deal": deal,
            "screen": result,
        }
        _ctx().state.set("deals", book)
        return _out({"saved": name, "verdict": result.get("verdict"),
                      "cap_rate_pct": result.get("cap_rate_pct"),
                      "counter_price": (result.get("counter_price") or {}).get("price"),
                      "deals_in_book": len(book)})
    except Exception as exc:  # noqa: BLE001
        return _err(f"save failed: {type(exc).__name__}: {exc}")


def tool_deals(args: dict) -> str:
    action = (args.get("action") or "list").lower()
    try:
        book = _book()
    except Exception as exc:  # noqa: BLE001
        return _err(str(exc))

    if action == "get":
        entry = book.get(args.get("name") or "")
        return _out(entry) if entry else _err(f"no deal named {args.get('name')!r}", names=sorted(book))

    rows = []
    wanted = set(args.get("names") or [])
    for name, entry in book.items():
        if wanted and name not in wanted:
            continue
        screen = entry.get("screen") or {}
        primary = next((d for d in screen.get("debt") or [] if d.get("dscr")), None)
        rows.append({
            "name": name,
            "verdict": screen.get("verdict"),
            "cap_rate_pct": screen.get("cap_rate_pct"),
            "price": screen.get("price"),
            "price_per_unit": screen.get("price_per_unit"),
            "dscr": round(primary["dscr"], 2) if primary else None,
            "counter_price": (screen.get("counter_price") or {}).get("price"),
            "saved": entry.get("saved"),
        })
    rows.sort(key=lambda r: (r["cap_rate_pct"] is None, -(r["cap_rate_pct"] or 0)))
    return _out({"count": len(rows), "deals": rows})


HANDLERS = {
    "uw_screen": tool_screen,
    "uw_triage": tool_triage,
    "uw_returns": tool_returns,
    "uw_extract": tool_extract,
    "uw_memo": tool_memo,
    "uw_save": tool_save,
    "uw_deals": tool_deals,
}
