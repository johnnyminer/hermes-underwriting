"""Tool handlers. Thin wrappers: the model does the arithmetic, the handlers do I/O and shape."""

from __future__ import annotations

import json
import os
import re
import urllib.error
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


_PLUGIN_ROOT = os.path.dirname(os.path.abspath(__file__))

_MAX_FETCH_BYTES = 8 * 1024 * 1024
_MAX_REDIRECTS = 3


def _file_safety():
    """Hermes' own read/write guards, when the host provides them."""
    try:
        from agent.file_safety import get_read_block_error, get_write_denied_error
        return get_read_block_error, get_write_denied_error
    except Exception:  # noqa: BLE001 - older hosts, or a flat import under unittest
        return None, None


def guard_read(path: str) -> str:
    read_block, _ = _file_safety()
    if read_block:
        error = read_block(str(path))
        if error:
            raise PermissionError(error)
    return path


def guard_write(path: str) -> str:
    _, write_denied = _file_safety()
    if write_denied:
        error = write_denied(str(path))
        if error:
            raise PermissionError(error)
    return path


def export_dir() -> str:
    """Where this plugin is allowed to write: its own data directory, nothing else."""
    ctx = _ctx()
    base = getattr(getattr(ctx, "state", None), "data_dir", None) or \
        os.path.expanduser("~/.hermes/plugin-data/underwriting")
    return os.path.join(str(base), "exports")


def resolve_output(name: str | None, default_name: str | None = None) -> str:
    """Turn a caller-supplied name into a path inside the plugin's own data directory.

    The model may choose the filename, not the destination. A document is untrusted input, so a
    document that says "write the audit trail to ~/.bashrc" must not be able to steer a write onto
    a shell rc file, the Hermes config, or an env file.
    """
    name = (name or default_name or "").strip()
    if not name:
        raise ValueError("no output filename")
    if os.path.basename(name) != name or name in (".", "..") or os.sep in name or "\\" in name:
        raise ValueError(f"out_path must be a bare filename, not a path: {name!r}. "
                         f"Pass something like 'audit.json' - it lands in the plugin's own "
                         f"data directory.")
    root = os.path.realpath(export_dir())
    target = os.path.realpath(os.path.join(root, name))
    if os.path.dirname(target) != root:
        raise ValueError(f"refusing to write outside {root}: {name!r}")
    os.makedirs(root, exist_ok=True)
    return guard_write(target)


def resolve_path(path: str) -> str:
    """Find a document the caller named relatively.

    A plugin does not run from the caller's directory - the host may be a long-lived gateway whose
    cwd is the home directory - so a relative path is resolved against the cwd and then the plugin
    root. The failure names where it looked. There is deliberately no $HOME fallback: reading the
    home directory on behalf of a model-supplied path is how a document gets to pick its own target.
    """
    p = os.path.expanduser(path)
    if os.path.isabs(p):
        return guard_read(p)
    tried = [os.path.join(os.getcwd(), p), os.path.join(_PLUGIN_ROOT, p)]
    for candidate in tried:
        if os.path.exists(candidate):
            return guard_read(candidate)
    raise FileNotFoundError(f"no such file: {path} (tried {', '.join(dict.fromkeys(tried))})")


def assert_public_url(url: str) -> str:
    """http(s) only, and only to public addresses.

    A bare `urlopen` will happily read `file:///etc/passwd`, hop to 127.0.0.1, sweep the LAN, or
    reach a cloud metadata endpoint. Since the URL can come out of a document the model just read,
    every hop has to be checked.
    """
    import ipaddress
    import socket
    from urllib.parse import urlsplit

    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise ValueError(f"only http and https URLs can be fetched, not "
                         f"{parts.scheme or 'a bare path'!r}")
    host = parts.hostname
    if not host:
        raise ValueError(f"no host in URL: {url!r}")
    port = parts.port or (443 if parts.scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError(f"cannot resolve {host}: {exc}") from exc
    for info in infos:
        ip = ipaddress.ip_address(str(info[4][0]).split("%")[0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
                or ip.is_multicast or ip.is_unspecified):
            raise ValueError(f"refusing to fetch {url}: {host} resolves to the non-public "
                             f"address {ip}")
    return url


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Surface redirects as HTTPError so each hop can be re-checked before it is followed."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        return None


def fetch_url(url: str) -> tuple[bytes, str, str]:
    """Fetch http(s) only: scheme and address checked on every hop, size capped."""
    from urllib.parse import urljoin

    current = url
    for _ in range(_MAX_REDIRECTS + 1):
        assert_public_url(current)
        req = urllib.request.Request(current, headers={
            "User-Agent": "Mozilla/5.0 (compatible; hermes-underwriting/1.0)",
            "Accept": "text/html,application/pdf,text/plain,*/*",
        })
        try:
            with urllib.request.build_opener(_NoRedirect).open(req, timeout=30) as resp:
                raw = resp.read(_MAX_FETCH_BYTES + 1)
                ctype = (resp.headers.get("Content-Type") or "").lower()
        except urllib.error.HTTPError as exc:
            if exc.code in (301, 302, 303, 307, 308):
                location = exc.headers.get("Location")
                if not location:
                    raise ValueError(f"redirect with no Location from {current}") from exc
                current = urljoin(current, location)
                continue
            raise
        if len(raw) > _MAX_FETCH_BYTES:
            raise ValueError(f"document is larger than {_MAX_FETCH_BYTES // (1024 * 1024)} MB")
        return raw, ctype, current
    raise ValueError(f"more than {_MAX_REDIRECTS} redirects fetching {url}")


def load_document(text: str | None = None, path: str | None = None, url: str | None = None) -> str:
    """Get plain text from whatever the caller has. No OCR: a scanned PDF is a real wall."""
    if text:
        return text
    if path:
        p = resolve_path(path)
        ext = os.path.splitext(p)[1].lower()
        if ext == ".pdf":
            return _pdf_to_text(p)
        with open(p, encoding="utf-8", errors="replace") as handle:
            return handle.read()
    if url:
        raw, ctype, final_url = fetch_url(url)
        if "pdf" in ctype or final_url.lower().endswith(".pdf"):
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
1. Only extract what the document states. If a field is not stated AND cannot be aggregated from
   stated rows, return null. Do NOT estimate, assume a market norm, or pro-rate. A null is a
   useful answer; an invented number is a data-integrity failure.
2. Aggregation from stated rows is allowed and encouraged — it is not inference. If the document
   gives a per-unit rent and a unit count, gross_potential_rent = rent x units x 12, labeled
   "derived" with the arithmetic written out. Occupancy from occupied/total units is the same.
   Anything you carry across from another document or from experience is forbidden.
3. Annual dollars unless the document labels otherwise. If a figure is monthly, annualize it and
   say so in the quote.
4. "t12_noi" is the seller's claim verbatim. Put it there even if you think it is wrong. Never put
   a computed NOI there.
5. Return ONLY JSON with exactly two top-level keys: "deal" and "provenance".
   - "deal" matches the schema below.
   - "provenance" is an object keyed by dotted path ("price", "income.gross_potential_rent",
     "opex.taxes"). EVERY non-null field in "deal" must have an entry:
       {{"source": "om|rent_roll|t12|listing|derived", "quote": "verbatim text, max 200 chars"}}
     For "derived", the quote is the arithmetic, e.g. "22 of 24 units x $1,095 x 12 = $315,360".
   - A non-null field with no provenance entry is a failure. Do not emit it.
6. Schema:
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


_NUM_LINE_MAX = 180


def _flatten_numbers(deal, prefix=""):
    """Every numeric leaf of a deal, keyed by dotted path."""
    out = []
    for key, value in (deal or {}).items():
        path = f"{prefix}{key}"
        if isinstance(value, dict):
            out.extend(_flatten_numbers(value, prefix=f"{path}."))
        elif isinstance(value, bool):
            continue
        elif isinstance(value, (int, float)):
            out.append((path, value))
    return out


def _variants(value):
    """The ways a document might write this number."""
    forms = set()
    for spec in (",.0f", ".0f", ",.2f", ".2f"):
        try:
            forms.add(format(value, spec))
        except (ValueError, TypeError):
            pass
    forms.add(str(value))
    return {f for f in forms if f}


def _find_in_document(doc, value):
    """Return the line of the document that states this number, or None.

    Independent of anything the model claims: the document either contains the figure or it does
    not. That is the whole point of verifying rather than trusting a quoted citation.
    """
    if not doc:
        return None
    for form in _variants(value):
        pattern = r"(?<![\d.])" + re.escape(form) + r"(?![\d])"
        match = re.search(pattern, doc)
        if match:
            start = doc.rfind("\n", 0, match.start()) + 1
            end = doc.find("\n", match.end())
            line = doc[start: end if end != -1 else len(doc)].strip()
            return line[:_NUM_LINE_MAX]
    return None


def _verify_provenance(deal, doc, claimed):
    """Attach a document line to every number, and audit the model's citations.

    The model may supply quotes; none of them are taken on faith. A field the model marks as
    coming from the document whose figure does not appear in the document is reported, not kept
    quietly.
    """
    claimed = claimed or {}
    provenance, warnings = {}, []
    for path, value in _flatten_numbers(deal):
        if value == 0:
            continue
        claim = claimed.get(path) or {}
        line = _find_in_document(doc, value)
        source = claim.get("source") or ("document" if line else "model")
        provenance[path] = {"source": source, "verified": bool(line),
                            "quote": line or claim.get("quote", "")}
        if not line:
            if claim.get("source") in ("om", "t12", "rent_roll", "listing"):
                warnings.append(f"{path} is cited from the document but {value:,.0f} does not "
                                f"appear in it - check this before it reaches the memo")
            elif claim.get("source") != "derived":
                warnings.append(f"{path} = {value:,.0f} is not stated in the document; it came "
                                f"from the model, not the source")
    return provenance, warnings


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
    provenance, audit = _verify_provenance(deal, doc, parsed.get("provenance"))
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
    warnings = list(audit)
    missing = [p for p, e in provenance.items() if not e["verified"]]
    if missing:
        warnings.append(f"{len(missing)} of {len(provenance)} numbers could not be matched to the "
                        f"document text: " + ", ".join(missing[:8]))

    payload = {
        "deal": deal,
        "provenance": provenance,
        "fields_extracted": len(known),
        "fields_verified": sum(1 for e in provenance.values() if e["verified"]),
        "characters_read": len(doc),
        "truncated": len(doc) > 60_000,
        "warnings": warnings,
        "next": "Run uw_screen with this deal. Anything null is a question for the broker, not a "
                "gap to fill with an estimate.",
    }

    out_path = args.get("out_path")
    if out_path:
        try:
            target = resolve_output(out_path, f"extract-{_slug(deal.get('name'))}.json")
        except (ValueError, PermissionError) as exc:
            payload["warnings"].append(f"not written: {exc}")
        else:
            with open(target, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, default=str)
            payload["written_to"] = target

    return _out(payload)


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
        out_name = args.get("out_path")
        target = resolve_output(out_name, f"memo-{_slug(result.get('deal'))}-{date.today():%Y%m%d}.md")
        with open(target, "w", encoding="utf-8") as handle:
            handle.write(text)
        return _out({"memo": target, "verdict": result.get("verdict"),
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
