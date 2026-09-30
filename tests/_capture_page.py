"""Build a local test page from the owner's page recordings (structure only).

The recordings (tests/fixtures/chatgpt_0930/*.json, "sr-page-recording") hold,
per moment, trees of nodes: {tag, a: {attributes}, box, txtLen, label?, css?,
textNodes?, k: [children]}. `label` is the node's visible text, whitespace
collapsed, recorded only when it is at most 40 characters; `txtLen` is the
length of its text; `css` is "display/visibility/position" where recorded.

This turns one such tree back into HTML: every tag, attribute and nesting as
recorded; a value the recorder replaced with "<N chars>" becomes N filler
characters; `css` becomes an inline style. Text is the recorded label where
there is one, and filler of the recorded length where there is not — so a test
can read what the page read, and nothing the owner's page said beyond 40
characters is ever needed.

⚠ ASSUMED wherever the recording is silent: where a node's own text sits among
its children (before them), and the text inside a node the recorder did not
descend into (its label, if it had one).
"""
import html as _html
import json
from pathlib import Path

FIX = Path(__file__).parent / "fixtures" / "chatgpt_0930"

#: Class hooks whose layout matters to a reader (flex items are blocks, so a
#: label drawn twice reads "X\nX" as it does on the live page). Tailwind's own
#: meaning for each.
BASE_CSS = """
.flex{display:flex}.inline-flex{display:inline-flex}.flex-col{flex-direction:column}
.contents{display:contents}.hidden{display:none}.block{display:block}
.inline-block{display:inline-block}.relative{position:relative}
.absolute{position:absolute}.inset-0{inset:0}.fixed{position:fixed}
.sr-only{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0)}
.pointer-events-none{pointer-events:none}
"""

_WORDS = ("lorem ipsum dolor sit amet consectetur adipiscing elit sed do eiusmod "
          "tempor incididunt ut labore et dolore magna aliqua").split()


def load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def filler(n, seed=0):
    """`n` characters of words, deterministic."""
    out, i = "", seed
    while len(out) < n:
        out += (" " if out else "") + _WORDS[i % len(_WORDS)]
        i += 1
    return out[:n].rstrip() or "x" * max(n, 0)


def _placeholder(v):
    if isinstance(v, str) and v.startswith("<") and v.endswith(" chars>"):
        try:
            n = int(v[1:].split()[0])
        except ValueError:
            return v
        return ("_r" + "x" * n)[:n]
    return v


def _style(css):
    if not css:
        return ""
    parts = str(css).split("/")
    keys = ("display", "visibility", "position")
    return ";".join(f"{k}:{v}" for k, v in zip(keys, parts) if v)


def node_html(n, *, attrs=None, seed=0):
    """HTML for one recorded node and everything recorded under it."""
    if not isinstance(n, dict):
        return ""
    tag = str(n.get("tag") or "div").lower()
    if tag in ("?", "#text"):
        return ""
    if tag == "svg":
        return '<svg width="16" height="16" aria-hidden="true"></svg>'
    if tag == "path":
        return ""
    a = dict(n.get("a") or {})
    a.update(attrs or {})
    style = _style(n.get("css"))
    parts = []
    for k, v in a.items():
        v = _placeholder(v)
        if k == "style" and style:
            v = f"{v};{style}"
            style = ""
        parts.append(f' {k}="{_html.escape(str(v), quote=True)}"' if v != "" else f" {k}")
    if style:
        parts.append(f' style="{style}"')
    kids = [c for c in (n.get("k") or []) if isinstance(c, dict)]
    inner = "".join(node_html(c, seed=seed + i + 1) for i, c in enumerate(kids))
    own = _own_text(n, kids, seed)
    if n.get("textNodes") and not kids and _doubled(n.get("label")):
        # ⚠ ASSUMED, from a shallower frame of the same recording: a label
        # recorded as "X X" with no child recorded under it is the text and its
        # shimmer copy, the copy cut off by the recorder's depth limit.
        half = str(n["label"])[:len(str(n["label"])) // 2]
        own, inner = half, _SWEEP + _html.escape(half) + "</span>"
    if tag in ("img", "input", "br", "hr", "meta", "link"):
        return f"<{tag}{''.join(parts)}>"
    if tag == "iframe":
        return f"<iframe{''.join(parts)}></iframe>"
    return f"<{tag}{''.join(parts)}>{_html.escape(own)}{inner}</{tag}>"


def _doubled(label):
    """"X X" — a label the page draws twice, as the recorder collapsed it."""
    s = str(label or "")
    h = len(s) // 2
    return len(s) % 2 == 1 and s[h] == " " and s[:h] == s[h + 1:] and h > 0


#: The shimmer copy of a label drawn twice, as the recording shows it wherever it
#: reached that deep (4-chatgpt-p1-thinking.json, frame 8: the text, then this
#: span, aria-hidden, css "block/visible/absolute").
_SWEEP = '<span class="cadencedShimmerSweep-ICUAVH" aria-hidden="true" style="position:absolute">'


def _own_text(n, kids, seed):
    label = n.get("label")
    tl = int(n.get("txtLen") or 0)
    if n.get("textNodes"):
        if label is not None:
            own = str(label)
            for c in kids:
                cl = c.get("label")
                if cl and cl in own:
                    i = own.rfind(cl)
                    own = (own[:i] + own[i + len(cl):]).strip()
            # The word spans ("Planning", "research", "scope") carry their
            # space in the text the recorder trimmed: txtLen says how much.
            if not kids and len(own) < tl <= len(own) + 2:
                own = own + " " * (tl - len(own))
            return own
        rest = tl - sum(int(c.get("txtLen") or 0) for c in kids)
        return filler(max(rest, 1), seed)
    if not kids and label:
        return str(label)
    if not kids and tl > 0 and label is None:
        return filler(tl, seed)
    return ""


def page_html(body, *, extra_css="", title="capture"):
    return ("<!doctype html><html><head><meta charset='utf-8'><title>" + title
            + "</title><style>" + BASE_CSS + extra_css + "</style></head><body>"
            + body + "</body></html>")


def frame(capture, index):
    return capture["frames"][index]


def find(n, pred):
    """The first node under (and including) `n` for which `pred` holds."""
    if not isinstance(n, dict):
        return None
    if pred(n):
        return n
    for c in n.get("k") or []:
        hit = find(c, pred)
        if hit is not None:
            return hit
    return None


def has_class(token):
    return lambda n: token in str((n.get("a") or {}).get("class", "")).split()
