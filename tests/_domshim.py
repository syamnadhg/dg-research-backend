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
`getComputedStyle` driven by `anim`/`clip` attributes,
`textContent`/`innerText`, attribute reads, `getBoundingClientRect`, `closest`,
`getAnimations()` (element and document), and a click that records what was clicked.
"""

from __future__ import annotations

import ast
import inspect
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
from html.parser import HTMLParser

NODE = shutil.which("node")

# Elements that never have children or a closing tag. Pushing one onto the stack
# would swallow every following sibling as its child, which silently changes
# `childElementCount` — the exact property the panel's leaf scan branches on.
_VOID_TAGS = frozenset({
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
})


class _SpecBuilder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._root = {"tag": "div", "attrs": {}, "text": "", "kids": []}
        self._stack = [self._root]

    def handle_starttag(self, tag, attrs):
        node = {"tag": tag, "attrs": {k: ("" if v is None else v) for k, v in attrs},
                "text": "", "kids": []}
        self._stack[-1]["kids"].append(node)
        if tag not in _VOID_TAGS:
            self._stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self._stack[-1]["kids"].append(
            {"tag": tag, "attrs": {k: ("" if v is None else v) for k, v in attrs},
             "text": "", "kids": []})

    def handle_endtag(self, tag):
        # Walk back to the nearest matching open tag. A stray close tag (common in
        # a truncated capture) must not pop an unrelated ancestor.
        for i in range(len(self._stack) - 1, 0, -1):
            if self._stack[i]["tag"] == tag:
                del self._stack[i:]
                return

    def handle_data(self, data):
        if data.strip():
            self._stack[-1]["text"] += data

    def result(self):
        kids = self._root["kids"]
        return kids[0] if len(kids) == 1 else self._root


def spec_from_html(html: str) -> dict:
    """Turn captured markup into a shim spec, so a REAL capture can be replayed
    through the real page JS.

    Why this exists: the panel-counts defect could not be diagnosed from the
    repository, because the activity panel only exists while a phase is in
    flight. The run now writes the panel's markup to disk mid-flight, and this is
    what lets a test execute the production extractor against that document
    instead of against a fixture someone hand-built to match their own theory of
    the markup. A hand-built fixture can only confirm what its author already
    believed.

    Two honest limitations, both irrelevant to counting and both worth knowing
    before trusting this for something else:

    * Text interleaved between child elements is collected onto the parent, so a
      node's own text always precedes its children's. `textContent` and the
      block-aware `innerText` still aggregate correctly; only the ORDER of a
      parent's own text relative to its children is lost.
    * A truncated capture parses as far as it can. Unclosed tags are closed at
      EOF, so the tail of the tree is shallower than the real page — which means
      counts read off a truncated document are FLOORS. Check the capture is whole
      before treating any number from it as exact.
    """
    p = _SpecBuilder()
    p.feed(html)
    p.close()
    return p.result()


def _string_literals(fn):
    """The parsed AST of `fn`, for callers that walk it looking for str constants.

    ⚠ Returns the TREE, not the literals — the name is historical. `js_constant`
    and `evaluate_js` each do their own walk and read `ast.Constant` values, and
    that is where the property this helper exists for comes from: a constant read
    off the tree is the VALUE Python produces, with escapes already resolved,
    rather than the source text between the quotes. Reading the source text is
    what makes a JS payload full of backslashes impossible to match reliably.
    """
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
    """The value of a `name = \"\"\"...\"\"\"` JS constant assigned inside `fn`.

    ⭐ 2026-08-05 — a COMPOSED constant resolves to its runtime value. The ChatGPT row
    JS is now `r\"\"\"…\"\"\" + _CHATGPT_ROW_FILTER_JS + r\"\"\"…\"\"\"`, because the read and
    the click must embed one shared filter rather than two copies that happen to agree
    (the copies not agreeing is what let a sidebar conversation link be pressed on
    2026-08-05). The AST walk below only ever matched a bare `ast.Constant`, so every
    test that fed one of those constants to node started failing with "not found" —
    which reads exactly like a renamed constant rather than a changed shape.

    A module attribute is preferred when `fn` is a module and carries the name: that is
    the value production actually hands to `page.evaluate`, escapes and concatenation
    already resolved. The AST walk stays for constants assigned INSIDE a function,
    where there is no attribute to read.

    ⭐⭐ 2026-08-19 — AND IT NOW FOLDS THAT CONCATENATION FOR IN-FUNCTION CONSTANTS
    TOO, which is what the paragraph above only half delivered. When
    `_CHATGPT_SHIMMER_JS_HELPERS` was extracted so three walkers could share one
    definition of "shimmering", the picker's `JS = \"\"\"…\"\"\" + _CHATGPT_SHIMMER_JS_HELPERS
    + \"\"\"…\"\"\"` stopped being an `ast.Constant` and eleven anchor tests failed with
    "JS not found" — a message that reads like a renamed constant and has nothing to
    do with the change. The shim's own rule applies to the shim: it only proves
    something if it answers the way the real thing does, and production evaluates
    the concatenation. `Name` operands are resolved against the module that defines
    `fn`, so a shared constant is spliced here exactly as `page.evaluate` sees it.
    """
    if isinstance(getattr(fn, name, None), str):
        return getattr(fn, name)
    owner = sys.modules.get(getattr(fn, "__module__", "") or "")

    def _fold(node):
        """The assigned value as a string, or None when it is not string-shaped."""
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left, right = _fold(node.left), _fold(node.right)
            return None if left is None or right is None else left + right
        if isinstance(node, ast.Name):
            # A module-level JS fragment shared between call sites. Resolved from
            # the live module rather than re-parsed, so escapes match production.
            val = getattr(owner, node.id, None)
            return val if isinstance(val, str) else None
        return None

    for node in ast.walk(_string_literals(fn)):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            continue
        folded = _fold(node.value)
        if folded is not None:
            return folded
        raise AssertionError(
            f"{name} in {getattr(fn, '__name__', fn)} is assigned something this "
            f"shim cannot resolve to a string ({type(node.value).__name__}) — a "
            f"test fed it to node and would have measured nothing")
    raise AssertionError(f"{name} not found in {getattr(fn, '__name__', fn)}")

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
  // ⭐ 2026-08-05 — `disabled` REFLECTS as a boolean PROPERTY on form controls,
  // and production reads `el.disabled`, never getAttribute('disabled'). Without
  // this getter the property was always undefined, so a fixture marking a button
  // disabled read as enabled and a "disabled controls are skipped" test passed
  // whether or not the check existed. A fixture only proves something if it
  // answers the way the real thing does.
  //
  // HTML semantics, deliberately: the ATTRIBUTE'S PRESENCE is what disables —
  // `disabled="false"` is still disabled in a browser. `aria-disabled` is the
  // opposite (a string that must equal "true"), and production tests it
  // separately for exactly that reason.
  get disabled() { return 'disabled' in this._attrs; }
  // ⭐ 2026-08-06 — `dataset` was missing entirely, and production reads
  // `el.dataset.state` to decide whether a menu row is already selected. Any JS
  // reaching that line threw `Cannot read properties of undefined`, so the branch
  // was unreachable under the shim and no test could cover it — the Claude effort
  // picker had never been executed here at all. Mirrors the browser: `data-*`
  // becomes camelCase, and a missing attribute reads `undefined` rather than
  // throwing.
  get dataset() {
    const out = {};
    for (const [k, v] of Object.entries(this._attrs)) {
      if (!k.startsWith('data-')) continue;
      out[k.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = v;
    }
    return out;
  }
  get textContent() { return this._text + this.children.map(c => c.textContent).join(''); }
  // ⭐ 2026-08-06 — production captures a panel with `panel.outerHTML` and then
  // reports how much of it it retained. Without this getter that read was `''`,
  // the reported full length was 0, and a test replaying a real capture could not
  // see the truncation AT ALL — the same silent-truncation failure the production
  // fix was written for, reproduced inside the harness meant to catch it.
  // Attribute order follows insertion, which is what a browser does too.
  get outerHTML() {
    const attrs = Object.entries(this._attrs)
      .map(([k, v]) => ' ' + k + '="' + String(v).replace(/"/g, '&quot;') + '"').join('');
    const tag = this.tagName.toLowerCase();
    return '<' + tag + attrs + '>' + this._text
      + this.children.map(c => c.outerHTML).join('') + '</' + tag + '>';
  }
  // ⭐ 2026-08-05 — `innerText` is LINE-AWARE in a browser; `textContent` is not.
  // The shim returned the concatenation for both, and that silently disarmed every
  // production regex anchored on a word boundary or a line. Measured case: the
  // ChatGPT panel renders "Searching 1 website" and "14 more" in sibling divs, and
  // the source-count regex is /(\d+)\s+(?:websites?|…)\b/ — against the concatenated
  // "…1 websitedocs.nvidia.com…" the trailing \b cannot match, so the count came back
  // 0 and a test asserting "we read the source count" would pass against an
  // extraction that reads nothing.
  //
  // Block-level children get a newline between them, inline ones do not — the same
  // distinction the browser makes, and the one the regexes were written against.
  get innerText() {
    const BLOCK = new Set(['DIV', 'P', 'SECTION', 'ARTICLE', 'LI', 'UL', 'OL', 'TR',
                           'TD', 'TH', 'H1', 'H2', 'H3', 'H4', 'H5', 'H6', 'HEADER',
                           'FOOTER', 'NAV', 'ASIDE', 'MAIN', 'FORM', 'FIGURE',
                           'BLOCKQUOTE', 'PRE', 'HR', 'BR', 'TABLE', 'DL', 'DT', 'DD']);
    let s = this._text;
    for (const c of this.children) {
      const t = c.innerText;
      if (BLOCK.has(c.tagName)) { if (s && !s.endsWith('\n')) s += '\n'; s += t + '\n'; }
      else s += t;
    }
    return s;
  }
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
  // Production reads it on the panel fingerprint and on the leaf test in the
  // activity walker; without it both were `undefined`, which compares false
  // against every number and silently made a leaf filter reject everything.
  get childElementCount() { return this.children.length; }
  get classList() {
    const cls = String(this._attrs['class'] || '').split(/\s+/);
    return { contains: (c) => cls.includes(c) };
  }
  get className() { return this._attrs['class'] || ''; }
  // ⭐ 2026-08-05 — `a.href` is a resolved-URL PROPERTY in a browser, and production
  // reads the property (`const h = a.href || ''`) rather than the attribute. Without
  // this it was undefined, so every source-URL walk in the codebase collected NOTHING
  // against a fixture full of anchors — and a "we extract the panel's sources" test
  // would pass whether or not the extraction worked. Fixtures here carry absolute
  // hrefs, so returning the attribute is the resolved value.
  get href() { return this._attrs['href'] || ''; }
  get title() { return this._attrs['title'] || ''; }
  click() { CLICKS.push(this.getAttribute('aria-label') || this.textContent || this.tagName); }
  // ⭐⭐ 2026-08-19 — THE WEB ANIMATIONS API, which this shim had no answer for
  // at all. Every "is it still generating" probe in this repo ends at
  // `el.getAnimations().some(a => a.playState === 'running')`, deliberately:
  // a browser leaves `animationName` set on an element whose animation already
  // FINISHED, so the computed style cannot tell a live spinner from dead chrome
  // (the 2026-05-14 note on those probes says exactly this). Without this
  // method every such probe threw `getAnimations is not a function` under the
  // shim, so the tier could not be executed and only source text could be
  // asserted about it — which is how a tier that matched CLASS names while
  // Gemini animates by NAME survived two years of green tests.
  //
  // Driven by the same `anim` attribute `getComputedStyle` already reads, so one
  // fixture describes both views of the element. `playstate` defaults to
  // "running"; set `playstate="finished"` to express the persisted-but-dead
  // animation these probes exist to reject. `effect.target` points back at the
  // element, which is how `document.getAnimations()` callers get from an
  // animation to its geometry.
  getAnimations() {
    const names = String(this._attrs['anim'] || '')
      .split(/\s+/).filter(n => n && n !== 'none');
    const state = this._attrs['playstate'] || 'running';
    return names.map(n => ({
      animationName: n, playState: state, effect: { target: this },
    }));
  }
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
  // ⭐ 2026-08-05 — `hidden` must suppress THIS too, not only `offsetParent`. A
  // browser returns ZERO rects for anything in a `display:none` subtree, and half
  // the production JS in this repo gates on `getClientRects().length` while the
  // other half gates on `offsetParent`. With only the latter honoured, a fixture
  // that hid a menu still had every row read as on-screen — so a "the hidden
  // popover's rows are skipped" test passed against code that never skipped them.
  getClientRects() {
    for (let n = this; n; n = n.parent) if (n.getAttribute('hidden') !== null) return [];
    return [this.getBoundingClientRect()];
  }
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
  // ⭐ 2026-08-05 — production CLIMBS with `el.parentElement`, not `el.parent`, and
  // the shim only exposed the latter. So every climb-to-a-panel-sized-ancestor walk
  // stopped dead after one step on `undefined` — including the ChatGPT activity
  // panel's own root finder, whose `activityRoot` therefore came back null and made
  // the whole walker return zeros. A fixture that cannot answer the way the browser
  // does turns a passing test into no test at all.
  get parentElement() { return this.parent; }
  // ⭐ 2026-08-22 — the SCROLL BOX. Claude's sources list is an
  // `ol role="list"` with `overflow-y-auto`, and whether it VIRTUALISES is an
  // open question that can only be answered from a run with sources: the
  // measured 5-row sample reported scrollHeight == clientHeight, which proves
  // nothing either way. Production therefore scroll-and-accumulates, and a shim
  // with no scroll box could not execute that loop at all — the accumulation
  // would have shipped source-scanned, which is how this repo has already
  // shipped an inverted gate.
  //
  // `sh`/`ch` drive it, matching the `w`/`h`/`x`/`y` idiom above, and default to
  // EQUAL (600) so every existing fixture reads as not-scrollable — the common
  // real case. A fixture declares a scrollable list by setting `sh` > `ch`.
  // `scrollTop` is a real settable property because production writes it, and a
  // getter-only member would have made the write a silent no-op.
  get scrollHeight() { return 'sh' in this._attrs ? +this._attrs.sh : 600; }
  get clientHeight() { return 'ch' in this._attrs ? +this._attrs.ch : 600; }
  get scrollTop() { return +(this._attrs.st || 0); }
  set scrollTop(v) { this._attrs.st = String(v); }
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
  // ⭐ 2026-08-22 — `Node.contains`. Claude's sources disclosure resolves the
  // list it discloses by walking ancestors for a list the CONTROL IS NOT INSIDE,
  // and `!list.contains(toggle)` is the entire guard: without it the walk
  // happily returns the list the toggle is a row of — the progress checklist,
  // i.e. exactly the surface that read was written to stop reading. With this
  // member missing the JS threw, so the branch was unreachable under the shim
  // and no test could tell a working walk from one that had never run.
  // Browser semantics: a node contains ITSELF.
  contains(other) {
    for (let n = other; n; n = n.parent) if (n === this) return true;
    return false;
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
  // ⭐⭐ 2026-08-20 — `:not(...)` IS A PRODUCTION SELECTOR HERE, and this shim
  // could not match it at all. The pattern below never accepted a `:` so
  // `matchSimple` returned false for the whole compound — which means every
  // selector carrying a `:not()` matched NOTHING under the shim, silently. The
  // Gemini source scan is one of them, so a test of it measured zero either way:
  // the arm was dead in production AND unmatchable in the harness, and the two
  // failures looked identical. Peeled off first, then the base is matched, then
  // each excluded selector must NOT match.
  const nots = [];
  p = p.replace(/:not\(([^()]*)\)/g, (_m, inner) => { nots.push(inner); return ''; });
  for (const n of nots) {
    if (n.split(',').map(s => s.trim()).filter(Boolean)
         .some(x => matchSimple(el, x))) return false;
  }
  // `a:not(x)` reduces to `a`; a bare `:not(x)` reduces to "anything not x".
  if (p === '') p = '*';
  // The universal selector. Production reaches for it when it has to walk a
  // container it cannot name a tag for — the NotebookLM "Generating Audio
  // Overview…" placeholder, whose tag is not in any capture. Without this the
  // shim returned zero matches for `*`, which reads exactly like a selector
  // that cannot match and would let a broken counter pass.
  if (p === '*') return true;
  // Tag + any mix of .class / #id / [attr] — `.font-claude-message` scoping is
  // load-bearing in the Claude artifact path (pass 1 is assistant-scoped), so a shim
  // that silently failed every class selector would take the wrong branch.
  // ⭐ 2026-08-05 — the tag part accepts DIGITS. It was `[a-zA-Z-]*`, so `h1`, `h2`,
  // `h3`, `td`… — every tag whose name carries a number — silently matched nothing.
  // Consequence measured on the ChatGPT panel walker: its section-heading extraction
  // (`panel.querySelectorAll('h1, h2, h3')`) had never once been exercised by a test,
  // and a fixture with a heading in it reported zero sections exactly like the live
  // panel that genuinely has none. Two very different states, one indistinguishable
  // result.
  const m = p.match(/^([a-zA-Z][a-zA-Z0-9-]*)?((?:[.#][A-Za-z0-9_-]+|\[[^\]]*\])*)$/);
  if (!m) return false;
  if (m[1] && el.tagName !== m[1].toUpperCase()) return false;
  // ⛔⛔ 2026-08-20 — CLASSES AND IDS ARE SCANNED OUTSIDE THE BRACKETS ONLY.
  // These two loops used to scan the whole qualifier string, so a DOT inside an
  // attribute VALUE was read as a class selector: `[href*="accounts.google"]`
  // was taken to also require `class="google"`, which nothing has, so the whole
  // selector matched NOTHING. Silently — a production exclusion list that could
  // never exclude anything looked identical to one that worked. Measured on the
  // Gemini source scan, whose `:not([href*="accounts.google"])` and
  // `:not([href*="google.com/gemini"])` both carry dots.
  const bare = m[2].replace(/\[[^\]]*\]/g, '');
  for (const cls of (bare.match(/\.[A-Za-z0-9_-]+/g) || [])) {
    if (!el.classList.contains(cls.slice(1))) return false;
  }
  for (const id of (bare.match(/#[A-Za-z0-9_-]+/g) || [])) {
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
  // ⭐ 2026-08-17 — `getElementById` was missing, and the ChatGPT picker walk is
  // built on it: a menu row carries `aria-controls` naming the submenu it owns,
  // and resolving that id is what makes "these rows belong to the control I just
  // pressed" a fact rather than a guess about document order. Without this the
  // walk threw and no test could reach the branch at all — the same shape as the
  // `dataset` and `parentElement` gaps recorded above, where a missing shim
  // member turned a passing test into no test.
  //
  // Browser semantics: FIRST match in document order, null when absent. Returning
  // the last (or throwing on a duplicate) would hide exactly the ambiguity the
  // production code is entitled to assume the browser resolves this way.
  getElementById: (id) => ROOT.querySelectorAll('[id="' + id + '"]')[0] || null,
  // `document.body` is the picker's fallback root for "no menu has mounted
  // yet". Without it that branch throws instead of exercising the fallback.
  get body() { return ROOT; },
  // The document-wide view of the same API. Production reaches for it when the
  // question is "is ANYTHING on this page still animating" and there is no
  // class name worth selecting on — which is the only formulation that can find
  // an animation whose name is the signal and whose class is meaningless.
  // Document order, root first, exactly as a browser reports it.
  getAnimations: () => [ROOT, ...ROOT.descendants()].flatMap(e => e.getAnimations()),
};
// ⭐ 2026-08-17 — THE SHIMMER IS A COMPUTED STYLE, and this returned a constant.
// ChatGPT's live progress line is an animated gradient clipped to the text, and
// the structural anchor that finds it reads exactly these three properties. With
// a fixed object every candidate reported `anim:false`, so the shimmer branch was
// unreachable under the shim and no test could tell a working anchor from one
// that had never fired. Driven by attributes, like the geometry above: put
// `anim="shimmer"` (or `clip="text"`) on a fixture node to make it shimmer.
globalThis.getComputedStyle = (el) => {
  const get = (n) => (el && el.getAttribute) ? (el.getAttribute(n) || '') : '';
  const clip = get('clip');
  return { display: 'block', visibility: 'visible', opacity: '1',
           animationName: get('anim') || 'none',
           backgroundClip: clip, webkitBackgroundClip: clip };
};
globalThis.window = { innerWidth: 1440, innerHeight: 900 };
globalThis.PointerEvent = class { constructor(t) { this.type = t; } };
globalThis.MouseEvent = class { constructor(t) { this.type = t; } };
globalThis.__run = (spec, fn, arg) => {
  ROOT = build(spec);
  const ret = arg === undefined ? fn() : fn(arg);
  return { ret, clicks: CLICKS };
};
"""


def stamp_panel_geometry(spec, *, w=520, h=800, x=900, y=0,
                         kid_w=300, kid_h=40, kid_y=50) -> dict:
    """Give a captured subtree the geometry it demonstrably had, in place.

    Captured markup carries no layout, and every panel-root selector in this repo
    gates on `getBoundingClientRect()` — width, height, and position relative to
    the viewport's midpoint. Without geometry the shim's defaults put every node
    at the LEFT edge, so the panel finder rejects all of them and the extractor
    returns its empty result. That reads exactly like a broken extractor.

    What is asserted here is not invented: the capture IS the right-hand panel's
    own `outerHTML`, so every node in it was inside a panel-sized element on the
    right of the viewport. The root gets panel dimensions; descendants get a
    small-but-visible box so they pass visibility checks without themselves
    qualifying as the panel and out-ranking the root.

    Existing `w`/`h`/`x`/`y` attributes are left alone, so a fixture can still pin
    one element off-screen deliberately.
    """
    def _walk(node, depth):
        a = node["attrs"]
        if depth == 0:
            a.update({"w": str(w), "h": str(h), "x": str(x), "y": str(y)})
        else:
            for k, v in (("w", kid_w), ("h", kid_h), ("x", x), ("y", kid_y)):
                a.setdefault(k, str(v))
        for kid in node["kids"]:
            _walk(kid, depth + 1)

    _walk(spec, 0)
    return spec


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

    ⚠⚠ 2026-08-06 — THE SCRIPT GOES IN A FILE, NOT IN `node -e`. It used to be
    passed as a single command-line argument, and Linux caps ONE argument at
    128 KB (MAX_ARG_STRLEN) regardless of how much total argv room there is.
    macOS is far more generous, so this passed locally and failed in CI with
    `OSError: [Errno 7] Argument list too long` the moment a real captured panel
    became the fixture: a 60 KB capture is a 79 KB spec, and the shim source is
    added on top.
    ⛔ The comment on `build()` had already flagged this exact ceiling — "the JSON
    would be a 400 KB argv, near the OS limit" — and the `repeat` mechanism exists
    to dodge it. Dodging a limit leaves it there for the next fixture; a temp file
    removes it. Nothing here needs to be inline.
    """
    if NODE is None:
        raise RuntimeError("node is required to run page JS")
    payload = json.dumps(spec)
    argjs = "undefined" if arg is None else json.dumps(arg)
    js = (SHIM + "\nconsole.log(JSON.stringify(__run("
          + payload + ", " + fn_src.strip() + ", " + argjs + ")));\n")
    with tempfile.TemporaryDirectory(prefix="sr_domshim_") as _d:
        script = os.path.join(_d, "run.mjs" if "import " in js else "run.js")
        with open(script, "w", encoding="utf-8") as _f:
            _f.write(js)
        # ⚠ encoding="utf-8" is NOT optional. `text=True` alone decodes with the
        # LOCALE codec, which on Windows is cp1252 -- and node always emits UTF-8.
        # Any fixture carrying a non-Latin-1 byte (a curly quote, an em dash, a
        # CJK title in a captured source row) then died with UnicodeDecodeError
        # inside subprocess's reader THREAD, so it surfaced as an unrelated-looking
        # error on every test in the file rather than a decode failure.
        p = subprocess.run([NODE, script], capture_output=True, text=True,
                           encoding="utf-8", timeout=60)
        if p.returncode != 0:
            raise AssertionError(f"node failed: {p.stderr}")
        return json.loads(p.stdout.strip().splitlines()[-1])
