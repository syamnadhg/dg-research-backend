"""Capture Claude's model popover, so the Effort row can be scoped from real markup.

DGOPS-9627 is blocked on one thing: the row that opens the Effort submenu is found
by matching text across the WHOLE page, which is the same unscoped shape that
pressed a sidebar conversation link in DGOPS-9626. Scoping it needs to know which
container the row actually sits in, and writing that scope without a capture means
guessing at a container — a wrong guess turns an intermittent quality loss into a
permanent one.

WHY A CAPTURE AND NOT A PRESS
============================
The obvious probe would drive the real setup step repeatedly and count how often
the submenu mounts. It cannot be run without side effects: the submenu is only
attempted when the wanted tier DIFFERS from what the composer already shows, so
forcing that path means asking for a tier the account is not on — and if the press
succeeds, the account's effort setting is genuinely changed.

This is read-only instead. It opens the popover, records its markup, and presses
Escape. Nothing is clicked inside it, no setting moves, and no message is sent, so
it consumes no research quota. What it produces is exactly the ticket's first
acceptance point, and the captured file can then be replayed through the real
selector under `tests/_domshim.py` — no further live run needed to write or verify
the fix.

⛔ STOP `--serve` FIRST. Both use the same browser profile directory, and
`Browser.start()` sweeps orphaned Chromes from that directory — running this
alongside a live backend risks killing the pipeline's own browser.

    python scripts/claude_popover_capture.py [--rounds N] [--headless]

Each round is an independent open/capture/close, because a popover that mounts on
the first attempt and not the fourth is itself the finding.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import research  # noqa: E402

OUT_DIR = Path.home() / ".super-research" / "logs"

# Finds the model trigger the way production does — the visible button naming the
# current family, outside any already-open menu — then reports the popover that
# appeared. Deliberately does NOT press anything inside the popover.
FIND_TRIGGER_JS = """(fam) => {
    const btns = [...document.querySelectorAll('button, [role="button"]')]
        .filter(b => b.getClientRects().length > 0
                     && !b.closest('[role="menu"], [role="listbox"], [role="dialog"]'));
    const famRe = new RegExp(fam, 'i');
    const trigger = btns.find(b => famRe.test(b.textContent || ''));
    if (!trigger) return {found: false, buttons: btns.length};
    trigger.setAttribute('data-sr-probe', '1');
    return {found: true, text: (trigger.textContent || '').trim().slice(0, 80)};
}"""

# After the popover is open: describe every mounted overlay, and for any row whose
# text begins with "effort", walk its ancestors. That ancestor chain IS the answer
# the ticket needs — which container to scope the search to.
DESCRIBE_JS = """() => {
    const desc = (el) => ({
        tag: el.tagName,
        role: el.getAttribute('role') || '',
        id: el.id || '',
        cls: String(el.className || '').split(/\\s+/).filter(Boolean).slice(0, 4),
        testid: el.getAttribute('data-testid') || '',
        radix: [...el.attributes].map(a => a.name)
            .filter(n => n.startsWith('data-radix') || n.startsWith('data-state')),
    });
    const out = {overlays: [], effort_rows: []};
    const OVERLAY = '[role="menu"], [role="listbox"], [role="dialog"], [data-radix-popper-content-wrapper]';
    for (const c of document.querySelectorAll(OVERLAY)) {
        if (!c.getClientRects().length) continue;
        const rows = [...c.querySelectorAll('[role="menuitem"], [role="option"], button, a, div')]
            .filter(e => e.getClientRects().length);
        out.overlays.push({
            box: desc(c),
            rows: rows.length,
            labels: rows.map(e => (e.textContent || '').replace(/\\s+/g, ' ').trim())
                .filter(t => t && t.length <= 28).slice(0, 20),
            html_len: (c.outerHTML || '').length,
        });
    }
    for (const el of document.querySelectorAll('*')) {
        const t = (el.textContent || '').replace(/\\s+/g, ' ').trim();
        if (!/^effort\\b/i.test(t) || t.length > 40) continue;
        if (!el.getClientRects().length) continue;
        const chain = [];
        let n = el;
        for (let i = 0; i < 8 && n; i++) { chain.push(desc(n)); n = n.parentElement; }
        out.effort_rows.push({text: t.slice(0, 40), ancestors: chain,
                              kids: el.childElementCount});
    }
    return out;
}"""

# ⚠ EVERY visible overlay, not the largest. The first run of this probe kept only
# the biggest one, which is the model popover — so when the Effort submenu was open
# alongside it, the submenu's markup was thrown away and only its row labels
# survived in the JSON. The submenu is the smaller of the two and it is the one the
# fix needs.
CAPTURE_HTML_JS = """() => {
    const OVERLAY = '[role="menu"], [role="listbox"], [role="dialog"], [data-radix-popper-content-wrapper]';
    return [...document.querySelectorAll(OVERLAY)]
        .filter(c => c.getClientRects().length)
        .map(c => c.outerHTML);
}"""


async def one_round(page, n: int, stamp: str) -> dict:
    family = research.p2_family("claude") or "opus"
    got = await page.evaluate(FIND_TRIGGER_JS, family)
    if not got.get("found"):
        return {"round": n, "trigger": False, "buttons": got.get("buttons")}

    # A real press: a synthetic click inside page.evaluate does not open a React
    # overlay — proved on three separate surfaces in this repo.
    await page.click('[data-sr-probe="1"]')
    await asyncio.sleep(1.2)

    described = await page.evaluate(DESCRIBE_JS)
    htmls = await page.evaluate(CAPTURE_HTML_JS) or []
    for k, one in enumerate(htmls):
        (OUT_DIR / f"claude_model_popover_{stamp}_r{n}_o{k}.html").write_text(
            one, encoding="utf-8")
    html = "".join(htmls)
    j = OUT_DIR / f"claude_model_popover_{stamp}_r{n}.json"
    j.write_text(json.dumps(described, indent=2, ensure_ascii=False), encoding="utf-8")

    # Leave the UI exactly as we found it.
    try:
        await page.keyboard.press("Escape")
        await asyncio.sleep(0.4)
        await page.evaluate(
            "() => document.querySelectorAll('[data-sr-probe]')"
            ".forEach(e => e.removeAttribute('data-sr-probe'))")
    except Exception:
        pass

    return {"round": n, "trigger": True, "trigger_text": got.get("text"),
            "overlays": len(described.get("overlays") or []),
            "effort_rows": len(described.get("effort_rows") or []),
            "html_chars": len(html)}


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=5)
    ap.add_argument("--headless", action="store_true")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    browser = research.Browser(research.PROFILE_DIR, headless=args.headless)
    await browser.start()
    rows = []
    try:
        page = browser.page
        await page.goto("https://claude.ai/new", wait_until="domcontentloaded")
        await asyncio.sleep(3.0)
        for n in range(1, args.rounds + 1):
            try:
                rows.append(await one_round(page, n, stamp))
            except Exception as e:
                rows.append({"round": n, "error": f"{type(e).__name__}: {e}"[:160]})
            await asyncio.sleep(1.0)
    finally:
        try:
            await browser.close()
        except Exception:
            pass

    print()
    print(f"  {'round':>5}  {'trigger':>7}  {'overlays':>8}  {'effort rows':>11}  "
          f"{'popover chars':>13}")
    for r in rows:
        if r.get("error"):
            print(f"  {r['round']:>5}  ERROR {r['error']}")
            continue
        print(f"  {r['round']:>5}  {str(r.get('trigger')):>7}  "
              f"{r.get('overlays', 0):>8}  {r.get('effort_rows', 0):>11}  "
              f"{r.get('html_chars', 0):>13}")
    mounted = sum(1 for r in rows if (r.get("overlays") or 0) > 0)
    found = sum(1 for r in rows if (r.get("effort_rows") or 0) > 0)
    print(f"\n  popover mounted {mounted}/{len(rows)} · an effort row was visible "
          f"{found}/{len(rows)}")
    print(f"  captures: {OUT_DIR}/claude_model_popover_{stamp}_r*.html|json")
    print("  Nothing was clicked inside the popover and no setting was changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
