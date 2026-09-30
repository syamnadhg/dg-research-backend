"""Local claude.ai pages rebuilt from the owner's 09-30 captures, for headless Chrome.

The captures (`fixtures/claude_0930/1-claude-menus.json`, `2-claude-research.json`)
are the owner's armed recordings of claude.ai: every overlay and the last turn as
{tag, a:{attrs}, box, txtLen, label, k:[children]}, text only as labels of 40
characters or less, icon glyphs as private-use characters (\\ue03b is the ✓).
Structure only. This module renders those nodes back into HTML and places them in
one page, so the production code runs against the page's real markup.

What the captures SHOW is taken from them, node for node:

  * the model button ("Opus 5.5 Medium", data-testid model-selector-dropdown),
    the model popover, the Effort row and the Effort submenu with its
    `data-effort-id` rows (capture 1, frames 2 and 4);
  * the "+" button (data-testid chat-input-attach) and its menu with the
    Research row (`menuitemcheckbox`, data-testid add-menu-research) (frames
    16-17), and the same row checked (frame 22);
  * the left sidebar <aside aria-label="Sidebar"> (capture 2, frame 20);
  * the assistant turn mid-run with the research card (frame 24) and finished
    with the report card (frame 91);
  * the report header's Copy options button and its menu (frames 89-90);
  * the Research panel's region, list and sources-row ancestry (frames 49, 63).

ASSUMED — not in any capture, and said so where it is built:

  * how each control BEHAVES (what opens on a press or a hover, what closes):
    written to match the before/after states the frames show;
  * the composer's text box, the Research pill in the composer, the report body
    and the Research panel's inner text (step titles, the rows' "N sources" part
    after the 40-character label cut), and two sidebar rows the 09-30 run saved as
    steps ("Chats and tasks", "Pin projects to keep them here");
  * geometry: 1280×800, sidebar 288 px on the left, the side panel 560 px on the
    right.

Every press the page receives is recorded (as JSON in the root element's
`data-sr-presses`) as {what, trusted}, so a test can tell a real press from a
synthetic one.
"""
from __future__ import annotations

import html
import json
import re
from functools import lru_cache
from pathlib import Path

CAP = Path(__file__).resolve().parent / "fixtures" / "claude_0930"
_REDACTED = re.compile(r"<\d+ chars>")
_VOID = {"img", "input", "br", "hr", "meta", "link"}


@lru_cache(maxsize=None)
def capture(name: str) -> dict:
    return json.loads((CAP / name).read_text(encoding="utf-8"))


def frame(name: str, i: int) -> dict:
    return capture(name)["frames"][i]


def render(node: dict, *, attrs: dict | None = None, drop: tuple = ()) -> str:
    """One captured node and its captured children, as HTML."""
    tag = str(node.get("tag") or "div").lower()
    if tag == "svg":
        return "<svg></svg>"
    a = dict(node.get("a") or {})
    for k in drop:
        a.pop(k, None)
    if tag == "img":
        a.pop("src", None)                # never a request to a real site
    a.update(attrs or {})
    parts = []
    for k, v in a.items():
        if v is None:
            continue
        if isinstance(v, str) and _REDACTED.fullmatch(v):
            continue                      # an id the recorder hid: none at all
        parts.append(f' {k}="{html.escape(str(v), quote=True)}"'
                     if v != "" else f" {k}")
    open_tag = f"<{tag}{''.join(parts)}>"
    if tag in _VOID:
        return open_tag
    kids = node.get("k") or []
    inner = ("".join(render(c) for c in kids) if kids
             else html.escape(node.get("label") or ""))
    return f"{open_tag}{inner}</{tag}>"


def _clicked(name: str, i: int, tag: str) -> dict:
    """The pressed control from a frame's `clicked` chain (it has no children)."""
    for n in frame(name, i).get("clicked") or []:
        if n.get("tag") == tag and n.get("label") is not None:
            return n
    raise LookupError(f"{name} frame {i}: no {tag} in the clicked chain")


def _find(node: dict, pred):
    if pred(node):
        return node
    for k in node.get("k") or []:
        hit = _find(k, pred)
        if hit is not None:
            return hit
    return None


# ── the captured pieces ─────────────────────────────────────────────────────

M, R = "1-claude-menus.json", "2-claude-research.json"


def model_button(tier: str = "Medium") -> str:
    n = _clicked(M, 2, "BUTTON")                        # "Opus 5.5 Medium"
    assert n["a"]["data-testid"] == "model-selector-dropdown"
    return render(dict(n, label=f"Opus 5.5 {tier}"),
                  attrs={"aria-label": f"Model: Opus 5.5 {tier}", "aria-expanded": "false",
                         "id": "sr-model-trigger"},
                  drop=("data-popup-open", "data-pressed", "class"))


def plus_button() -> str:
    n = _clicked(M, 16, "BUTTON")                       # the "+" (\ue001)
    assert n["a"]["data-testid"] == "chat-input-attach"
    return render(n, attrs={"aria-expanded": "false", "id": "sr-plus"},
                  drop=("data-popup-open", "data-pressed", "class"))


def model_popover(tier: str = "medium") -> str:
    """Frame 4's popover, its Effort row reset to closed and reading `tier`."""
    wrap = json.loads(json.dumps(frame(M, 4)["menus"][0]))
    row = _find(wrap, lambda x: x.get("a", {}).get("aria-haspopup") == "menu"
                and (x.get("label") or "").startswith("Effort"))
    row["a"].update({"aria-expanded": "false", "id": "sr-effort-row"})
    for k in ("data-highlighted", "data-popup-open"):
        row["a"].pop(k, None)
    val = _find(row, lambda x: x.get("label") == "Medium")
    val["label"] = tier.capitalize()
    return render(wrap, attrs={"id": "sr-model-menu", "class": "sr-pop", "hidden": ""})


def effort_submenu() -> str:
    wrap = frame(M, 4)["menus"][2]                      # data-nested presentation
    assert _find(wrap, lambda x: x.get("a", {}).get("data-effort-id") == "xhigh")
    return render(wrap, attrs={"id": "sr-effort-menu", "class": "sr-pop sr-pop2",
                               "hidden": ""})


def plus_menu(research_on: bool = False, *, testid: bool = True,
              sticks: bool = True) -> str:
    """Frame 17's menu; with `research_on`, the Research row as frame 22 shows
    it after the press: aria-checked, data-checked and the ✓ glyph.

    `testid=False` takes the row's test id off (the row must still be found by
    its text past the icon glyph); `sticks=False` makes a press that closes the
    menu and changes nothing (a press that did not take)."""
    wrap = json.loads(json.dumps(frame(M, 17)["menus"][0]))
    row = _find(wrap, lambda x: x.get("a", {}).get("data-testid") == "add-menu-research")
    assert row is not None
    row["a"]["data-sr-research-row"] = ""
    if not testid:
        row["a"].pop("data-testid")
    if not sticks:
        row["a"]["data-sr-inert"] = ""
    if research_on:
        row["a"].pop("data-unchecked", None)
        row["a"].update({"data-checked": "", "aria-checked": "true"})
    return render(wrap, attrs={"id": "sr-plus-menu", "class": "sr-pop", "hidden": ""})


def copy_menu() -> str:
    wrap = frame(R, 90)["menus"][0]
    assert _find(wrap, lambda x: x.get("a", {}).get("data-testid") == "export-download")
    return render(wrap, attrs={"id": "sr-copy-menu", "class": "sr-pop sr-copy",
                               "hidden": ""})


def sidebar() -> str:
    aside = frame(R, 20)["panels"][0]
    assert aside["a"].get("aria-label") == "Sidebar"
    body = render(aside, attrs={"id": "sr-sidebar"})
    # ASSUMED: two rows the 09-30 run saved as Claude "steps" (the capture's
    # recents section is cut at depth 11 and carries neither label).
    extra = ('<div data-sr-assumed="09-30 steps"><div data-row>Chats and tasks'
             '</div><div data-row>\ue0bd<span>Pin projects to keep them here</span>'
             '</div></div>')
    return body.replace("</aside>", extra + "</aside>")


def turn(finished: bool) -> str:
    t = frame(R, 91 if finished else 24)["lastTurn"][0]
    assert t["a"].get("data-testid") == "assistant-message"
    return render(t)


def stop_button() -> str:
    a = frame(R, 26)["stopButtons"][0]["a"]
    assert a["aria-label"] == "Stop response"
    return render({"tag": "BUTTON", "a": a, "label": "\ue0a9"},
                  attrs={"id": "sr-stop"}, drop=("class",))


# ── the parts no frame records (ASSUMED, see the module docstring) ──────────

RESEARCH_ROWS = (("royalcanin.com", "19 sources"), ("petsmart.com", "11 sources"))
RESEARCH_ROWS_2 = (("petsmart.com", "42 sources"), ("royalcanin.com", "2 sources"))


def _rows_button(rows) -> str:
    items = "".join(
        f'<div class="flex items-center text-xs text-secondary">'
        f'<img alt=""><p>{h}</p><span>{n}</span></div>'
        for h, n in rows)
    return ('<button class="transition-all w-full flex flex-col">'
            f'<div class="flex flex-col gap-2.5 my-1">{items}</div></button>')


def research_panel() -> str:
    """The region and the list ancestry are captured (frames 49, 63, 71); the
    step titles and the rows' count text are ASSUMED."""
    def step(title, rows):
        return (
            '<li class="flex flex-row gap-3 min-h-[2.125rem]"><div class="w-full flex flex-col">'
            f'<div class="sr-step">{title}</div>'
            '<div tabindex="-1" class="overflow-hidden shrink-0"><div class="min-h-0">'
            '<div tabindex="-1" class="min-h-0 overflow-y-auto overflow-x-hidden scroll-fade-y">'
            f'<div class="flex flex-col pt-4 pb-6">{_rows_button(rows)}</div></div></div></div>'
            '</div></li>')
    return (
        '<div data-drawer-slot="" class="flex-1 overflow-hidden h-full bg-surface-1">'
        '<div tabindex="-1" role="region" aria-label="Research panel" '
        'class="relative h-full w-full bg-surface-3" id="sr-research-panel">'
        '<div class="flex flex-col h-full bg-surface-3">'
        '<div class="shrink-0 flex items-center justify-between">'
        '<div>Large-breed dog food comparison</div>'
        '<button type="button" data-cds="Button" data-cds-icon-only="" '
        'aria-label="Close">\ue10f</button></div>'
        '<ol role="list" class="flex flex-col overflow-y-auto px-5">'
        + step("Searching for large-breed dog food brand comparisons", RESEARCH_ROWS)
        + step("Reading veterinary nutrition guidance for giant breeds", RESEARCH_ROWS_2)
        + '</ol></div></div></div>')


REPORT_MD = (
    "# Large-Breed Dog Food: Purina Pro Plan vs. Hill's Science Diet vs. Royal Canin\n\n"
    "## TL;DR\n\n"
    "Large and giant breeds need controlled calcium and energy during growth, and all "
    "three brands formulate for that. The differences that matter are the protein "
    "level, the kibble size and what the dog actually eats well over months.\n\n"
    "## Growth and joints\n\n"
    "Puppies of large breeds grow for 12 to 24 months. Diets for them keep calcium "
    "near the lower end of the allowed range and limit energy density, which slows "
    "growth without stunting it. Adult formulas add glucosamine in small amounts.\n\n"
    "## Protein and energy\n\n"
    "Active adults do well on 26 to 30 percent protein; less active or older dogs need "
    "less energy and benefit from a lower-fat formula to keep a lean body condition.\n\n"
    "## Sources\n\n"
    "1. [Large breed puppy nutrition](https://www.royalcanin.com/us/dogs/puppy/large)\n"
    "2. [Pro Plan large breed](https://www.purina.com/pro-plan/dogs/large-breed)\n")


def report_panel() -> str:
    """The region and the Copy split button are captured (frame 89); the Copy
    half of the split button and the report body are ASSUMED."""
    opts = _clicked(R, 89, "BUTTON")                    # "Copy options"
    assert opts["a"]["aria-label"] == "Copy options"
    body = "".join(f"<p>{html.escape(line)}</p>"
                   for line in REPORT_MD.splitlines() if line.strip())
    return (
        '<div data-drawer-slot="" class="flex-1 overflow-hidden h-full bg-surface-1">'
        '<div class="relative h-full">'
        '<div tabindex="-1" role="region" id="sr-report-panel" '
        'aria-label="Artifact panel: Large-Breed Dog Food: Purina Pro Plan vs. '
        'Hill&#x27;s Science Diet vs" class="bg-surface-3 flex h-full flex-col">'
        '<div class="pr-2 pl-3 flex items-center"><div class="flex gap-2 items-center">'
        '<div data-cds="SplitDropdownButton" role="group" aria-label="Copy" data-size="sm" '
        'class="relative inline-flex w-fit shrink-0">'
        '<div data-cds-segment="" class="contents"><button type="button">Copy</button></div>'
        '<div data-cds-segment="" class="contents">'
        + render(opts, attrs={"aria-expanded": "false", "id": "sr-copy-options"},
                 drop=("data-popup-open", "data-pressed", "class"))
        + '</div></div></div></div>'
        f'<div class="standard-markdown">{body}</div></div></div></div>')


_CSS = """
html, body { margin: 0; font: 14px sans-serif; background: #fff; }
#sr-sidebar-slot { position: fixed; left: 0; top: 0; width: 288px; height: 100vh;
                   overflow: hidden; }
#sr-main { position: absolute; left: 300px; top: 0; width: 400px; }
#sr-panel-slot { position: fixed; right: 0; top: 0; width: 560px; height: 100vh;
                 overflow: auto; background: #eee; }
#sr-panel-slot:empty { display: none; }
.sr-pop { position: fixed; left: 320px; top: 120px; width: 300px; background: #fafafa;
          border: 1px solid #999; z-index: 10; }
.sr-pop2 { left: 630px; }
.sr-copy { left: 760px; top: 60px; }
[hidden] { display: none !important; }
fieldset { border: 1px solid #ccc; margin: 10px 0; }
/* The report card: the capture's button is `absolute inset-0` over its block
   (box 519×70, capture 2 frame 91). */
[data-sheet-kind] { position: relative; min-height: 70px; width: 380px; }
button[data-testid="artifact-card-open"] { position: absolute; inset: 0; }
"""

# ASSUMED behaviour, written to the before/after states the frames show.
_JS = r"""
(() => {
  const $ = s => document.querySelector(s);
  const $$ = s => [...document.querySelectorAll(s)];
  // The press log lives in the DOM: patchright evaluates in an isolated world,
  // which shares the document but not this script's globals.
  const presses = [];
  const note = (what, e) => {
    presses.push({what, trusted: !!(e && e.isTrusted)});
    document.documentElement.setAttribute('data-sr-presses', JSON.stringify(presses));
  };
  document.documentElement.setAttribute('data-sr-presses', '[]');
  const show = (el, on) => { if (el) { if (on) el.removeAttribute('hidden'); else el.setAttribute('hidden', ''); } };
  const trig = () => $('#sr-model-trigger');
  const setTier = (label) => {
    const t = trig();
    t.setAttribute('aria-label', 'Model: Opus 5.5 ' + label);
    t.textContent = 'Opus 5.5 ' + label;
    const row = $('#sr-effort-row');
    if (row) {
      const v = [...row.querySelectorAll('span')].find(s => /^(Low|Medium|High|Extra|Max)$/.test(s.textContent.trim()));
      if (v) v.textContent = label;
    }
    $$('[data-effort-id]').forEach(r => {
      const on = r.getAttribute('data-effort-id') === ({Low:'low',Medium:'medium',High:'high',Extra:'xhigh',Max:'max'})[label];
      r.setAttribute('aria-checked', on ? 'true' : 'false');
    });
  };
  // A tier moved by hand (the owner on 09-30): dispatched as a DOM event.
  document.addEventListener('sr-set-tier', e => setTier(String(e.detail)));
  const closeModel = () => { show($('#sr-effort-menu'), false); show($('#sr-model-menu'), false);
                             trig().setAttribute('aria-expanded', 'false');
                             $('#sr-effort-row') && $('#sr-effort-row').setAttribute('aria-expanded', 'false'); };
  const openEffort = () => { show($('#sr-effort-menu'), true); $('#sr-effort-row').setAttribute('aria-expanded', 'true'); };
  document.addEventListener('click', e => {
    const t = e.target;
    if (t.closest('#sr-model-trigger')) {
      note('model-button', e);
      const open = $('#sr-model-menu').hasAttribute('hidden');
      if (open) { show($('#sr-model-menu'), true); trig().setAttribute('aria-expanded', 'true'); }
      else closeModel();
      return;
    }
    if (t.closest('#sr-effort-row')) { note('effort-row', e); openEffort(); return; }
    const opt = t.closest('[data-effort-id]');
    if (opt) {
      note('effort:' + opt.getAttribute('data-effort-id'), e);
      const label = ({low:'Low',medium:'Medium',high:'High',xhigh:'Extra',max:'Max'})[opt.getAttribute('data-effort-id')];
      setTier(label); closeModel(); return;
    }
    if (t.closest('#sr-plus')) {
      note('plus', e);
      const m = $('#sr-plus-menu'); const open = m.hasAttribute('hidden');
      show(m, open); $('#sr-plus').setAttribute('aria-expanded', open ? 'true' : 'false'); return;
    }
    const rr = t.closest('[data-sr-research-row]');
    if (rr) {
      note('research-row', e);
      if (rr.hasAttribute('data-sr-inert')) {
        show($('#sr-plus-menu'), false); $('#sr-plus').setAttribute('aria-expanded', 'false'); return;
      }
      const on = rr.getAttribute('aria-checked') !== 'true';
      rr.setAttribute('aria-checked', on ? 'true' : 'false');
      if (on) { rr.setAttribute('data-checked', ''); rr.removeAttribute('data-unchecked'); }
      else { rr.setAttribute('data-unchecked', ''); rr.removeAttribute('data-checked'); }
      show($('#sr-research-pill'), on);
      show($('#sr-plus-menu'), false); $('#sr-plus').setAttribute('aria-expanded', 'false'); return;
    }
    const card = t.closest('button[aria-label$="Open research panel."]');
    if (card) {
      note('research-card', e);
      setTimeout(() => { $('#sr-panel-slot').innerHTML = window.__sr_research_panel; }, 2000);
      return;
    }
    const rep = t.closest('button[data-testid="artifact-card-open"]');
    if (rep) {
      note('report-card', e);
      rep.setAttribute('aria-pressed', 'true');
      $('#sr-panel-slot').innerHTML = window.__sr_report_panel; return;
    }
    if (t.closest('#sr-copy-options')) {
      note('copy-options', e);
      const m = $('#sr-copy-menu'); show(m, m.hasAttribute('hidden')); return;
    }
    const dl = t.closest('[data-testid="export-download"]');
    if (dl) {
      e.preventDefault();
      note('download-md', e);
      const a = document.createElement('a');
      a.href = URL.createObjectURL(new Blob([window.__sr_report_md], {type: 'text/markdown'}));
      a.download = 'large-breed-dog-food.md';
      document.body.appendChild(a); a.click(); a.remove();
      show($('#sr-copy-menu'), false); return;
    }
    const tb = t.closest('button');
    if (tb) note('button:' + (tb.getAttribute('aria-label') || tb.textContent.trim()).slice(0, 40), e);
  }, true);
  document.addEventListener('mouseover', e => {
    if (e.target.closest && e.target.closest('#sr-effort-row') && !$('#sr-model-menu').hasAttribute('hidden')) openEffort();
  }, true);
  document.addEventListener('keydown', e => {
    if (e.key !== 'Escape') return;
    if (!$('#sr-effort-menu').hasAttribute('hidden')) { show($('#sr-effort-menu'), false); return; }
    if (!$('#sr-model-menu').hasAttribute('hidden')) { closeModel(); return; }
    if (!$('#sr-plus-menu').hasAttribute('hidden')) { show($('#sr-plus-menu'), false); return; }
    if (!$('#sr-copy-menu').hasAttribute('hidden')) { show($('#sr-copy-menu'), false); return; }
  }, true);
})();
"""


def page(*, tier: str = "Medium", finished: bool = False, running: bool = False,
         research_on: bool = False, panel: str = "", research_testid: bool = True,
         research_sticks: bool = True) -> str:
    """The whole page. `panel` is "", "research" or "report" (open at load)."""
    pill = ('<button type="button" id="sr-research-pill" aria-label="Research" '
            'aria-pressed="true"' + ("" if research_on else " hidden") + '>\ue0d0</button>')
    composer = (
        '<fieldset data-cds-dock-group="" data-perf-region="composer" id="sr-composer">'
        '<div data-cds="ChatComposer"><div class="relative w-full min-w-0">'
        # ASSUMED: the text box (the capture's composer is cut above it).
        '<div contenteditable="true" role="textbox" class="ProseMirror" '
        'aria-label="Write your prompt to Claude"><p><br></p></div>'
        '<div data-cds="ChatComposerActions"><div class="flex items-center">'
        + plus_button() + pill + '</div><div class="flex items-center gap-2">'
        + model_button(tier) + (stop_button() if running else "")
        + '</div></div></div></div></fieldset>')
    menus = (model_popover(tier.lower()) + effort_submenu()
             + plus_menu(research_on, testid=research_testid, sticks=research_sticks)
             + copy_menu())
    slot = {"research": research_panel(), "report": report_panel()}.get(panel, "")
    data = ("<script>"
            f"window.__sr_research_panel = {json.dumps(research_panel())};"
            f"window.__sr_report_panel = {json.dumps(report_panel())};"
            f"window.__sr_report_md = {json.dumps(REPORT_MD)};"
            "</script>")
    body = (f'<div id="sr-sidebar-slot">{sidebar()}</div>'
            f'<div id="sr-main"><div role="feed" aria-label="Chat messages">'
            f'{turn(finished) if (finished or running) else ""}</div>{composer}</div>'
            f'<div id="sr-panel-slot">{slot}</div>{menus}')
    return ('<!doctype html><html><head><meta charset="utf-8">'
            f'<style>{_CSS}</style></head><body>{body}{data}<script>{_JS}</script>'
            '</body></html>')
