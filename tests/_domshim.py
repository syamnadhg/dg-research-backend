"""A dependency-free DOM shim for executing the pipeline's page JS under node.

Why this exists: several real defects have been pure SELECTOR-SEMANTICS bugs — a
`querySelector` with a comma list returning the first match in document order rather
than the earlier selector's match (the Gemini Recent-vs-Notebooks expander), or a
selector set that simply has no member capable of matching the live markup (Claude's
"Sources and activity" toolbar toggle). Source-text assertions, which is what this
repo has historically used for page JS, cannot catch either class. Running the actual
JS against the markup recorded in the failing logs can.

Hand-rolled rather than jsdom on purpose: a real npm dependency would put the backend
test suite behind an `npm install` and a node_modules tree.

Supports what the production selectors actually use: tag names, `[attr]`,
`[attr="v"]`, `[attr*="v" i]`, comma selector lists, descendant combinators,
`textContent`/`innerText`, attribute reads, `getBoundingClientRect`, `closest`, and a
click that records what was clicked.
"""

from __future__ import annotations

import ast
import inspect
import json
import shutil
import subprocess
import textwrap

NODE = shutil.which("node")


def _string_literals(fn):
    """Every str constant in `fn`, as the VALUES Python produces — not source text."""
    return ast.parse(textwrap.dedent(inspect.getsource(fn)))


def evaluate_js(fn, *, contains: str = "") -> str:
    """The actual JS string `fn` hands to `page.evaluate(...)`.

    Parsed via ast and taken as a literal VALUE rather than regex-scraped from the
    source. This distinction is not cosmetic: the source text of a non-raw Python
    string shows `\\\\s`, while the string Playwright receives has `\\s`. Scraping the
    source hands node a literal backslash-s, so every character class in the selector
    logic silently stops matching and the test passes or fails for the wrong reason.
    """
    hits = []
    for node in ast.walk(_string_literals(fn)):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "evaluate" and node.args):
            arg = node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                if not contains or contains in arg.value:
                    hits.append(arg.value)
    assert hits, f"no page.evaluate(<literal>) in {fn.__name__} matching {contains!r}"
    assert len(hits) == 1, f"{len(hits)} candidate evaluate() strings in {fn.__name__}"
    return hits[0]


def js_constant(fn, name: str) -> str:
    """The value of a `name = \"\"\"...\"\"\"` JS constant assigned inside `fn`."""
    for node in ast.walk(_string_literals(fn)):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == name:
                    return node.value.value
    raise AssertionError(f"{name} not found in {fn.__name__}")

SHIM = r"""
const CLICKS = [];
class El {
  constructor(tag, attrs, text, kids) {
    this.tagName = String(tag).toUpperCase();
    this._attrs = attrs || {}; this._text = text || ''; this.children = kids || [];
    this.parent = null;
    for (const k of this.children) k.parent = this;
  }
  getAttribute(n) { return (n in this._attrs) ? this._attrs[n] : null; }
  // Production MARKS an element it has identified in JS so Playwright can aim a
  // real, trusted click at it — the search has to happen in JS (ordered hooks,
  // safety exclusions) while the press has to happen in the browser. Without
  // these the marking JS throws and the test reads as a broken selector.
  setAttribute(n, v) { this._attrs[n] = String(v); }
  removeAttribute(n) { delete this._attrs[n]; }
  hasAttribute(n) { return n in this._attrs; }
  get textContent() { return this._text + this.children.map(c => c.textContent).join(''); }
  get innerText() { return this.textContent; }
  // Own text vs descendant text is a DISTINCTION production depends on: a
  // Material dropdown parks its open option list INSIDE the trigger, so reading
  // innerText on the trigger finds "Anyone with the link" in a row nobody
  // selected. The share-dialog checks therefore walk childNodes and take only
  // TEXT_NODEs. Without this the shim reported every element as having no own
  // text, so an already-public trigger and a restricted one looked identical.
  get childNodes() {
    const out = [];
    if (this._text) out.push({ nodeType: 3, nodeValue: this._text });
    for (const k of this.children) out.push(k);
    return out;
  }
  get nodeType() { return 1; }
  get classList() {
    const cls = String(this._attrs['class'] || '').split(/\s+/);
    return { contains: (c) => cls.includes(c) };
  }
  get className() { return this._attrs['class'] || ''; }
  click() { CLICKS.push(this.getAttribute('aria-label') || this.textContent || this.tagName); }
  // `x`/`y` place the box. They default to 10,10 (on-screen) so every existing
  // fixture keeps its old geometry, and they exist because "on screen" is not a
  // question a size can answer: NotebookLM parks a full-size button at x=-36,
  // where a rect-size gate and offsetParent both say clickable and it is not.
  getBoundingClientRect() {
    const w = 'w' in this._attrs ? +this._attrs.w : 100;
    const h = 'h' in this._attrs ? +this._attrs.h : 24;
    const x = 'x' in this._attrs ? +this._attrs.x : 10;
    const y = 'y' in this._attrs ? +this._attrs.y : 10;
    return { width: w, height: h, left: x, top: y, right: x + w, bottom: y + h };
  }
  getClientRects() { return [this.getBoundingClientRect()]; }
  // The other visibility idiom in this codebase. Production JS uses BOTH
  // `getClientRects().length` and `!el.offsetParent` as its "is this on screen"
  // gate, and a shim that left offsetParent undefined made every element read
  // as hidden — so the model rankers, which gate on it first, would skip every
  // row and "pass" a test by selecting nothing. Root has no parent, matching
  // the browser (a detached or display:none node has none either); mark a node
  // `hidden` to simulate that for a node that does have one.
  // Hiding PROPAGATES, as it does in a browser: a node inside a hidden subtree
  // has no offsetParent either. Without that, a fixture could hide a container
  // and its rows would still read as on-screen.
  get offsetParent() {
    for (let n = this; n; n = n.parent) if (n.getAttribute('hidden') !== null) return null;
    return this.parent;
  }
  dispatchEvent() { CLICKS.push(this.getAttribute('aria-label') || this.textContent || this.tagName); return true; }
  descendants() { return this.children.flatMap(c => [c, ...c.descendants()]); }
  matches(sel) {
    return sel.split(',').map(s => s.trim()).filter(Boolean).some(p => matchOne(this, p));
  }
  closest(sel) {
    let n = this;
    while (n) { if (n.matches(sel)) return n; n = n.parent; }
    return null;
  }
  querySelectorAll(sel) { return this.descendants().filter(e => e.matches(sel)); }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
}
// Descendant combinators are load-bearing: production gates on things like
// `conversations-list a[href*="/app/"]` (scoped on purpose). A shim that ignored the
// combinator would make those gates unreachable and the tests meaningless.
// Split on whitespace only OUTSIDE brackets — `[class*="sidebar" i]` carries a
// space before the case-insensitivity flag, and a naive /\s+/ split shreds it.
function splitChain(p) {
  const out = []; let buf = '', depth = 0;
  for (const ch of p) {
    if (ch === '[') depth++;
    else if (ch === ']') depth--;
    if (depth === 0 && /\s/.test(ch)) { if (buf) { out.push(buf); buf = ''; } continue; }
    buf += ch;
  }
  if (buf) out.push(buf);
  return out;
}
function matchOne(el, p) {
  const chain = splitChain(p);
  if (chain.length > 1) {
    if (!matchSimple(el, chain[chain.length - 1])) return false;
    let i = chain.length - 2, node = el.parent;
    while (node && i >= 0) { if (matchSimple(node, chain[i])) i--; node = node.parent; }
    return i < 0;
  }
  return matchSimple(el, p);
}
function matchSimple(el, p) {
  // The universal selector. Production reaches for it when it has to walk a
  // container it cannot name a tag for — the NotebookLM "Generating Audio
  // Overview…" placeholder, whose tag is not in any capture. Without this the
  // shim returned zero matches for `*`, which reads exactly like a selector
  // that cannot match and would let a broken counter pass.
  if (p === '*') return true;
  // Tag + any mix of .class / #id / [attr] — `.font-claude-message` scoping is
  // load-bearing in the Claude artifact path (pass 1 is assistant-scoped), so a shim
  // that silently failed every class selector would take the wrong branch.
  const m = p.match(/^([a-zA-Z-]*)((?:[.#][A-Za-z0-9_-]+|\[[^\]]*\])*)$/);
  if (!m) return false;
  if (m[1] && el.tagName !== m[1].toUpperCase()) return false;
  for (const cls of (m[2].match(/\.[A-Za-z0-9_-]+/g) || [])) {
    if (!el.classList.contains(cls.slice(1))) return false;
  }
  for (const id of (m[2].match(/#[A-Za-z0-9_-]+/g) || [])) {
    if (el.getAttribute('id') !== id.slice(1)) return false;
  }
  for (const raw of (m[2].match(/\[[^\]]*\]/g) || [])) {
    const am = raw.slice(1, -1).match(/^([a-zA-Z-]+)(?:([*^$]?)=\s*"([^"]*)"\s*(i)?)?$/);
    if (!am) return false;
    const v = el.getAttribute(am[1]);
    if (v === null) return false;
    if (am[3] === undefined) continue;
    const hay = am[4] ? String(v).toLowerCase() : String(v);
    const need = am[4] ? am[3].toLowerCase() : am[3];
    // Full operator set — production uses *= and ^= (the "View <title>" prefix
    // match); a shim that silently treated ^= as equality would report zero hits
    // and look exactly like a broken selector.
    if (am[2] === '*') { if (!hay.includes(need)) return false; }
    else if (am[2] === '^') { if (!hay.startsWith(need)) return false; }
    else if (am[2] === '$') { if (!hay.endsWith(need)) return false; }
    else if (hay !== need) return false;
  }
  return true;
}
// `repeat` expands one child spec into N siblings. Production carries an
// 8000-node ceiling above which the ChatGPT panel walk abandons a root
// unscanned, and a fixture that has to CROSS that ceiling cannot be shipped
// node-by-node — the JSON would be a 400 KB argv, near the OS limit. Expanding
// inside node keeps the payload small and the fixture honest.
function build(spec) {
  const attrs = {};
  for (const [k, v] of Object.entries(spec.attrs || {})) if (v !== null) attrs[k] = v;
  const kids = [];
  for (const k of (spec.kids || [])) {
    for (let i = 0; i < (k.repeat || 1); i++) kids.push(build(k));
  }
  return new El(spec.tag, attrs, spec.text || '', kids);
}
let ROOT = null;
globalThis.document = {
  querySelectorAll: (s) => ROOT.querySelectorAll(s),
  querySelector: (s) => ROOT.querySelector(s),
  // `document.body` is the picker's fallback root for "no menu has mounted
  // yet". Without it that branch throws instead of exercising the fallback.
  get body() { return ROOT; },
};
globalThis.getComputedStyle = () => ({ display: 'block', visibility: 'visible', opacity: '1' });
globalThis.window = { innerWidth: 1440, innerHeight: 900 };
globalThis.PointerEvent = class { constructor(t) { this.type = t; } };
globalThis.MouseEvent = class { constructor(t) { this.type = t; } };
globalThis.__run = (spec, fn, arg) => {
  ROOT = build(spec);
  const ret = arg === undefined ? fn() : fn(arg);
  return { ret, clicks: CLICKS };
};
"""


def el(tag, attrs=None, text="", kids=None, repeat=1):
    """Build a DOM spec node. `w`/`h` attrs set the bounding box.

    `repeat` clones this node into N identical siblings when it is built — for
    fixtures that must exceed a production node ceiling.
    """
    spec = {"tag": tag, "attrs": attrs or {}, "text": text, "kids": kids or []}
    if repeat != 1:
        spec["repeat"] = repeat
    return spec


def run_js(spec, fn_src: str, arg=None) -> dict:
    """Run `fn_src` (a JS arrow/function expression) against `spec`.

    Returns {"ret": <return value>, "clicks": [labels...]}.
    """
    if NODE is None:
        raise RuntimeError("node is required to run page JS")
    payload = json.dumps(spec)
    argjs = "undefined" if arg is None else json.dumps(arg)
    js = (SHIM + "\nconsole.log(JSON.stringify(__run("
          + payload + ", " + fn_src.strip() + ", " + argjs + ")));\n")
    p = subprocess.run([NODE, "-e", js], capture_output=True, text=True, timeout=60)
    if p.returncode != 0:
        raise AssertionError(f"node failed: {p.stderr}")
    return json.loads(p.stdout.strip().splitlines()[-1])
