"""Wave 10.9 — the document funnel: no private link in a saved document, CRLF
definitions resolve, and an image's name lookup ends at the image's deadline.

⛔⛔ WHAT THE WAVE CLOSED.

  D1 — only a link AROUND an image was ever checked, and a document with no image
       never entered the funnel at all (`if not text or not ("![" in text …)):
       return text`). A report's signed `files.oaiusercontent.com` link, its
       `sandbox:` download, the agent's own `chatgpt.com/c/…` conversation or a
       `[1]: <googleusercontent>` definition was saved as written — into the
       document, the NotebookLM upload and every frozen share.
       ⭐ The refuter NARROWED the fix: the private SHAPES only, never the platform
       host list as a whole — it names help.openai.com, a real source.
  D3 — `_DOC_IMG_DEF_RE` ended in `\\n` only: a CRLF document (Gemini's in-page
       clipboard read on Windows) matched no definition, so every reference image
       stayed `![c][1]` and its definition kept the platform URL.
  (+) `_doc_img_resolve_host` → getaddrinfo had no time bound and ran outside the
       image's deadline; so did the connect's own lookup. ⭐ Repair round 2 gave
       that bound a constant of its own (`_DOC_IMG_LOOKUP_TIMEOUT`) above one
       resolver retry, and made a lookup the CLOCK ended something the research
       does not remember.

Every mutant below is a way the fix could go back to decoration while looking
installed. The quiet ones matter most:

  F2  — ⛔⛔ THE SCRUB MOVES AHEAD OF THE IMAGES. Every link test stays green; the
        definition a platform image resolves through, and a data: image's bytes,
        are gone before the image pass can store them.
  F3  — ⛔⛔ THE SCRUB MOVES INTO THE IMAGE HALF — the collision the refuter named:
        incognito will skip that half, and the private links ship with it.
  H1  — ⛔⛔ THE WHOLE PLATFORM LIST IS PRIVATE: a research about ChatGPT loses its
        help-centre citations. Looks stricter; deletes real sources.
  R1/R2 — the first-definition rule: a later private duplicate keeps the label's
        real link alive, and the label a renderer reads loses every definition.
  L2  — the URL check hands the lookup a deadline an hour away: the bound exists
        and binds nothing the image's clock can see.
  L14/L15 — ⛔⛔ REPAIR ROUND 2. The bound the wave shipped WAS the connect
        timeout, and 5 s is a stub resolver's own first-attempt timeout: one lost
        UDP query answered at ~5.1 s and read as a resolver that is down. Both
        mutants put it back, one at the constant and one at the use.
  L17 — and the other half: that verdict went into the per-research cache with
        115 of the document's 120 s unspent, so the brief, the other agent
        reports, the consolidated report and the Super Research all captioned the
        same chart without asking again.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE, and every
mutated file must still COMPILE — a mutant that does not parse fails every test
and would be scored as a kill. Both are harness faults, counted OUT.

⚠ Four wave-4 mutants (R1, N5, CN2, CN4 in wave4_document_images_0913_mutants.py)
were re-aimed at the lines this wave moved; they are not duplicated here.

  .venv/bin/python .mutants/wave109_docfunnel_mutants.py
  .venv/bin/python .mutants/wave109_docfunnel_mutants.py F2 H1
"""
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SUITES = "tests/test_document_images_0913.py"
RESEARCH = "research.py"
FILES = (RESEARCH,)
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

# ── anchors: the funnel ─────────────────────────────────────────────────────
F_WRAP = "    return _doc_scrub_private_links(await _doc_images_rehost(text, label))"
F_IMG_RETURN = "    _doc_img_log_stats(label, run.stats)\n    return out\n"

# ── anchors: what is private ────────────────────────────────────────────────
H_SCHEMES = "    if low.startswith(_DOC_PRIVATE_LINK_SCHEMES):\n        return True\n"
H_DATA = '_DOC_PRIVATE_LINK_SCHEMES = ("data:", "blob:", "sandbox:")'
H_HOSTS = '_DOC_PRIVATE_LINK_HOSTS = ("oaiusercontent.com", "googleusercontent.com", "ggpht.com")'
H_HOST_TEST = "    if any(_on(h) for h in _DOC_PRIVATE_LINK_HOSTS):\n"
H_PATH_TEST = "    return any(_on(h) and rx.match(parts.path) for h, rx in _DOC_PRIVATE_LINK_PATHS)"
H_ON = '        return host == name or host.endswith("." + name)'
H_WWW = '    if low.startswith("www."):\n        dest = "https://" + dest\n'
P_CHATGPT = '    ("chatgpt.com", re.compile(r"/(?:g/[^/]+/)?c/")),\n'
P_OPENAI = '    ("chat.openai.com", re.compile(r"/(?:g/[^/]+/)?c/")),\n'
P_CLAUDE = '    ("claude.ai", re.compile(r"/chat/")),\n'
P_GEMINI = '    ("gemini.google.com", re.compile(r"/(?:u/\\d+/)?app/")),\n'
P_NLM = '    ("notebooklm.google.com", re.compile(r"/notebook/")),\n'

# ── anchors: the scrub ──────────────────────────────────────────────────────
S_EMPTY = "    if not text:\n        return text\n    masked, unmask = _doc_img_mask_code(text)\n"
S_MASK = "    masked, unmask = _doc_img_mask_code(text)\n    private: set = set()\n"
S_FIRST = ("        if key not in seen:\n"
           "            seen.add(key)\n"
           "            dest = m.group(\"adest\") if m.group(\"adest\") is not None else m.group(\"dest\")\n"
           "            if _doc_link_is_private(dest):\n"
           "                private.add(key)\n")
S_FIRST_ANY = ("        dest = m.group(\"adest\") if m.group(\"adest\") is not None else m.group(\"dest\")\n"
               "        if _doc_link_is_private(dest):\n"
               "            private.add(key)\n")
S_DEF = ('        if _doc_img_label_key(m.group("label")) in private or _doc_link_is_private(dest):\n'
         '            return ""\n')
S_INLINE = ('        return m.group("text") if _doc_link_is_private(href) else m.group(0)\n'
            '\n    def _reference(m):')
S_ESC = '        if s[i - 1:i] == "\\\\" or (s[i - 1:i] == "!" and s[i - 2:i - 1] != "\\\\"):\n'
S_IMG_GUARD = ' or (s[i - 1:i] == "!" and s[i - 2:i - 1] != "\\\\"):\n'
S_ESC_BANG = ' and s[i - 2:i - 1] != "\\\\"):\n'
S_PAREN = ('        if m.group("label") is None and s.startswith("(", m.end()):\n'
           '            return m.group(0)\n        key = _doc_img_label_key(')
S_REF_KEY = '        return m.group("text") if key in private else m.group(0)\n\n    def _bare(m):'
S_RSTRIP = '            core = url.rstrip(".,:;!?*_~")\n'
S_BARE_KEEP = "        return tail if _doc_link_is_private(url) else m.group(0)\n"
S_RUN_INLINE = "    out = _DOC_PRIVATE_INLINE_RE.sub(_inline, out)\n"
S_RUN_REF = "    if private:\n        out = _DOC_IMG_BRACKET_RE.sub(_reference, out)\n"
S_RUN_BARE = "        new = _DOC_PRIVATE_BARE_RE.sub(_bare, line)\n"
S_DROP = ("        if new == line or not _DOC_EMPTIED_LINE_RE.match(new):\n"
          "            lines.append(new)\n")
S_SAME = "    return text if out == masked else unmask(out)\n"

# ── anchors: the patterns ───────────────────────────────────────────────────
X_INLINE = '_DOC_PRIVATE_INLINE_RE = re.compile(r"(?<!\\\\)(?<!(?<!\\\\)!)" + _DOC_LINK_INLINE)'
X_BARE_HEAD = '    r"[ \\t]?(?P<lt><)?(?<![A-Za-z0-9])"\n'
X_BARE_TAIL = '[^\\s<>()\\[\\]\\"\'`]++)(?(lt)>)", re.I)'
X_EMPTIED = '_DOC_EMPTIED_LINE_RE = re.compile(r"[ \\t>]*(?:[-*+]|\\d{1,9}[.)])?[ \\t\\r]*\\Z")'

# ── anchors: CRLF definitions ───────────────────────────────────────────────
C_END = '[ \\t]*(?:\\r?\\n|\\Z)", re.M)'
C_TITLE = "|[ \\t]*\\r?\\n[ \\t]*)"

# ── anchors: the bounded lookup ─────────────────────────────────────────────
L_FETCH = "            _doc_img_check_url(url, deadline)\n"
L_CHECK = "        addrs = _doc_img_resolve_host(parts.hostname, 443, deadline)\n"
L_RESOLVE = "    return [info[4][0] for info in _doc_img_lookup(host, port, deadline)]"
L_CONNECT = ('        infos = _doc_img_lookup(host.strip("[]"), port, deadline,\n'
             "                                allowed_gai_family())[:_DOC_IMG_CONNECT_ADDRS]\n")
L_LEFT = "    left = min(_DOC_IMG_LOOKUP_TIMEOUT, deadline - time.monotonic())\n"
L_BOUND = "_DOC_IMG_LOOKUP_TIMEOUT = 10.0"
L_CHECK_TO = ('        raise _DocImageRefused("failed", timed_out=isinstance(exc, TimeoutError))'
              " from None\n    if not addrs")
L_CONNECT_TO = ('        raise _DocImageRefused("failed", timed_out=isinstance(exc, TimeoutError))'
                " from None\n    skipped")
L_KEEP = "    if cut_off and (timed_out or time.monotonic() >= run.deadline):\n"
L_SET = "        timed_out = refusal.timed_out\n"
L_FIELD = "        self.timed_out = timed_out\n"
L_GUARD = ('    if left <= 0:\n        raise TimeoutError("lookup")\n    box: dict = {}\n')
L_GAI = "            box[\"infos\"] = socket.getaddrinfo(host, port, family, socket.SOCK_STREAM)\n"
L_CATCH = "        except BaseException as exc:  # noqa: BLE001 — raised again in the waiting thread\n"
L_DAEMON = 'th = _threading.Thread(target=_resolve, name="doc-images-lookup", daemon=True)'
L_JOIN = "    th.join(left)\n"
L_ALIVE = '    if th.is_alive():\n        raise TimeoutError("lookup")\n    if "error" in box:\n'
L_ERROR = '    if "error" in box:\n        raise box["error"]\n'

MUTANTS = [
    # ── D1: where the scrub sits ────────────────────────────────────────────
    ("F1", "under", RESEARCH,
     "⛔⛔ THE DEFECT ITSELF — the funnel stops scrubbing; every private link is "
     "saved as written",
     [(F_WRAP, "    return await _doc_images_rehost(text, label)")]),
    ("F2", "under", RESEARCH,
     "⛔⛔ the scrub runs BEFORE the images: a platform image's definition and a "
     "data: image's bytes are cut before they can be stored",
     [(F_WRAP, "    return await _doc_images_rehost(_doc_scrub_private_links(text), label)")]),
    ("F3", "under", RESEARCH,
     "⛔⛔ the scrub moves INTO the image half — skipped with it (incognito), and "
     "skipped by its early return for a document with no image",
     [(F_WRAP, "    return await _doc_images_rehost(text, label)"),
      (F_IMG_RETURN, "    _doc_img_log_stats(label, run.stats)\n    return _doc_scrub_private_links(out)\n")]),

    # ── D1: what is private ─────────────────────────────────────────────────
    ("H1", "over", RESEARCH,
     "⛔⛔ THE WHOLE PLATFORM LIST IS PRIVATE — help.openai.com, gstatic and "
     "support.anthropic.com citations deleted from research about those products",
     [(H_HOST_TEST, "    if _doc_img_is_platform_host(host) or any(_on(h) for h in _DOC_PRIVATE_LINK_HOSTS):\n")]),
    ("H2", "under", RESEARCH,
     "sandbox:, blob: and data: destinations stay",
     [(H_SCHEMES, "")]),
    ("H3", "under", RESEARCH,
     "a data: link stays in the saved text",
     [(H_DATA, '_DOC_PRIVATE_LINK_SCHEMES = ("blob:", "sandbox:")')]),
    ("H4", "under", RESEARCH,
     "⛔ a signed googleusercontent link stays",
     [(H_HOSTS, '_DOC_PRIVATE_LINK_HOSTS = ("oaiusercontent.com", "ggpht.com")')]),
    ("H5", "under", RESEARCH,
     "⛔ a signed oaiusercontent file link stays",
     [(H_HOSTS, '_DOC_PRIVATE_LINK_HOSTS = ("googleusercontent.com", "ggpht.com")')]),
    ("H6", "under", RESEARCH,
     "a ggpht image link stays",
     [(H_HOSTS, '_DOC_PRIVATE_LINK_HOSTS = ("oaiusercontent.com", "googleusercontent.com")')]),
    ("H7", "under", RESEARCH,
     "⛔ every conversation path stays",
     [(H_PATH_TEST, "    return False")]),
    ("H8", "over", RESEARCH,
     "⛔ the path is not read: a public share, a product's home page go too",
     [(H_PATH_TEST, "    return any(_on(h) for h, rx in _DOC_PRIVATE_LINK_PATHS)")]),
    ("H9", "over", RESEARCH,
     "the label boundary goes: notchatgpt.com/c/… is the agent's conversation",
     [(H_ON, "        return host.endswith(name)")]),
    ("H10", "under", RESEARCH,
     "the host itself no longer matches, only its subdomains",
     [(H_ON, '        return host.endswith("." + name)')]),
    ("H11", "under", RESEARCH,
     "an address written www.chatgpt.com/c/… (the renderer autolinks it) stays",
     [(H_WWW, "")]),
    ("P1", "under", RESEARCH, "a ChatGPT conversation URL stays",
     [(P_CHATGPT, "")]),
    ("P2", "under", RESEARCH,
     "a ChatGPT conversation inside a GPT or a project (/g/<id>/c/…) stays",
     [(P_CHATGPT, '    ("chatgpt.com", re.compile(r"/c/")),\n')]),
    ("P3", "under", RESEARCH, "the old ChatGPT host's conversation stays",
     [(P_OPENAI, "")]),
    ("P4", "under", RESEARCH, "a Claude conversation stays",
     [(P_CLAUDE, "")]),
    ("P5", "under", RESEARCH,
     "a Gemini conversation under an account index (/u/1/app/…) stays",
     [(P_GEMINI, '    ("gemini.google.com", re.compile(r"/app/")),\n')]),
    ("P6", "under", RESEARCH, "a NotebookLM notebook stays",
     [(P_NLM, "")]),

    # ── D1: the scrub's passes ──────────────────────────────────────────────
    ("S1", "under", RESEARCH,
     "no text → a crash on the None a caller may hand over",
     [(S_EMPTY, "    masked, unmask = _doc_img_mask_code(text)\n")]),
    ("S2", "over", RESEARCH,
     "⛔ code is scrubbed too — a quoted address in a fence is rewritten",
     [(S_MASK, "    masked, unmask = text, (lambda t: t)\n    private: set = set()\n")]),
    ("R1", "over", RESEARCH,
     "⛔ ANY private definition makes its label private: a later duplicate strips "
     "the label's real link and its first definition",
     [(S_FIRST, S_FIRST_ANY)]),
    ("R2", "under", RESEARCH,
     "a later private duplicate of a label stays in the document",
     [(S_DEF, '        if _doc_img_label_key(m.group("label")) in private:\n            return ""\n')]),
    ("R3", "under", RESEARCH,
     "a private label's later ordinary definition stays, and the renderer reads it",
     [(S_DEF, '        if _doc_link_is_private(dest):\n            return ""\n')]),
    ("R4", "under", RESEARCH,
     "the references to a removed definition keep their brackets",
     [(S_RUN_REF, "")]),
    ("R5", "over", RESEARCH,
     "an image's brackets are read as a reference: `![c][1]` becomes `!c`",
     [(S_IMG_GUARD, ":\n")]),
    ("R6", "under", RESEARCH,
     "an escaped `\\!` still reads as an image, so the link after it keeps its brackets",
     [(S_ESC_BANG, "):\n")]),
    ("R7", "over", RESEARCH,
     "an escaped bracket is read as a reference",
     [(S_ESC, '        if (s[i - 1:i] == "!" and s[i - 2:i - 1] != "\\\\"):\n')]),
    ("R8", "over", RESEARCH,
     "an inline link's text is read as a reference: `[1](https://…)` loses its brackets",
     [(S_PAREN, "        key = _doc_img_label_key(")]),
    ("R9", "over", RESEARCH,
     "every reference loses its brackets once any label is private",
     [(S_REF_KEY, '        return m.group("text")\n\n    def _bare(m):')]),
    ("I1", "under", RESEARCH,
     "⛔ an inline private link is never unwrapped — `[the file]()` is left",
     [(S_RUN_INLINE, "")]),
    ("I2", "under", RESEARCH,
     "an inline private link keeps its destination",
     [(S_INLINE, '        return m.group(0)\n\n    def _reference(m):')]),
    ("I3", "over", RESEARCH,
     "an inline IMAGE is unwrapped like a link: `![c](…)` becomes `!c`",
     [(X_INLINE, '_DOC_PRIVATE_INLINE_RE = re.compile(r"(?<!\\\\)" + _DOC_LINK_INLINE)')]),
    ("I4", "under", RESEARCH,
     "a citation after an escaped `\\!` is not read as a link",
     [(X_INLINE, '_DOC_PRIVATE_INLINE_RE = re.compile(r"(?<![\\\\!])" + _DOC_LINK_INLINE)')]),
    ("B1", "under", RESEARCH,
     "⛔ a bare or autolinked conversation URL stays — the renderer links it",
     [(S_RUN_BARE, "        new = line\n")]),
    ("B2", "under", RESEARCH,
     "the bare rule never removes",
     [(S_BARE_KEEP, "        return m.group(0)\n")]),
    ("B3", "over", RESEARCH,
     "the sentence's closing period goes with the address",
     [(S_RSTRIP, "            core = url\n")]),
    ("B4", "under", RESEARCH,
     "an autolink's closing `>` is left behind",
     [(X_BARE_TAIL, '[^\\s<>()\\[\\]\\"\'`]++)", re.I)')]),
    ("B5", "under", RESEARCH,
     "the space before a removed address stays — `the chat  and`",
     [(X_BARE_HEAD, '    r"(?P<lt><)?(?<![A-Za-z0-9])"\n')]),
    ("B6", "over", RESEARCH,
     "a word ending in data:/blob:/sandbox: is cut: `metadata:text/plain` → `meta`",
     [(X_BARE_HEAD, '    r"[ \\t]?(?P<lt><)?"\n')]),
    ("E1", "under", RESEARCH,
     "⛔ a line left with only its list marker stays — `-` under a paragraph turns "
     "it into a heading",
     [(S_DROP, "        lines.append(new)\n")]),
    ("E2", "over", RESEARCH,
     "a line that was blank before is dropped too",
     [(S_DROP, "        if not _DOC_EMPTIED_LINE_RE.match(new):\n            lines.append(new)\n")]),
    ("E3", "under", RESEARCH,
     "only an EMPTY line goes; a bare list marker stays",
     [(X_EMPTIED, '_DOC_EMPTIED_LINE_RE = re.compile(r"[ \\t>]*[ \\t\\r]*\\Z")')]),
    ("E4", "under", RESEARCH,
     "a numbered list marker stays",
     [(X_EMPTIED, '_DOC_EMPTIED_LINE_RE = re.compile(r"[ \\t>]*(?:[-*+])?[ \\t\\r]*\\Z")')]),
    ("E5", "under", RESEARCH,
     "a quote marker stays",
     [(X_EMPTIED, '_DOC_EMPTIED_LINE_RE = re.compile(r"[ \\t]*(?:[-*+]|\\d{1,9}[.)])?[ \\t\\r]*\\Z")')]),
    ("E6", "under", RESEARCH,
     "in a CRLF document the emptied line's `\\r` keeps it",
     [(X_EMPTIED, '_DOC_EMPTIED_LINE_RE = re.compile(r"[ \\t>]*(?:[-*+]|\\d{1,9}[.)])?[ \\t]*\\Z")')]),
    ("S3", "over", RESEARCH,
     "a new string every time — a document with nothing private is never itself",
     [(S_SAME, "    return unmask(out)\n")]),

    # ── D3: CRLF definitions ────────────────────────────────────────────────
    ("C1", "under", RESEARCH,
     "⛔ a CRLF definition matches nothing again: the reference image stays "
     "`![c][1]` and its definition keeps the platform URL",
     [(C_END, '[ \\t]*(?:\\n|\\Z)", re.M)')]),
    ("C2", "under", RESEARCH,
     "a CRLF definition's title on the next line is left behind",
     [(C_TITLE, "|[ \\t]*\\n[ \\t]*)")]),

    # ── the bounded lookup ──────────────────────────────────────────────────
    ("L1", "under", RESEARCH,
     "the fetch hands its URL check a deadline an hour away",
     [(L_FETCH, "            _doc_img_check_url(url, time.monotonic() + 3600)\n")]),
    ("L2", "under", RESEARCH,
     "⛔ the URL check hands its lookup a deadline an hour away",
     [(L_CHECK, "        addrs = _doc_img_resolve_host(parts.hostname, 443, time.monotonic() + 3600)\n")]),
    ("L3", "under", RESEARCH,
     "⛔⛔ THE DEFECT — the URL check's lookup is unbounded again",
     [(L_RESOLVE, "    return [info[4][0] for info in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)]")]),
    ("L4", "under", RESEARCH,
     "⛔⛔ the connect's own lookup is unbounded again, and starts after the deadline",
     [(L_CONNECT, ('        infos = socket.getaddrinfo(host.strip("[]"), port, allowed_gai_family(),\n'
                   "                                   socket.SOCK_STREAM)[:_DOC_IMG_CONNECT_ADDRS]\n"))]),
    ("L5", "under", RESEARCH,
     "no cap: a resolver that is down costs every image its whole budget",
     [(L_LEFT, "    left = deadline - time.monotonic()\n")]),
    ("L6", "under", RESEARCH,
     "the LONGER of the two bounds",
     [(L_LEFT, "    left = max(_DOC_IMG_TIMEOUT[0], deadline - time.monotonic())\n")]),
    ("L7", "over", RESEARCH,
     "a lookup starts after the image's deadline",
     [(L_GUARD, "    box: dict = {}\n")]),
    ("L8", "under", RESEARCH,
     "⛔ the wait has no bound — the thread only moved the hang",
     [(L_JOIN, "    th.join()\n")]),
    ("L9", "under", RESEARCH,
     "a lookup left behind holds the process's exit",
     [(L_DAEMON, 'th = _threading.Thread(target=_resolve, name="doc-images-lookup", daemon=False)')]),
    ("L10", "over", RESEARCH,
     "a resolver error reads as 'no address' — a refusal remembered for the research",
     [(L_ERROR, '    if "error" in box:\n        return []\n')]),
    ("L11", "under", RESEARCH,
     "an error other than OSError dies in the lookup thread and the caller sees a KeyError",
     [(L_CATCH, "        except OSError as exc:\n")]),
    ("L12", "over", RESEARCH,
     "a lookup out of time reads as 'no address' — a refusal instead of a failure",
     [(L_ALIVE, '    if th.is_alive():\n        return []\n    if "error" in box:\n')]),
    ("L13", "over", RESEARCH,
     "the lookup asks for every socket type, not a stream",
     [(L_GAI, "            box[\"infos\"] = socket.getaddrinfo(host, port, family)\n")]),

    # ── repair round 2: the lookup's own bound, and the clock's verdict ─────
    ("L14", "under", RESEARCH,
     "⛔⛔ THE DEFECT — the lookup's bound goes back onto a resolver's own retry "
     "interval: one lost UDP query is a resolver that is DOWN",
     [(L_BOUND, "_DOC_IMG_LOOKUP_TIMEOUT = 5.0")]),
    ("L15", "under", RESEARCH,
     "⛔⛔ THE DEFECT AT THE OTHER SITE — the lookup borrows the CONNECT timeout "
     "again, whatever its own constant says",
     [(L_LEFT, "    left = min(_DOC_IMG_TIMEOUT[0], deadline - time.monotonic())\n")]),
    ("L16", "over", RESEARCH,
     "the bound is above the image's whole budget — it binds nothing the image's "
     "clock cannot already see",
     [(L_BOUND, "_DOC_IMG_LOOKUP_TIMEOUT = 300.0")]),
    ("L17", "under", RESEARCH,
     "⛔⛔ THE SECOND HALF OF THE DEFECT — a lookup the clock ended is remembered "
     "for the research again, so every later document captions that image",
     [(L_KEEP, "    if cut_off and time.monotonic() >= run.deadline:\n")]),
    ("L18", "over", RESEARCH,
     "nothing decided while the image was being read is ever remembered: the "
     "per-image limit is paid again by every document of the research",
     [(L_KEEP, "    if cut_off:\n")]),
    ("L19", "over", RESEARCH,
     "⛔ every resolver failure reads as the clock — a name that does not exist is "
     "looked up again in every document",
     [(L_CHECK_TO, '        raise _DocImageRefused("failed", timed_out=True) from None\n'
                   "    if not addrs")]),
    ("L20", "under", RESEARCH,
     "the URL check's lookup no longer says the clock ended it",
     [(L_CHECK_TO, '        raise _DocImageRefused("failed") from None\n    if not addrs')]),
    ("L21", "under", RESEARCH,
     "the CONNECT's lookup no longer says the clock ended it — the second answer, "
     "inside the requests chain",
     [(L_CONNECT_TO, '        raise _DocImageRefused("failed") from None\n    skipped')]),
    ("L22", "under", RESEARCH,
     "the refusal says the clock ended it and the funnel does not read that",
     [(L_SET, "")]),
    ("L23", "under", RESEARCH,
     "the refusal carries the flag and never sets it",
     [(L_FIELD, "        self.timed_out = False\n")]),
]


def _run(cmd):
    return subprocess.run(cmd, cwd=ROOT, env=ENV, shell=True,
                          capture_output=True, text=True)


def green():
    # ⭐ THE INTERPRETER RUNNING THIS FILE, so a worktree with no `.venv` of its
    # own still measures its own tree (pytest puts the cwd first on sys.path).
    # `-x`: a kill needs one failure, and the file takes ~20 s whole.
    r = _run(f"{shlex.quote(sys.executable)} -m pytest {SUITES} -x -q -p no:cacheprovider")
    out = (r.stdout or "") + (r.stderr or "")
    # ⛔ THE SUMMARY LINE, NEVER THE EXIT CODE. This repo's backend suite once
    # died at 27% and exited 0, and a commit rode on it. ⭐ And only that line: a
    # warning's text may say "error" or "failed" on a run that passed.
    summary = [ln for ln in out.splitlines()
               if re.search(r"\b\d+ (passed|failed|errors?)\b.* in [\d.]+s", ln)]
    if not summary:
        return False
    last = summary[-1]
    return "passed" in last and "failed" not in last and "error" not in last


# ⛔⛔ EVERYTHING BELOW RUNS UNDER `__main__` ONLY. The static anchor sweep loads
# every harness in this directory with `spec.loader.exec_module`, which EXECUTES
# it — so an unguarded runner would turn the sweep into a full mutation run.
if __name__ == "__main__":
    ORIGINALS = {f: (ROOT / f).read_text(encoding="utf-8") for f in FILES}

    def restore():
        for f, t in ORIGINALS.items():
            (ROOT / f).write_text(t, encoding="utf-8")

    only = set(sys.argv[1:])
    print("baseline… ", end="", flush=True)
    if not green():
        print("⛔ BASELINE RED — fix the suite before mutating anything.")
        sys.exit(2)
    print("green\n")

    survivors = []
    selected = [m for m in MUTANTS if not only or m[0] in only]
    for mid, direction, fname, why, edits in selected:
        path = ROOT / fname
        original = ORIGINALS[fname]
        try:
            mutated = original
            for frm, to in edits:
                if frm == to:
                    raise AssertionError(f"replacement identical to anchor: {frm[:70]!r}")
                hits = mutated.count(frm)
                if hits != 1:
                    raise AssertionError(
                        f"anchor occurs {hits}x in {fname} (needs exactly 1): {frm[:70]!r}")
                mutated = mutated.replace(frm, to)
            # ⛔ A MUTANT THAT DOES NOT PARSE FAILS EVERY TEST and would be
            # scored as a kill. Refuse it before it reaches the disk.
            try:
                compile(mutated, fname, "exec")
            except SyntaxError as se:
                raise AssertionError(f"mutant does not compile: {se}")
            path.write_text(mutated, encoding="utf-8")
            if green():
                survivors.append(mid)
                print(f"  {mid}  ✗ SURVIVED ({direction}) — {why}")
            else:
                print(f"  {mid}  ✓ killed")
        except AssertionError as e:
            survivors.append(f"{mid} (anchor)")
            print(f"  {mid}  ⛔ HARNESS FAULT — {e}")
        finally:
            path.write_text(original, encoding="utf-8")

    restore()
    for f, t in ORIGINALS.items():
        if (ROOT / f).read_text(encoding="utf-8") != t:
            print(f"\n⛔⛔ RESTORE FAILED for {f} — fix the tree before trusting anything above")
            sys.exit(2)

    print(f"\n{len(selected) - len(survivors)}/{len(selected)} killed")
    if survivors:
        print("survivors: " + ", ".join(survivors))
        sys.exit(1)
    print("clean.\n")
