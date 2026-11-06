"""Hermes plugin entry point: registers the underwriting tools, the /underwrite command and the skill.

The plugin has no network dependencies and no third-party packages. A screen is pure arithmetic
over the inputs, which is why the same deal always produces the same memo — and why nothing here
can fail because an API moved.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

try:  # loaded as hermes_plugins.<slug>
    from . import engine, memo, schemas, tools
except ImportError:  # loaded flat
    import engine
    import memo
    import schemas
    import tools

EMOJI = {
    "uw_screen": "🏢",
    "uw_triage": "📉",
    "uw_returns": "📈",
    "uw_extract": "📄",
    "uw_memo": "📝",
    "uw_save": "💾",
    "uw_deals": "📚",
}


def register(ctx):
    tools.bind(ctx)

    for schema in schemas.ALL:
        name = schema["name"]
        ctx.register_tool(
            name=name,
            toolset="underwriting",
            schema=schema,
            handler=tools.HANDLERS[name],
            description=schema["description"],
            emoji=EMOJI.get(name, "🏢"),
        )

    ctx.register_command(
        "underwrite",
        _underwrite_command,
        description="Screen a deal from a JSON file, or show the deal book",
        args_hint="<deal.json | list>",
    )

    skill_path = Path(__file__).parent / "skills" / "screen" / "SKILL.md"
    if skill_path.exists():
        ctx.register_skill(
            "screen",
            skill_path,
            description="Underwrite a commercial property the way an analyst does: rebuild NOI, "
                        "test the box, name the counter-price, and separate facts from assumptions.",
            frontmatter={"name": "underwriting:screen"},
        )


def _load_deal_file(path: str) -> dict:
    p = Path(os.path.expanduser(path))
    if not p.exists():
        raise FileNotFoundError(f"no such file: {p}")
    data = json.loads(p.read_text(encoding="utf-8"))
    # Accept either a bare deal or {"deal": {...}, "buy_box": {...}}
    if isinstance(data, dict) and isinstance(data.get("deal"), dict):
        return {"deal": data["deal"], "buy_box": data.get("buy_box")}
    return {"deal": data}


def _underwrite_command(raw_args: str = "") -> str:
    arg = (raw_args or "").strip()
    try:
        if not arg or arg.lower() in ("list", "ls", "book"):
            book = tools._book()  # noqa: SLF001 - same package
            if not book:
                return ("The deal book is empty. Screen a deal with `uw_screen`, save it with "
                        "`uw_save`, or run `/underwrite path/to/deal.json`.")
            lines = ["**Deal book**", ""]
            for name, entry in sorted(book.items()):
                screen = entry.get("screen") or {}
                cap = screen.get("cap_rate_pct")
                lines.append(f"- **{name}** — {screen.get('verdict', '?')} · "
                             f"{f'{cap:.2f}% cap' if cap else 'n/a'} · "
                             f"${screen.get('price', 0):,.0f} · saved {entry.get('saved', '?')}")
            return "\n".join(lines)

        payload = _load_deal_file(arg)
        result = engine.screen(payload["deal"], payload.get("buy_box"))
        if result.get("verdict") == "INCOMPLETE":
            return (f"**INCOMPLETE** — {result.get('reason')}\n\n"
                    f"Missing: {', '.join(result.get('missing') or [])}")
        return memo.build_memo(result)
    except Exception as exc:  # noqa: BLE001 - a command should report, not crash the session
        return f"underwrite: {type(exc).__name__}: {exc}"
