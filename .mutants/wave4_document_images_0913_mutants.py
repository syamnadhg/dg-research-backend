"""Mutation harness for wave 4 — IMAGES IN DOCUMENTS, the machine half, 2026-09-13.

⛔⛔ WHAT WAVE 4 MEASURED. Every HTML capture route deleted every image and its alt
text (`strip=['img', …]`): Gemini's first choice, Claude chat, Claude research's
panel scrape, the ChatGPT brief's only route. The routes that keep a platform's
own markdown kept its URLs, which no reader could load. Nothing ever fetched a
byte. And the fix itself adds the lens's WORST risk: the owner's machine fetching
links out of text a sharer may have prompted.

⭐⭐ THE MUTANTS COME FROM THOSE FAILURE MODES, NOT FROM THE REPAIR LIST.

⭐⭐ THE DIRECTION LABELS:

    "over"  · the machine keeps, fetches or trusts TOO MUCH — an unsafe address
              reached, a platform URL or a data: URI left in a saved document, a
              reference from another research trusted, a line of the document
              written to the log.
    "under" · back toward the measured defect — an image deleted, refetched,
              lost from one of the saves, or the event loop blocked while the
              round-robin should be polling.

⭐⭐ THE ONES THAT MATTER MOST, AND WHY:

  A9    — ⛔⛔⛔ THE PEER CHECK GOES. The name resolved public for the check and
          the connect went to 10.0.0.7 — DNS rebinding, the one refusal that has
          to happen INSIDE requests, before a byte of the request is written.
  R1    — ⛔⛔ REDIRECTS STOP BEING RE-CHECKED: a public host 302s to the router.
  A2/A1 — ⛔ `is_global` calls 64:ff9b::a00:1 (NAT64 → 10.0.0.1) and 224.0.0.1
          global. The two gaps the library leaves.
  U1-U3 — ⛔ a reference the web returned is written without checking it names
          THIS research and THESE bytes.
  F5    — ⛔⛔ an image that could not be kept keeps its platform URL — the exact
          broken box this wave exists to remove.
  K1-K9 — every save path: the per-agent save, three brief saves, the finalize
          re-save, two regen re-saves, and the consolidated build that glues them.
  E1    — the rehost runs on the event loop, and every other agent stops being
          polled for as long as the images take.

⭐⭐ REPAIR ROUND 1 (2026-09-14), the ones that matter most:

  T1/T2/T4 — ⛔⛔ the per-image deadline shuts nothing: a server trickling a byte
          at a time holds a worker thread for days. Killed only by the REAL TLS
          trickle tests — a fake response returns at once and measures nothing.
  M1/M3 — ⛔⛔ code is rewritten again, or the "<img> mention" guard WIDENS to any
          tag with nothing to write and a platform URL survives in prose.
  W2    — ⛔ any non-raster answer becomes a live link, not just a web page.
  T7    — ⛔ the timer lands between reads and a truncated image is stored.

⭐⭐ REPAIR ROUND 2 (2026-09-14), the ones that matter most:

  Q2    — ⛔⛔⛔ ANY PAGE ANSWER IS A LINK whatever the markup: Google's image host
          answers 400 text/html, so an unfetchable Gemini chart goes back into a
          share as a live platform URL. The citation fix stands on the shape rule.
  P1/P2 — ⛔⛔ a click-to-enlarge link keeps the signed platform URL around the image.
  H1/H8 — ⛔⛔ an abandoned rehost uploads and writes the shared cache; H8 marks the
          stop only after the fallback pass that reads that cache.
  H4    — ⛔⛔ round 2's own repair, back: the upload's timeouts capped at the time
          left strand a stored image behind a caption. H10-H12: the whole-request
          guard shuts nothing, and a web answering a byte at a time runs past the
          hard stop — killed only by the REAL local web tests.
  P6    — ⛔ a removed image leaves no text: `[ View full size](https://lh3…)`.

⭐⭐ REPAIR ROUND 3 (2026-09-14), the ones that matter most:

  ST1/ST2 — ⛔⛔ a Stop exits the process 3 s later; a document waiting on its image
          fetches was never written under a status saying it was. ST4/ST5 — the
          guard WIDENS to a pause, and a paused document's images become captions
          for good (the source address is gone from the text).
  CN1   — ⛔⛔ urllib3's create_connection: every address, 5 s each, before the
          deadline can watch a socket. Killed only through the REAL requests chain.
  CU1   — ⛔ an image cut off by one document's spent budget is a caption in every
          later document. CU2-CU5 — the rule WIDENS and a dead host, a login-only
          image or bytes already read are refetched by every document.
  UP1-UP3 — ⛔ a passing web failure is remembered; UP4 — a definite 4xx is not.
  LK1   — ⛔⛔ `[![Chart](ref)](https://lh3…=s0)` keeps a signed platform URL.
  LN2   — ⛔⛔ three chart URLs lift a wrong artifact past Claude's 30% check.

⭐⭐ REPAIR ROUND 4 (2026-09-14), the ones that matter most:

  EX1/EX2 — ⛔⛔ round 3's own repair, widened: ANY Stop takes the offline pass
          again, and the 24-hour pause limit (a Stop, no exit) captions every
          unsaved image for good. ST1-ST5 re-pointed at the exit, not the Stop.
  CP1   — ⛔⛔ a rebound name gets a TCP handshake with a LAN host before the peer
          check closes it.
  HD3/HD8 — a rehosted image in a heading pushes it past 80 characters and a
          finding takes the heading above as its title.
  BR1   — ⛔ a brief supplied with phase 1 skipped is pasted to every agent unrehosted.

⭐⭐ THE CLOSE OF WAVES 10.9 + 10.10 (2026-09-24). Wave 10.9's private-link scrub
runs after this harness's code on every path, and four mutants here survived it
(all killed at the wave-10.8 close). Two were real: their tests used lh3 and
oaiusercontent addresses, which the scrub now drops by itself, so P6 and LK1 are
killed on hosts the scrub keeps. P3 was equivalent and is retired. F2's line was
the defect — it hid a data: label from the scrub — so the line is gone and DF1
puts it back.

    python .mutants/wave4_document_images_0913_mutants.py
"""
from __future__ import annotations

import hashlib
import os
import re as _re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

RP = "research.py"
OURS = (RP,)

# ⛔ ONE LEG, THE ROOT ONE. Everything this wave touches is research.py, which the
# ROOT suite imports and the agent suite never does.
MINE_ROOT = "tests/test_document_images_0913.py"
MIN_SELECTED_ROOT = 200
ALL_ROOT = "tests/"

SURVIVOR_CONFIRMATIONS = 2
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
_INFLIGHT = Path(__file__).with_suffix(".inflight")


MUTANTS = [
    # ── the converter ─────────────────────────────────────────────────────────
    ('C1', RP, 'under',
     '⛔⛔ THE STRIP COMES BACK on the image-keeping path: `img` in the strip list means markdownify never calls convert_img, and every HTML route deletes every image and its alt again — the founding defect',
     [("strip=['script', 'style']).convert(html)",
       "strip=['img', 'script', 'style']).convert(html)")]),
    ('C2', RP, 'under',
     '⛔ THE DEFAULT FLIPS to the old output, so the five capture call sites that pass nothing lose their images while the one tracker that opts out looks correct',
     [('def html_to_markdown(html, keep_images=True):',
       'def html_to_markdown(html, keep_images=False):')]),
    ('C3', RP, 'over',
     'THE PANEL TRACKER STARTS KEEPING IMAGES: its length is `partial_text_len`, the input to Claude\'s length-sanity rejection, and its https harvest is the source list — image markup inflates the one and pollutes the other',
     [('        # Pass 1 — HTML across all targets.\n        for target in targets:\n            html_blob = await _try_html(target)\n            if html_blob and len(html_blob) > 200:\n                md = html_to_markdown(html_blob, keep_images=False)',
       '        # Pass 1 — HTML across all targets.\n        for target in targets:\n            html_blob = await _try_html(target)\n            if html_blob and len(html_blob) > 200:\n                md = html_to_markdown(html_blob)')]),
    ('C4', RP, 'under',
     'THE 32 PX BOUNDARY MOVES: an explicit `height="32"` icon is kept and costs a fetch',
     [('        if m and float(m.group(1)) <= _DOC_IMG_DECORATIVE_MAX_PX:',
       '        if m and float(m.group(1)) < _DOC_IMG_DECORATIVE_MAX_PX:')]),
    ('C5', RP, 'under',
     '⛔ THE DECORATIVE ROLE LIST WIDENS to `img` — an accessible chart that says what it is gets dropped as decoration',
     [('in ("presentation", "none"):',
       'in ("presentation", "none", "img"):')]),
    ('C6', RP, 'over',
     'FAVICON SERVICES STOP BEING DECORATIVE: every citation\'s google s2 / gstatic favicon becomes a fetch and an upload, forty of them eating the per-document budget before one chart',
     [('    return _doc_img_is_favicon_service(str(attrs.get("src") or ""))',
       '    return False')]),
    ('C7', RP, 'under',
     '⛔ MARKDOWNIFY\'S OWN convert_img COMES BACK: inside a heading or a table cell it returns the bare alt unless the DIRECT parent is listed, so a linked chart in a cell is lost',
     [('                out = _doc_img_markdown_for_tag(dict(el.attrs))',
       '                return super().convert_img(el, text, parent_tags)')]),
    ('C8', RP, 'under',
     'THE ANGLE BRACKETS GO: a src with a space or a parenthesis ends the destination early and half a platform URL is left in the text where no parser sees an image',
     [('        return f"![{alt}](<{src}>)"',
       '        return f"![{alt}]({src})"')]),
    ('C9', RP, 'under',
     'ALT IS NO LONGER ESCAPED: `Q[1] | Q2` closes the image early and splits the table cell',
     [(r'''    alt = re.sub(r"([\\\[\]|])", r"\\\1", alt)''',
       '    alt = alt')]),

    # ── the markdown forms ────────────────────────────────────────────────────
    ('F1', RP, 'over',
     '⛔ A REFERENCE DEFINITION AN IMAGE USED IS KEPT: the image is rewritten and the platform URL survives on its own line below it',
     [('        if key in used and key not in linked:\n            return ""',
       '        if False:\n            return ""')]),
    # ⛔ F2 RETIRED 2026-09-24 WITH THE LINE IT MUTATED ("an unused data: definition
    # is kept"). Since wave 10.9 `_doc_scrub_private_links` runs after this pass on
    # every path and drops a data: definition itself, so F2 survived — and its
    # output was the BETTER one: dropped here first, the definition hid its label
    # from the scrub and `[the csv][d]` stayed as literal brackets in any document
    # holding an image. The line is gone; DF1 puts it back. The scrub's own data:
    # rule is H2/H3 in wave109_docfunnel_mutants.py.
    ('DF1', RP, 'under',
     '⛔ THE IMAGE PASS DROPS data: DEFINITIONS AGAIN, before the scrub can read them: in any document holding an image a link to one is left as literal `[the csv][d]`',
     [('        key = _doc_img_label_key(m.group("label"))\n        if key in used and key not in linked:\n',
       '        dest = m.group("adest") if m.group("adest") is not None else m.group("dest")\n'
       '        if dest.strip()[:5].lower() == "data:":\n            return ""\n'
       '        key = _doc_img_label_key(m.group("label"))\n        if key in used and key not in linked:\n')]),
    ('F3', RP, 'over',
     'AN ESCAPED `\\![…](…)` IS TREATED AS AN IMAGE and its URL fetched — CommonMark says it is a literal bang and a link',
     [(r'''_DOC_IMG_MD_RE = re.compile(
    r"(?<!\\)!\[''',
       r'''_DOC_IMG_MD_RE = re.compile(
    r"!\[''')]),
    ('F4', RP, 'over',
     '⛔ RAW `<img>` IN EXPORTED MARKDOWN IS SKIPPED: its src — a data: URI or a platform URL — stays in the saved document',
     [('    text = _DOC_IMG_HTML_RE.sub(_html_img, text)',
       '    text = text')]),
    ('F5', RP, 'over',
     '⛔⛔⛔ AN IMAGE THAT COULD NOT BE KEPT KEEPS ITS PLATFORM URL — the broken box with alt text this wave exists to remove, and a sandbox:/blob: link in a permanent share',
     [('            return _slot(f"![{alt}]()", src)',
       '            return m.group(0)')]),
    ('F6', RP, 'over',
     'AN IMAGE WITH NO ALT THAT COULD NOT BE KEPT IS LEFT AS IT WAS, URL and all',
     [('        return _slot("", src)',
       '        return m.group(0)')]),
    ('F7', RP, 'under',
     'COLLAPSED AND SHORTCUT REFERENCES STOP RESOLVING: `![Chart][]` and `![Chart]` find no definition, and their definitions keep the platform URL',
     [('            key = _doc_img_label_key(m.group("label") or m.group("alt"))',
       '            key = _doc_img_label_key(m.group("label"))')]),

    # ── idempotence and the per-research cache ───────────────────────────────
    ('I1', RP, 'over',
     '⛔ A REFERENCE TO ANOTHER RESEARCH IS TRUSTED as already stored — a supplied brief can point a document at an object this research never owned',
     [('        if run.rid and m.group(1) == run.rid:',
       '        if run.rid:')]),
    ('I2', RP, 'under',
     '⛔⛔ REWRITTEN REFERENCES ARE NO LONGER RECOGNISED: the finalize re-save and the consolidated report send every ref to the fetch, which refuses a relative path — every image the per-agent save kept becomes a caption',
     [('    m = _DOC_IMG_REF_RE.match(src)\n    if m:\n        if run.rid',
       '    m = None\n    if m:\n        if run.rid')]),
    ('I3', RP, 'under',
     'THE CACHE IS NEVER READ: the same chart is fetched and uploaded once per document and once per repeat inside one',
     [('    hit = _doc_img_cache_get(run, key)',
       '    hit = _DOC_IMG_MISS')]),
    ('I4', RP, 'under',
     'A FAILED IMAGE IS NOT REMEMBERED: a dead host is hit again by every later document of the research, each time burning the per-document budget',
     [('    _doc_img_cache_put(run, key, cached)\n    return ref',
       '    if ref:\n        _doc_img_cache_put(run, key, cached)\n    return ref')]),
    ('I5', RP, 'over',
     '⛔ ONE CACHE FOR EVERY RESEARCH: a second research reuses the first one\'s reference, which names the wrong research and is served to nobody',
     [(r'''        self.cache_key = f"{self.uid}\x00{self.rid}"''',
       '        self.cache_key = "one-cache-for-every-research"')]),
    ('I6', RP, 'under',
     'THE PER-RESEARCH CACHE IS UNBOUNDED on a long-lived worker',
     [('    while len(bucket) > _DOC_IMG_CACHE_PER_RUN:',
       '    while False:')]),
    ('I7', RP, 'under',
     'THE CACHE KEEPS EVERY RESEARCH A WORKER EVER RAN',
     [('        while len(_doc_img_cache) > _DOC_IMG_CACHE_RUNS:',
       '        while False:')]),

    # ── limits ────────────────────────────────────────────────────────────────
    ('L1', RP, 'over',
     'THE 40-PER-DOCUMENT CAP GOES: a report with 500 images is 500 fetches and 500 uploads',
     [('    if run.stopped or run.attempts >= _DOC_IMG_MAX_PER_DOC or time.monotonic() >= run.deadline:',
       '    if run.stopped or time.monotonic() >= run.deadline:')]),
    ('L2', RP, 'under',
     'THE DOCUMENT DEADLINE STOPS BEING CHECKED between images, so a slow host holds the save for forty full timeouts',
     [('    if run.stopped or run.attempts >= _DOC_IMG_MAX_PER_DOC or time.monotonic() >= run.deadline:',
       '    if run.stopped or run.attempts >= _DOC_IMG_MAX_PER_DOC:')]),
    ('L3', RP, 'over',
     'ATTEMPTS ARE NEVER COUNTED, so the cap never binds',
     [('    run.attempts += 1\n    ref = cached = None',
       '    ref = cached = None')]),
    ('L4', RP, 'over',
     '⛔ NO TOKEN, FETCH ANYWAY: a legacy-mode machine downloads every image in the document and then has nowhere to put it',
     [('    if not run.token:\n        return _not_fetched("failed")\n',
       '')]),
    ('L5', RP, 'under',
     'THE TOKEN IS REFRESHED FOR EVERY IMAGE — forty forced Firebase refreshes for one document',
     [('    if not run.token_checked:',
       '    if True:')]),
    ('L6', RP, 'over',
     'NO OWNER, FETCH ANYWAY: an unpaired run fetches images it can never upload',
     [('    if not (run.uid and run.rid):',
       '    if not run.rid:')]),

    # ── the upload ────────────────────────────────────────────────────────────
    ('U1', RP, 'over',
     '⛔ THE RETURNED REF IS NOT CHECKED AGAINST THIS RESEARCH',
     [('    if (not m or m.group(1) != run.rid\n            or m.group(2)',
       '    if (not m\n            or m.group(2)')]),
    ('U2', RP, 'over',
     '⛔ THE RETURNED REF IS NOT CHECKED AGAINST THESE BYTES',
     [('            or m.group(2) != hashlib.sha256(data).hexdigest() or m.group(3) != ext):',
       '            or m.group(3) != ext):')]),
    ('U3', RP, 'over',
     'THE RETURNED REF\'S EXTENSION IS NOT CHECKED AGAINST THE SNIFF',
     [('            or m.group(2) != hashlib.sha256(data).hexdigest() or m.group(3) != ext):',
       '            or m.group(2) != hashlib.sha256(data).hexdigest()):')]),
    ('U4', RP, 'over',
     'ANY NON-ERROR STATUS COUNTS AS STORED: a 302 to a sign-in page or a 201 with some other body writes a ref',
     [('        if resp.status_code != 200:\n            return None\n        body = resp.json()',
       '        if resp.status_code >= 400:\n            return None\n        body = resp.json()')]),
    ('U5', RP, 'over',
     'THE UPLOAD FOLLOWS REDIRECTS, carrying the device bearer wherever the web is sent',
     [('                timeout=(5.0, 30.0),\n                allow_redirects=False,',
       '                timeout=(5.0, 30.0),\n                allow_redirects=True,')]),
    ('U6', RP, 'over',
     '⛔ `\\Z` BECOMES `$`: Python\'s `$` matches before a trailing newline, the web\'s anchored JS regex does not — a ref the renderer refuses is written',
     [(r'''\.(png|jpg|gif|webp)\Z")''',
       r'''\.(png|jpg|gif|webp)$")''')]),
    ('U7', RP, 'under',
     'THE BODY KEY DRIFTS from the route\'s contract (`research_id`) and every upload is refused',
     [('        json={"ownerUid": run.uid, "research_id": run.rid,',
       '        json={"ownerUid": run.uid, "researchId": run.rid,')]),

    # ── the bytes ─────────────────────────────────────────────────────────────
    ('B1', RP, 'over',
     'THE GIF SNIFF STOPS AT FOUR BYTES and stops mirroring the web\'s',
     [('b[:4] == b"GIF8" and b[4] in (0x37, 0x39) and b[5] == 0x61:',
       'b[:4] == b"GIF8":')]),
    ('B2', RP, 'over',
     'ANY RIFF FILE IS A WEBP — a WAV passes the sniff',
     [('b[:4] == b"RIFF" and b[8:12] == b"WEBP":',
       'b[:4] == b"RIFF":')]),
    ('B3', RP, 'under',
     'THE 48 PX BOUNDARY MOVES and a 48 px image is dropped',
     [('    if min(dims) < _DOC_IMG_MIN_PX:',
       '    if min(dims) <= _DOC_IMG_MIN_PX:')]),
    ('B4', RP, 'over',
     'ONLY THE LARGER SIDE COUNTS: a 1 px tracking strip 600 px wide is kept',
     [('    if min(dims) < _DOC_IMG_MIN_PX:',
       '    if max(dims) < _DOC_IMG_MIN_PX:')]),
    ('B5', RP, 'over',
     'THE 5 MB CAP GOES from the byte check — a decoded data: URI of any size is uploaded',
     [('    if not data or len(data) > _DOC_IMG_MAX_BYTES:',
       '    if not data:')]),
    ('B7', RP, 'over',
     'A HUGE data: URI IS DECODED BEFORE ITS SIZE IS CHECKED — the whole blob held twice in memory',
     [('    if len(b64) > 4 * -(-_DOC_IMG_MAX_BYTES // 3):\n        raise _DocImageRefused("failed")\n    try:',
       '    try:')]),
    ('B8', RP, 'under',
     'THE JPEG SEGMENT WALK SKIPS TWO BYTES SHORT and no ordinary JFIF file has readable dimensions',
     [('                i += 2 + seg',
       '                i += seg')]),
    ('B9', RP, 'under',
     'THE LOSSLESS WEBP HEIGHT IS READ FROM THE WRONG BITS',
     [('((bits >> 14) & 0x3FFF) + 1',
       '((bits >> 16) & 0x3FFF) + 1')]),
    ('B10', RP, 'over',
     'A PNG WITHOUT ITS IHDR CHUNK FIRST HAS DIMENSIONS READ OUT OF WHATEVER FOLLOWS',
     [('            if b[12:16] != b"IHDR":\n                return None\n',
       '')]),

    # ── where the machine may connect ─────────────────────────────────────────
    ('A1', RP, 'over',
     '⛔ MULTICAST PASSES — `is_global` calls 224.0.0.1 global',
     [('    return all(c.is_global and not c.is_multicast for c in candidates)',
       '    return all(c.is_global for c in candidates)')]),
    ('A2', RP, 'over',
     '⛔⛔ NAT64 IS NOT UNWRAPPED: `64:ff9b::a00:1` is global to `is_global` and reaches 10.0.0.1 on a NAT64 network',
     [('    if ip.version == 6 and (int(ip) >> 32) == 0x0064FF9B0000000000000000:',
       '    if False:')]),
    ('A3', RP, 'over',
     '⛔⛔ ONE PUBLIC ADDRESS IS ENOUGH: a name with a public and a private A record passes, and the connect picks the private one',
     [('    if not addrs or not all(_doc_img_address_is_public(a) for a in addrs):',
       '    if not addrs or not any(_doc_img_address_is_public(a) for a in addrs):')]),
    ('A4', RP, 'over',
     'A NAME THAT RESOLVES TO NOTHING PASSES — `all([])` is True',
     [('    if not addrs or not all(_doc_img_address_is_public(a) for a in addrs):',
       '    if not all(_doc_img_address_is_public(a) for a in addrs):')]),
    ('A5', RP, 'over',
     '⛔ PLAIN HTTP IS FETCHED — anyone on the path swaps the bytes that become a permanent shared image',
     [('    if parts.scheme.lower() != "https" or not parts.hostname:',
       '    if parts.scheme.lower() not in ("https", "http") or not parts.hostname:')]),
    ('A6', RP, 'over',
     'CREDENTIALS IN THE URL ARE SENT: requests turns `user:pw@` into Basic auth',
     [('    if parts.username is not None or parts.password is not None:\n        raise _DocImageRefused("refused")',
       '    if False:\n        raise _DocImageRefused("refused")')]),
    ('A7', RP, 'over',
     'ANY PORT IS FETCHED — public hosts\' admin ports become reachable from a prompt',
     [('    if port not in (None, 443):',
       '    if False:')]),
    ('A8', RP, 'over',
     'BACKSLASHES, WHITESPACE AND CONTROL BYTES IN THE URL PASS — the parser-differential shapes where urlsplit and urllib3 disagree about the host',
     [('    if len(url) > _DOC_IMG_MAX_URL_CHARS or _DOC_IMG_URL_BAD_CHARS_RE.search(url):',
       '    if len(url) > _DOC_IMG_MAX_URL_CHARS:')]),
    ('A9', RP, 'over',
     '⛔⛔⛔ THE PEER CHECK GOES: a name resolved public for the check, then the connect went to 10.0.0.7 — DNS rebinding — and the request is written to it',
     [('            _doc_img_check_peer(sock)\n            guard.watch(sock)\n            return sock',
       '            guard.watch(sock)\n            return sock')]),
    ('A10', RP, 'over',
     '⛔ AN UNREADABLE PEER FAILS OPEN',
     [('    except (OSError, IndexError, TypeError):\n        peer = ""',
       '    except (OSError, IndexError, TypeError):\n        peer = "93.184.216.34"')]),
    ('A11', RP, 'over',
     '⛔ THE ENVIRONMENT IS TRUSTED: proxy variables and ~/.netrc credentials ride along',
     [('    session.trust_env = False',
       '    session.trust_env = True')]),
    ('A12', RP, 'over',
     'COOKIES ARE KEPT between hops — a redirect chain can plant one and read it back',
     [('    session.cookies.set_policy(DefaultCookiePolicy(allowed_domains=[]))',
       '    session.cookies.set_policy(DefaultCookiePolicy())')]),

    # ── the fetch ─────────────────────────────────────────────────────────────
    ('R1', RP, 'over',
     '⛔⛔ ONLY THE FIRST HOP IS CHECKED: a public host 302s to the router and the router is fetched',
     [('            _doc_img_check_url(url, deadline)\n            if time.monotonic() >= deadline:',
       '            if _hop == 0:\n                _doc_img_check_url(url, deadline)\n            if time.monotonic() >= deadline:')]),
    ('R2', RP, 'over',
     '⛔ REQUESTS FOLLOWS REDIRECTS ITSELF, past every per-hop check',
     [('            resp = session.get(url, stream=True, allow_redirects=False,',
       '            resp = session.get(url, stream=True, allow_redirects=True,')]),
    ('R3', RP, 'over',
     'A FOURTH REDIRECT IS FOLLOWED',
     [('        for _hop in range(_DOC_IMG_MAX_REDIRECTS + 1):',
       '        for _hop in range(_DOC_IMG_MAX_REDIRECTS + 2):')]),
    ('R3b', RP, 'under',
     'THE THIRD REDIRECT IS REFUSED — CDNs routinely use two or three',
     [('        for _hop in range(_DOC_IMG_MAX_REDIRECTS + 1):',
       '        for _hop in range(_DOC_IMG_MAX_REDIRECTS):')]),
    ('R5', RP, 'over',
     'THE READ OVERSHOOTS THE CAP by up to a chunk — the bound is 5 MB + 1 byte, not "about 5 MB"',
     [('        chunk = resp.raw.read(min(65536, _DOC_IMG_MAX_BYTES + 1 - len(buf)),',
       '        chunk = resp.raw.read(65536,')]),
    ('R6', RP, 'over',
     'A DECLARED 2 GB BODY IS DOWNLOADED UP TO THE CAP before it is refused',
     [('    if declared.isdigit() and int(declared) > _DOC_IMG_MAX_BYTES:',
       '    if False:')]),
    ('R7', RP, 'over',
     'THE BODY IS DECOMPRESSED WHILE IT IS COUNTED — a gzip bomb expands before the cap sees it',
     [('                              decode_content=False)',
       '                              decode_content=True)')]),
    ('R8', RP, 'under',
     'A SLOW BODY IS NEVER CUT OFF by the document deadline',
     [('        if time.monotonic() >= deadline:\n            raise _DocImageRefused("failed")\n        chunk = resp.raw.read(',
       '        chunk = resp.raw.read(')]),

    # ── the funnel ────────────────────────────────────────────────────────────
    ('E1', RP, 'under',
     '⛔⛔ THE REHOST RUNS ON THE EVENT LOOP: while forty images download, no other agent is polled',
     [('        out = await asyncio.wait_for(\n            _doc_img_until_stop(asyncio.get_running_loop().run_in_executor(\n                pool, ctx.run, _doc_images_rewrite_sync, text, run)),\n            timeout=_DOC_IMG_DOC_BUDGET_SEC + _DOC_IMG_HARD_STOP_GRACE_SEC)',
       '        out = _doc_images_rewrite_sync(text, run)')]),
    ('E2', RP, 'under',
     'NO HARD STOP: one hung resolver holds the document save indefinitely',
     [('        out = await asyncio.wait_for(\n            _doc_img_until_stop(asyncio.get_running_loop().run_in_executor(\n                pool, ctx.run, _doc_images_rewrite_sync, text, run)),\n            timeout=_DOC_IMG_DOC_BUDGET_SEC + _DOC_IMG_HARD_STOP_GRACE_SEC)',
       '        out = await _doc_img_until_stop(asyncio.get_running_loop().run_in_executor(\n            pool, ctx.run, _doc_images_rewrite_sync, text, run))')]),
    ('E3', RP, 'over',
     '⛔ THE HARD STOP HANDS BACK THE RAW TEXT — every platform URL saved as it came',
     [('        run = _DocImageRun(uid, rid, label, 0.0)\n        run.stats["dropped"] += dropped\n        try:\n            out = _doc_images_rewrite_sync(text, run)\n        except Exception:\n            return text',
       '        return text')]),
    ('E4', RP, 'over',
     '⛔ THE STATS LINE CARRIES DOCUMENT TEXT — run logs are declared to hold no topic',
     [('    _doc_img_log_stats(label, run.stats)\n    return out',
       '    _doc_img_log_stats(f"{label} {text[:40]}", run.stats)\n    return out')]),
    ('E5', RP, 'over',
     'THE FAST PATH ONLY LOOKS FOR `![`: a document whose only images are raw `<img>` tags skips the rehost with their data: URIs intact',
     [('    if not text or not ("![" in text or _DOC_IMG_HTML_RE.search(text)):',
       '    if not text or "![" not in text:')]),
    ('E6', RP, 'under',
     'THE DECORATIVE COUNT IS NEVER RESET and every later document reports the whole run\'s drops',
     [('    dropped, _doc_img_decorative_pending = _doc_img_decorative_pending, 0',
       '    dropped = _doc_img_decorative_pending')]),

    # ── the consumers ─────────────────────────────────────────────────────────
    ('K1', RP, 'under',
     '⛔⛔ THE PER-AGENT SAVE LOSES THE FUNNEL: the first write of every report — local .md, Firestore, and the text the finalize and consolidated builds read — carries platform URLs',
     [('    text = await _rehost_document_images(text, label=name)\n\n    n_chars = len(text)',
       '    n_chars = len(text)')]),
    ('K2', RP, 'over',
     '⛔ THE FUNNEL MOVES AHEAD OF THE TOPIC GUARD: an off-topic document\'s images are fetched and stored under the research before it is thrown away',
     [('    text = reject_off_topic_text(text, queue_dir, name, agent_key,',
       '    text = await _rehost_document_images(text, label=name)\n    text = reject_off_topic_text(text, queue_dir, name, agent_key,')]),
    ('K3', RP, 'under',
     'A SUPPLIED BRIEF IS SAVED UNREHOSTED — a pasted data: URI goes straight to Firestore',
     [('                # brief.md, the document, or the Phase 2 paste.\n                brief_text = await _rehost_document_images(brief_text, label="Brief")',
       '                # brief.md, the document, or the Phase 2 paste.')]),
    ('K4', RP, 'under',
     '⛔ THE EXTRACTED BRIEF IS SAVED UNREHOSTED — the one brief route that exists',
     [('                # ⭐ Wave 4: rehost the brief\'s images before either write.\n                brief_text = await _rehost_document_images(brief_text, label="Brief")',
       '                # ⭐ Wave 4: rehost the brief\'s images before either write.')]),
    ('K5', RP, 'under',
     'THE REGENERATED BRIEF IS SAVED UNREHOSTED',
     [('                        brief_text = p1_new["text"]\n                        brief_text = await _rehost_document_images(brief_text, label="Brief")',
       '                        brief_text = p1_new["text"]')]),
    ('K6', RP, 'under',
     '⛔ THE FINALIZE RE-SAVE AND THE CONSOLIDATED BUILD READ UNREHOSTED RESULTS — a salvaged partial overwrites the document with platform URLs',
     # Wave 10.9: the re-save's test became `_p2_needs_resave(r)` (a kept agent
     # is not re-written), and on 09-22 the whole block moved into
     # `_p2_persist_reports` so a test could drive the writes. Re-indented twice;
     # the mutant — the funnel call deleted — is unchanged both times.
     [('    await _rehost_result_texts(results)\n    for name, r in results.items():\n        if _p2_needs_resave(r):',
       '    for name, r in results.items():\n        if _p2_needs_resave(r):')]),
    ('K7', RP, 'under',
     'THE RESUME-WITH-INPUT REGEN RE-SAVE IS UNFUNNELED',
     [('                    # Rewrite documents\n                    await _rehost_result_texts(results)',
       '                    # Rewrite documents')]),
    ('K8', RP, 'under',
     'THE PHASE-3-GATE RETRY RE-SAVE IS UNFUNNELED',
     [('                # Rewrite documents from the fresh results\n                await _rehost_result_texts(results)',
       '                # Rewrite documents from the fresh results')]),
    ('K9', RP, 'under',
     '⛔ THE RESULTS FUNNEL REWRITES A COPY: every image is fetched and uploaded, and the loops below still write the platform URLs',
     [('            entry["text"] = await _rehost_document_images(entry["text"], label=str(agent_name))',
       '            await _rehost_document_images(entry["text"], label=str(agent_name))')]),
    # ── repair round 1 (2026-09-14): one image's deadline ────────────────────
    ('T1', RP, 'under',
     '⛔⛔ THE IMAGE TIMER IS NEVER STARTED: a server that trickles a byte at a time holds the worker thread until it stops, the defect the repair exists for',
     [('    guard.start()\n    try:\n        for _hop in',
       '    try:\n        for _hop in')]),
    ('T2', RP, 'under',
     '⛔⛔ A CONNECTION IS NEVER HANDED TO THE DEADLINE: the timer fires and shuts nothing',
     [('            _doc_img_check_peer(sock)\n            guard.watch(sock)\n            return sock',
       '            _doc_img_check_peer(sock)\n            return sock')]),
    ('T3', RP, 'under',
     'THE DEADLINE CLOSES THE DUP INSTEAD OF SHUTTING THE CONNECTION: closing one descriptor wakes no read blocked on another',
     [('                    s.shutdown(socket.SHUT_RDWR)',
       '                    s.close()')]),
    ('T4', RP, 'under',
     '⛔ THE DEADLINE KEEPS THE CONNECTED SOCKET, NOT A DUP: TLS detaches it, and the shutdown lands on a dead descriptor',
     [('            dup = sock.dup()',
       '            dup = sock')]),
    ('T5', RP, 'over',
     'A CONNECTION OPENED AFTER THE DEADLINE IS ACCEPTED — a redirect hop starts a fresh unbounded read',
     [('            if dup is not None and not self.expired:',
       '            if dup is not None:')]),
    ('T6', RP, 'under',
     'THE FETCH NEVER CLOSES ITS DEADLINE: a timer thread per image lingers for the whole budget and every dup leaks a descriptor',
     [('        guard.close()\n        session.close()\n\n\ndef _doc_img_upload(',
       '        session.close()\n\n\ndef _doc_img_upload(')]),
    ('T7', RP, 'over',
     '⛔ THE TIMER LANDS BETWEEN READS AND THE SHORT BODY IS RETURNED: a truncated image with a readable header is stored',
     [('                if guard.expired:\n                    raise _DocImageRefused("failed")\n',
       '')]),
    ('T8', RP, 'under',
     'ONE IMAGE MAY SPEND THE WHOLE DOCUMENT BUDGET — a single slow host captions the other thirty-nine',
     [('_doc_img_fetch(src, min(run.deadline, time.monotonic() + _DOC_IMG_PER_IMAGE_SEC)))',
       '_doc_img_fetch(src, run.deadline))')]),
    ('T9', RP, 'under',
     'ONE IMAGE OUTLIVES THE DOCUMENT DEADLINE, straight into the hard stop',
     [('_doc_img_fetch(src, min(run.deadline, time.monotonic() + _DOC_IMG_PER_IMAGE_SEC)))',
       '_doc_img_fetch(src, time.monotonic() + _DOC_IMG_PER_IMAGE_SEC))')]),
    ('T10', RP, 'under',
     'THE TIMER FIRES LATE — the deadline is a suggestion',
     [('        self._timer = _threading.Timer(max(0.0, deadline - time.monotonic()), self.expire)',
       '        self._timer = _threading.Timer(max(0.0, deadline - time.monotonic()) + 5.0, self.expire)')]),
    ('X1', RP, 'under',
     '⛔ THE REHOST USES THE LOOP\'S DEFAULT POOL again: in --serve a stuck fetch takes a thread every other to_thread call needs',
     [('                pool, ctx.run, _doc_images_rewrite_sync, text, run)),',
       '                None, ctx.run, _doc_images_rewrite_sync, text, run)),')]),
    ('X2', RP, 'under',
     'THE CONTEXT IS NOT COPIED into the worker: a machine-scoped log line from the token refresh lands in the run log',
     [('pool, ctx.run, _doc_images_rewrite_sync, text, run)),',
       'pool, _doc_images_rewrite_sync, text, run)),')]),
    ('X3', RP, 'under',
     'THE REHOST\'S POOL IS UNBOUNDED',
     [('max_workers=_DOC_IMG_WORKERS, thread_name_prefix="doc-images",',
       'max_workers=64, thread_name_prefix="doc-images",')]),
    ('X4', RP, 'under',
     '⛔⛔ THE POOL\'S END IS LEFT TO THE COLLECTOR. Measured 09-15: with nothing else holding the pool, CPython frees it on return and the executor\'s own weakref ends the worker — so "the threads end" passes either way, and the earlier wording (idle threads for the whole process, taking the serve-stop SIGUSR1) was only half true: the mask is X5\'s. What is true is that the funnel stops owning the end. Hold the frame — a profiler, a debugger, a traceback kept for a log line, a runtime that does not refcount — and the idle rehost thread lives on for the process',
     [('        pool.shutdown(wait=False, cancel_futures=True)',
       '        pass')]),
    ('X5', RP, 'under',
     '⛔⛔ A REHOST THREAD TAKES SIGNALS: a SIGINT/SIGTERM the main thread blocked to hold a press is delivered to it instead',
     [('        initializer=_doc_img_block_signals)',
       '        initializer=None)')]),
    ('X6', RP, 'over',
     '⛔⛔ THE REHOST THREAD BLOCKS THE FAULT SIGNALS TOO: a SIGSEGV in ssl or a C extension there is undefined, and the serve process dies with no traceback',
     [('_signal.pthread_sigmask(_signal.SIG_BLOCK, _signal.valid_signals() - faults)',
       '_signal.pthread_sigmask(_signal.SIG_BLOCK, _signal.valid_signals())')]),

    # ── repair round 1: login-only images, the user agent ────────────────────
    ('G1', RP, 'under',
     'A 401/403 IS FOLDED BACK INTO "failed" — the count of what a login-only image misses is gone',
     [('                    bucket = "login" if resp.status_code in (401, 403) else "failed"',
       '                    bucket = "failed"')]),
    ('G2', RP, 'over',
     '⛔ THE USER AGENT NAMES THE PRODUCT to whatever host a sharer\'s prompt chose',
     [('"User-Agent": "Mozilla/5.0 (compatible; image fetch)",',
       '"User-Agent": "Mozilla/5.0 (compatible; SuperResearch image fetch)",')]),

    # ── repair round 1: a citation after "!" ─────────────────────────────────
    ('W1', RP, 'under',
     '⛔ A WEB PAGE AFTER AN EXCLAMATION MARK BECOMES A CAPTION: the citation, its link and its finding are lost',
     [('            return "\\\\" + m.group(0)',
       '            return f"![{alt}]()"')]),
    ('W2', RP, 'over',
     '⛔ ANY NON-RASTER ANSWER IS A LINK: an SVG — or a platform URL behind a JSON error — is written back as a live link instead of a caption',
     [('                if _doc_img_sniff_ext(data) is None and _doc_img_is_page(resp):',
       '                if _doc_img_sniff_ext(data) is None:')]),
    ('W3', RP, 'under',
     'A RASTER SERVED AS text/html IS WRITTEN BACK AS A LINK instead of stored',
     [('                if _doc_img_sniff_ext(data) is None and _doc_img_is_page(resp):',
       '                if _doc_img_is_page(resp):')]),
    ('W4', RP, 'under',
     'THE PAGE ANSWER IS NOT KEPT: it becomes a caption and is cached as a failure',
     [('        if refusal.kind == "linked":\n            cached = _DOC_IMG_LINKED\n            if may_link:\n                ref = _DOC_IMG_LINKED\n',
       '')]),
    ('W5', RP, 'over',
     'A CACHED PAGE IS COUNTED AS A REUSED IMAGE in the stats line',
     [('run.stats["linked" if hit is _DOC_IMG_LINKED else "reused" if hit else "failed"] += 1',
       'run.stats["reused" if hit else "failed"] += 1')]),
    ('W6', RP, 'under',
     'THE WRITTEN-BACK LINK IS NOT ESCAPED: every renderer still reads an image, and the link is still lost',
     [('            return "\\\\" + m.group(0)',
       '            return m.group(0)')]),

    # ── repair round 1: code is quoted text ──────────────────────────────────
    ('M1', RP, 'over',
     '⛔⛔ CODE IS NOT MASKED: an HTML sample in a fence is rewritten into a reference and its URL fetched',
     [('    text, unmask = _doc_img_mask_code(text)\n',
       '    unmask = str\n')]),
    ('M2', RP, 'over',
     '⛔ A BARE <img> MENTION IN PROSE IS DELETED — "Use the  element"',
     [('        if not out and not any(str(v).strip() for v in attrs.values()):\n            return m.group(0)\n',
       '')]),
    ('M3', RP, 'over',
     '⛔⛔ THE MENTION GUARD WIDENS to any tag with nothing to write: an <img> whose source cannot be written keeps its platform URL in prose',
     [('        if not out and not any(str(v).strip() for v in attrs.values()):',
       '        if not out:')]),
    ('M8', RP, 'over',
     '⛔⛔ THE MENTION GUARD LOOKS AT `src` ALONE: `<img srcset="https://platform/a.png 2x">` or `data-src` is kept byte for byte and a raw-HTML renderer loads it',
     [('        if not out and not any(str(v).strip() for v in attrs.values()):',
       '        if not out and not str(attrs.get("src") or "").strip():')]),
    ('M10', RP, 'under',
     'THE MENTION GUARD NARROWS to a tag with no attributes at all: "give <img alt> a value" is deleted from prose',
     [('        if not out and not any(str(v).strip() for v in attrs.values()):',
       '        if not out and not attrs:')]),
    ('M4', RP, 'over',
     '⛔ A CODE SPAN CROSSES PARAGRAPHS: one stray backtick hides every image until the next one, platform URLs and all',
     [('            if m or not line.strip():',
       '            if m:')]),
    ('M5', RP, 'over',
     'AN ESCAPED BACKTICK OPENS A CODE SPAN and hides the image after it',
     [('            if text[p_start + s - 1:p_start + s] == "\\\\":\n                i += 1\n                continue\n',
       '')]),
    ('M6', RP, 'over',
     'A SHORTER FENCE CLOSES A LONGER ONE: the sample inside a four-backtick fence is rewritten',
     [('"{" + str(len(fence)) + r",}[ \\t]*\\r?\\Z")',
       '"{3,}" + r"[ \\t]*\\r?\\Z")')]),
    ('M9', RP, 'over',
     '⛔ A CRLF FENCE NEVER CLOSES: every image after the first code block keeps its platform URL',
     [('r",}[ \\t]*\\r?\\Z")',
       'r",}[ \\t]*\\Z")')]),
    ('M7', RP, 'over',
     '⛔ THE PLACEHOLDER DELIMITER IS ONE FIXED NUL: a document holding that byte gets code pasted into its prose',
     [('    sep = "\\x00" * (longest + 1)',
       '    sep = "\\x00"')]),

    # ── repair round 1: definitions, odd destinations, snippets ──────────────
    ('D1', RP, 'under',
     '⛔ A DEFINITION AN IMAGE SHARES WITH A LINK IS REMOVED: `[see][1]` renders as literal brackets',
     [('        if key in used and key not in linked:',
       '        if key in used:')]),
    ('N1', RP, 'over',
     '⛔ THE LEFTOVER PASS IS GONE: `![c](https://x/File_(a_(b)).png)` keeps its platform URL',
     [('    text = _doc_img_blank_leftovers(text, run)\n',
       '')]),
    ('N2', RP, 'over',
     'AN UNPARSEABLE IMAGE NAMED LIKE A DEFINITION RESOLVES THROUGH IT and leaves `(url)` glued behind the reference',
     [('            if (m.group("label") is None and m.string.startswith("(", m.end())\n'
       '                    and _doc_img_leftover_close(m.string, m.end() + 1) >= 0):\n'
       '                return m.group(0)\n',
       '')]),
    ('N8', RP, 'over',
     '⛔ THE UNPARSEABLE GUARD CATCHES EVERY REFERENCE FORM: `![fig][l](2024)` and `![fig][](x)` render the definition\'s platform image and are never rehosted',
     [('            if (m.group("label") is None and m.string.startswith("(", m.end())',
       '            if (m.string.startswith("(", m.end())')]),
    ('N9', RP, 'over',
     '⛔ THE GUARD PASSES ON AN IMAGE THE LEFTOVER PASS LEAVES ALONE: `![fig](see below` renders the definition\'s platform image, unrehosted',
     [('\n                    and _doc_img_leftover_close(m.string, m.end() + 1) >= 0):',
       '):')]),
    ('N10', RP, 'over',
     'THE GUARD SCANS FROM A CHARACTER THAT IS NOT `(`: `(chart: ![fig] below)` reads `below)` as a destination and the image keeps its definition URL',
     [('m.group("label") is None and m.string.startswith("(", m.end())\n',
       'm.group("label") is None\n')]),
    ('N3', RP, 'under',
     '⛔ THE LEFTOVER PASS BLANKS A FINISHED IMAGE — a stored `/document-images/…` destination is captioned in the saved document and its object orphaned. Measured 09-15: NOT "every image the main pass stored", as this said — the main pass hides everything it writes in slots until after this pass. What DOES arrive is a stored reference carrying one whitespace character the main pattern will not accept before its `)` — a non-breaking space out of an HTML capture, a stray CR/VT/FF: the main pattern drops the image, `.strip()` hands THIS pass the bare reference, and it is blanked end to end through `_rehost_document_images`. Pinned both ways — that document through the funnel, and `_doc_img_blank_leftovers` itself for the finished images only a reordering of the two passes would send here',
     [('    if not dest or _DOC_IMG_REF_RE.match(dest):',
       '    if not dest:')]),
    ('N4', RP, 'over',
     'THE LEFTOVER SCAN IGNORES NESTING and stops at the first `)`, leaving half a URL',
     [('        if c == "(":\n            depth += 1\n',
       '')]),
    ('N6', RP, 'over',
     'THE LEFTOVER SCAN IGNORES ESCAPES: `\\)` ends the destination early',
     [('        if c == "\\\\":\n            i += 2\n            continue\n',
       '')]),
('N7', RP, 'over',
     'THE LEFTOVER PASS IGNORES AN ESCAPED BANG: literal `\\![x](…)` prose with an unparseable destination is rewritten as if it were an image',
     [(r'''_DOC_IMG_LEFTOVER_RE = re.compile(
    r"(?<!\\)!\[''',
       r'''_DOC_IMG_LEFTOVER_RE = re.compile(
    r"!\[''')]),
    ('N5', RP, 'over',
     'A DEFINITION TITLE ON THE NEXT LINE IS LEFT BEHIND as a stray quoted line',
     [('r"(?:(?:[ \\t]+|[ \\t]*\\r?\\n[ \\t]*)(?:\\"',
       'r"(?:(?:[ \\t]+)(?:\\"')]),
    ('S1', RP, 'under',
     'FINDINGS SNIPPETS KEEP IMAGE MARKUP — "Revenue grew 40% !Chart"',
     [('        snippet = _FIND_MD_IMG_RE.sub("", snippet)\n',
       '')]),
    ('S2', RP, 'under',
     'A LINKED IMAGE LEAVES `[](url)` IN THE SNIPPET',
     [("""    r'\\[[ \\t]*!\\[(?:\\\\.|[^\\]\\\\\\n]){0,2000}\\]\\([^)\\n]*\\)[ \\t]*\\]\\([^)\\n]*\\)'\n    r'|(?<!\\\\)!\\[""",
       """    r'(?<!\\\\)!\\[""")]),
    ('S3', RP, 'under',
     'A CITATION THE REHOST WROTE BACK READS `everything\\!source` in its card',
     [('        snippet = snippet.replace("\\\\![", "![")\n',
       '')]),

    # ── repair round 2 (2026-09-14): a link around an image ──────────────────
    ('P1', RP, 'over',
     '⛔⛔ THE LINK AROUND AN IMAGE IS NEVER LOOKED AT: a click-to-enlarge anchor keeps the signed platform URL in the saved document and every share',
     [('    text = _doc_img_unwrap_self_links(text, slot_re, slots)\n',
       '')]),
    ('P2', RP, 'over',
     '⛔ A LINK TO THE IMAGE ITSELF STAYS — only data:/blob:/sandbox: targets go, and `[![Chart](ref)](https://lh3…)` keeps its platform URL',
     [('        if sources and (href in sources or href.lower().startswith(("data:", "blob:", "sandbox:"))):',
       '        if sources and href.lower().startswith(("data:", "blob:", "sandbox:")):')]),
    # ⛔ P3 RETIRED 2026-09-24 AS AN EQUIVALENT MUTANT ("a link to blob:, data: or
    # sandbox: around an image stays"). Since wave 10.9 `_doc_scrub_private_links`
    # runs after this pass on every path and unwraps every inline link to those
    # schemes, keeping its text — exactly what this rule hands back — so no
    # document can tell the two apart. The schemes are measured at the scrub (H2,
    # H3, I1, I2 in wave109_docfunnel_mutants.py). If the scrub ever stops
    # following this pass on some path, P3 is real again and belongs here.
    ('P4', RP, 'under',
     '⛔ EVERY LINK AROUND AN IMAGE GOES: the article a chart links to — its source — is lost',
     [('        if sources and (href in sources or href.lower().startswith(("data:", "blob:", "sandbox:"))):',
       '        if sources:')]),
    ('P5', RP, 'under',
     '⛔ ANY IMAGE SOURCE IN THE DOCUMENT COUNTS, not the one inside the link: `per [Reuters](url)` loses its link because a captioned image elsewhere used that address',
     [('        sources = {slots[int(i)][1] for i in slot_re.findall(inner)}',
       '        sources = {src for _out, src in slots}')]),
    # ⭐ Since wave 10.9 the scrub also drops an lh3 link, so P6 is killed on a public
    # image host, where nothing but this rule can take the link out.
    ('P6', RP, 'over',
     '⛔ A LINK AROUND A REMOVED IMAGE STAYS: `[](S)` and `[ View full size](S)` — a removed image leaves no text, and its link keeps the image\'s own source',
     [('        sources = {slots[int(i)][1] for i in slot_re.findall(inner)}',
       '        sources = {slots[int(i)][1] for i in slot_re.findall(inner) if slots[int(i)][0]}')]),
    ('P8', RP, 'over',
     'THE SLOT CARRIES NO NONCE: document text that looks like a slot is replaced by an image it never held',
     [(r'''    slot_tag = f"{os.urandom(6).hex()}:"''',
       r'''    slot_tag = ":"''')]),
    ('P7', RP, 'over',
     'A LINK WITH A TITLE IS NOT RECOGNISED: the converter writes the anchor\'s title, and `[![Chart](<S>)](S "Open")` keeps S',
     [(r'''    r"(?:[ \t\n]+(?:\"(?:[^\"\\]|\\.)*+\"|'(?:[^'\\]|\\.)*+'|\((?:[^()\\]|\\.)*+\)))?[ \t\n]*\)")''',
       r'''    r"[ \t\n]*\)")''')]),

    # ── repair round 2: a citation after "!" whatever the page answered ──────
    ('Q1', RP, 'under',
     '⛔ A NON-200 WEB PAGE IS NOT A PAGE: a news site answering this plain client with 403, or 404/5xx, deletes the citation',
     [('                    if _doc_img_is_page(resp):\n                        raise _DocImageRefused("linked", bucket)\n',
       '')]),
    ('Q2', RP, 'over',
     '⛔⛔⛔ ANY PAGE ANSWER IS A LINK whatever the markup: Google\'s image host answers 400 text/html, so an unfetchable Gemini chart goes back into the share as a live platform URL',
     [('ref = _doc_img_resolve_src(src, run, _doc_img_citation_shaped(m.string, m.start(), src, angled))',
       'ref = _doc_img_resolve_src(src, run, True)')]),
    ('Q3', RP, 'over',
     '⛔ AN IMAGE THE CONVERTER WROTE (angle brackets) CAN BE A CITATION: an `<img>` whose host answers a page is kept as a link',
     [('    if angled or bang <= 0:\n        return False\n    prev',
       '    if bang <= 0:\n        return False\n    prev')]),
    ('Q4', RP, 'over',
     'AN IMAGE AT THE START OF THE TEXT READS THE LAST CHARACTER AS ITS NEIGHBOUR and can be kept as a link',
     [('    if angled or bang <= 0:',
       '    if angled:')]),
    ('Q5', RP, 'over',
     '⛔ AN IMAGE AFTER A SPACE OR ON ITS OWN LINE CAN BE A CITATION — the ordinary image layout, kept as a link when no answer says otherwise',
     [('    if prev.isspace() or prev in "[(|<>\\x00":',
       '    if prev in "[(|<>\\x00":')]),
    ('Q6', RP, 'over',
     'AN IMAGE OPENING A LINK CAN BE A CITATION: `[![Chart](https://…)](page)` keeps the image URL as a link',
     [('    if prev.isspace() or prev in "[(|<>\\x00":',
       '    if prev.isspace() or prev in "(|<>\\x00":')]),
    ('Q7', RP, 'over',
     'AN IMAGE ON THE LINE AFTER A CODE FENCE CAN BE A CITATION: the mask\'s NUL reads as a glued word',
     [('    if prev.isspace() or prev in "[(|<>\\x00":',
       '    if prev.isspace() or prev in "[(|<>":')]),
    ('Q8', RP, 'over',
     'ANY SCHEME WITH A HOST CAN BE A CITATION: `ftp://…` after "!" is kept as a link',
     [('    if parts.scheme.lower() not in ("https", "http") or not host:',
       '    if not host:')]),
    ('Q9', RP, 'over',
     'CREDENTIALS IN A CITATION\'S URL ARE KEPT in the saved document',
     [('    if parts.username is not None or parts.password is not None:\n        return False\n    if _doc_img_is_platform_host(host):',
       '    if _doc_img_is_platform_host(host):')]),
    ('Q10', RP, 'over',
     '⛔ THE PLATFORMS\' PRODUCT HOSTS CAN BE CITATIONS: `files.oaiusercontent.com` after "!" with no answer is kept as a link',
     [('    return _is_platform_host(host) or any(host == h',
       '    return any(host == h')]),
    ('Q11', RP, 'over',
     '⛔ GEMINI\'S IMAGE HOST CAN BE A CITATION: `lh3.googleusercontent.com` answering an HTML error is kept as a live link',
     [('for h in _DOC_IMG_PLATFORM_IMAGE_HOSTS)',
       'for h in ())')]),
    ('Q12', RP, 'over',
     'A PATH ENDING IN AN IMAGE EXTENSION CAN BE A CITATION: `…/q3.png` is kept as a link',
     [('    return not _DOC_IMG_IMAGE_PATH_RE.search(parts.path)',
       '    return True')]),
    ('Q13', RP, 'under',
     '⛔ A CITATION NEVER FETCHED IS DELETED: http, no token, the cap or the budget spent — `40%![Reuters]()`',
     [('        if may_link:\n            run.stats["linked"] += 1\n            return _DOC_IMG_LINKED\n',
       '')]),
    ('Q14', RP, 'under',
     'AN http CITATION GOES TO THE FETCH, which refuses it, and is deleted',
     [('    if src[:5].lower() == "http:":\n',
       '    if False:\n')]),
    ('Q15', RP, 'over',
     '⛔ A CACHED PAGE VERDICT IS A LINK FOR EVERY LATER OCCURRENCE: an image-shaped `![source](url)` after a citation of the same address keeps the URL',
     [('        if hit is _DOC_IMG_LINKED and not may_link:\n            hit = None\n',
       '')]),
    ('Q16', RP, 'under',
     'THE PAGE VERDICT IS CACHED ONLY WHEN IT WAS WRITTEN AS A LINK: a caption first caches a failure and the citation after it is deleted',
     [('            cached = _DOC_IMG_LINKED\n            if may_link:',
       '            if may_link:\n                cached = _DOC_IMG_LINKED')]),
    ('Q17', RP, 'over',
     'A PAGE ANSWER WRITTEN AS A CAPTION IS COUNTED AS LINKED in the stats line',
     [('        run.stats["linked" if ref is _DOC_IMG_LINKED else refusal.fallback] += 1',
       '        run.stats[refusal.kind] += 1')]),
    ('Q18', RP, 'over',
     'A 200 PAGE WRITTEN AS A CAPTION IS COUNTED AS LINKED — its fallback bucket is gone',
     [('                    raise _DocImageRefused("linked", "failed")',
       '                    raise _DocImageRefused("linked")')]),

    # ── repair round 2: an abandoned rehost stores nothing, remembers nothing ─
    ('H1', RP, 'over',
     '⛔⛔ THE RUN IS NEVER MARKED STOPPED: after the hard stop or a cancelled task the worker uploads an image nothing references and writes the shared cache',
     [('        run.stopped = True\n        if not isinstance(e, Exception):',
       '        if not isinstance(e, Exception):')]),
    ('H2', RP, 'over',
     '⛔ THE UPLOAD IGNORES THE STOP: a cancelled rehost still stores the image it was fetching',
     [('    if run.stopped or end - time.monotonic() < _DOC_IMG_UPLOAD_MIN_SEC:\n        return _DOC_IMG_MISS\n',
       '    if end - time.monotonic() < _DOC_IMG_UPLOAD_MIN_SEC:\n        return _DOC_IMG_MISS\n')]),
    ('H3', RP, 'over',
     '⛔ AN UPLOAD STARTS WITH NO TIME TO FINISH: the guard cuts it off while the web saves — a caption in the document and an object nothing references',
     [('    if run.stopped or end - time.monotonic() < _DOC_IMG_UPLOAD_MIN_SEC:\n        return _DOC_IMG_MISS\n',
       '    if run.stopped or end - time.monotonic() <= 0:\n        return _DOC_IMG_MISS\n')]),
    ('H4', RP, 'under',
     '⛔⛔ THE UPLOAD\'S TIMEOUTS ARE CAPPED AT THE TIME LEFT (the round-2 repair): a web saving longer than that stores the image while the client gives up — a kept image becomes a caption AND a stranded object',
     [('                timeout=(5.0, 30.0),\n                allow_redirects=False,',
       '                timeout=(min(5.0, max(0.001, run.deadline - time.monotonic())),\n'
       '                         min(30.0, max(0.001, run.deadline - time.monotonic()))),\n'
       '                allow_redirects=False,')]),
    ('H9', RP, 'over',
     'THE UPLOAD MAY RUN RIGHT UP TO THE HARD STOP: the funnel stops waiting as the answer lands, and a stored image is captioned',
     [('    end = run.deadline + _DOC_IMG_HARD_STOP_GRACE_SEC - _DOC_IMG_UPLOAD_MARGIN_SEC',
       '    end = run.deadline + _DOC_IMG_HARD_STOP_GRACE_SEC')]),
    ('H10', RP, 'over',
     '⛔⛔ THE UPLOAD\'S GUARD IS NEVER STARTED: a web answering a byte at a time holds the upload past the hard stop, and it stores an image the captioned document never references',
     [('    guard.start()\n    try:\n        try:\n            resp = session.post(',
       '    try:\n        try:\n            resp = session.post(')]),
    ('H11', RP, 'over',
     '⛔ AN HTTPS UPLOAD CONNECTION IS NOT WATCHED — production\'s: only the socket timeouts bound it',
     [('    class _WatchedHTTPSConnection(_u3c.HTTPSConnection):\n        def _new_conn(self):\n            sock = super()._new_conn()\n            guard.watch(sock)\n',
       '    class _WatchedHTTPSConnection(_u3c.HTTPSConnection):\n        def _new_conn(self):\n            sock = super()._new_conn()\n')]),
    ('H12', RP, 'over',
     'AN HTTP UPLOAD CONNECTION IS NOT WATCHED — development\'s: only the socket timeouts bound it',
     [('    class _WatchedHTTPConnection(_u3c.HTTPConnection):\n        def _new_conn(self):\n            sock = super()._new_conn()\n            guard.watch(sock)\n',
       '    class _WatchedHTTPConnection(_u3c.HTTPConnection):\n        def _new_conn(self):\n            sock = super()._new_conn()\n')]),
    ('H13', RP, 'over',
     'THE UPLOAD\'S SESSION IS NEVER CLOSED: its pooled connection outlives the upload',
     [('        guard.close()\n        session.close()\n    ref = body.get(',
       '        guard.close()\n    ref = body.get(')]),
    ('H14', RP, 'over',
     'THE UPLOAD\'S GUARD IS NEVER CLOSED: its timer thread lives on to the end of the grace for every image',
     [('        guard.close()\n        session.close()\n    ref = body.get(',
       '        session.close()\n    ref = body.get(')]),
    ('H15', RP, 'under',
     '⛔ AN UPLOAD NOT STARTED FOR LACK OF TIME IS REMEMBERED AS A FAILED IMAGE: every later document of the research — each with a fresh budget — captions it without trying',
     [('            run.stats["failed"] += 1\n            return None\n        run.stats["stored" if ref else "failed"] += 1',
       '            ref = cached = None\n        run.stats["stored" if ref else "failed"] += 1')]),
    ('H5', RP, 'over',
     '⛔ AN ABANDONED WORKER WRITES THE SHARED CACHE under the next document',
     [('    if run.stopped:\n        return None\n    _doc_img_cache_put(run, key, cached)',
       '    _doc_img_cache_put(run, key, cached)')]),
    ('H6', RP, 'over',
     'A CANCELLED REHOST FETCHES ON through the rest of the document',
     [('    if run.stopped or run.attempts >= _DOC_IMG_MAX_PER_DOC or time.monotonic() >= run.deadline:',
       '    if run.attempts >= _DOC_IMG_MAX_PER_DOC or time.monotonic() >= run.deadline:')]),
    ('H7', RP, 'under',
     '⛔ A CANCELLED TASK IS SWALLOWED: the funnel writes captions and returns, and the stop press does not stop the pipeline',
     [('        if not isinstance(e, Exception):\n            raise\n',
       '')]),
    ('H8', RP, 'over',
     '⛔⛔ THE STOP IS MARKED ONLY AFTER THE FALLBACK PASS: a worker that comes back while that pass reads the cache still writes it',
     [('        run.stopped = True\n        if not isinstance(e, Exception):\n            raise\n',
       '        if not isinstance(e, Exception):\n            run.stopped = True\n            raise\n        stopped_run = run\n'),
      ('            out = _doc_images_rewrite_sync(text, run)\n        except Exception:\n            return text\n    finally:',
       '            out = _doc_images_rewrite_sync(text, run)\n        except Exception:\n            return text\n        finally:\n            stopped_run.stopped = True\n    finally:')]),
    # ── repair round 3 (2026-09-14): a Stop writes the document at once ──────
    # ⭐ Round 4 re-pointed ST1-ST5 at the scheduled exit (`_doc_img_exit_coming`).
    ('ST1', RP, 'under',
     '⛔⛔ AN EXIT ALREADY SCHEDULED STILL FETCHES: a skipped or salvaged partial waits on its images, the process exits 3 s after the Stop, and the document said to be saved is never written',
     [('        if _doc_img_exit_coming():\n            raise _DocImgStopRequested()\n        pool = _doc_img_executor()',
       '        pool = _doc_img_executor()')]),
    ('ST2', RP, 'under',
     '⛔⛔ AN EXIT SCHEDULED DURING THE WAIT IS NEVER SEEN: the document waits for its fetches past the process exit',
     [('            if _doc_img_exit_coming():\n                raise _DocImgStopRequested()\n    finally:',
       '    finally:')]),
    ('ST3', RP, 'under',
     '⛔ THE WAIT IS NOT STOP-AWARE AT ALL: the executor future is awaited straight, only the hard stop ends it',
     [('            _doc_img_until_stop(asyncio.get_running_loop().run_in_executor(\n                pool, ctx.run, _doc_images_rewrite_sync, text, run)),',
       '            asyncio.get_running_loop().run_in_executor(\n                pool, ctx.run, _doc_images_rewrite_sync, text, run),')]),
    ('ST4', RP, 'under',
     '⛔⛔ THE EXIT GUARD WIDENS TO A PAUSE before the call: a paused finalize writes captions, and a caption never becomes an image again',
     [('        if _doc_img_exit_coming():\n            raise _DocImgStopRequested()\n        pool',
       '        if _doc_img_exit_coming() or _controls.is_pause():\n            raise _DocImgStopRequested()\n        pool')]),
    ('ST5', RP, 'under',
     '⛔⛔ THE EXIT GUARD WIDENS TO A PAUSE during the wait: a pause mid-fetch captions the document for good',
     [('            if _doc_img_exit_coming():\n                raise _DocImgStopRequested()\n    finally:',
       '            if _doc_img_exit_coming() or _controls.is_pause():\n                raise _DocImgStopRequested()\n    finally:')]),
    ('ST6', RP, 'under',
     'THE STOP IS LOOKED FOR EVERY 5 s: past the 3 s exit',
     [('_DOC_IMG_STOP_POLL_SEC = 0.25',
       '_DOC_IMG_STOP_POLL_SEC = 5.0')]),

    # ── repair round 3: what is remembered for the rest of the research ──────
    # ⭐ Re-aimed 2026-09-21 (wave 10.9, repair round 2): the same rule now also
    # lets a lookup the CLOCK ended out of the cache (`timed_out`).
    ('CU1', RP, 'under',
     '⛔ AN IMAGE CUT OFF BY THE DOCUMENT\'S SPENT BUDGET IS CACHED AS FAILED: a chart that started with 3 s left is a caption in every later document, each with a fresh budget',
     [('    if cut_off and (timed_out or time.monotonic() >= run.deadline):\n        return ref\n',
       '')]),
    ('CU2', RP, 'under',
     '⛔ THE CUT-OFF RULE WIDENS to any failure while reading: a dead host that fails at once is refetched by every document',
     [('    if cut_off and (timed_out or time.monotonic() >= run.deadline):',
       '    if cut_off:')]),
    ('CU3', RP, 'under',
     'A DEFINITE VERDICT AT THE DEADLINE IS FORGOTTEN: a login-only image answered as the budget ran out is fetched again by every document',
     [('        cut_off = reading and refusal.kind == "failed"',
       '        cut_off = reading')]),
    ('CU4', RP, 'under',
     'BYTES ALREADY READ COUNT AS CUT OFF: a non-image that arrived by the deadline is refetched by every document',
     [('                _doc_img_fetch(src, min(run.deadline, time.monotonic() + _DOC_IMG_PER_IMAGE_SEC)))\n        reading = False\n',
       '                _doc_img_fetch(src, min(run.deadline, time.monotonic() + _DOC_IMG_PER_IMAGE_SEC)))\n')]),
    ('CU5', RP, 'under',
     '⛔ A CONNECTION THE DEADLINE SHUT (its requests error) IS CACHED AS FAILED — only the timer\'s own refusal is spared',
     [('        run.stats["failed"] += 1\n        cut_off = reading\n',
       '        run.stats["failed"] += 1\n')]),
    ('UP1', RP, 'under',
     '⛔ A 503 FROM THE WEB IS CACHED for the rest of the research: the chart is a caption in every later document though the web recovered',
     [('        if resp.status_code >= 500:\n            return _DOC_IMG_MISS\n',
       '')]),
    ('UP2', RP, 'under',
     '⛔ A NETWORK ERROR ON THE UPLOAD IS CACHED as a failed image for the rest of the research',
     [('        except (OSError, _DocImageRefused) as exc:',
       '        except ZeroDivisionError as exc:')]),
    ('UP3', RP, 'under',
     'THE GUARD REFUSING THE UPLOAD\'S CONNECTION IS CACHED — the run\'s clock, not the image',
     [('        except (OSError, _DocImageRefused) as exc:',
       '        except OSError as exc:')]),
    ('UP4', RP, 'over',
     '⛔ A DEFINITE 4xx IS NOT REMEMBERED: every document fetches and uploads an image the web will always refuse',
     [('        if resp.status_code >= 500:',
       '        if resp.status_code >= 400:')]),

    # ── repair round 3 fixup: which upload ERRORS pass ───────────────────────
    ('UE1', RP, 'over',
     '⛔ EVERY OSError PASSES AGAIN: a bad FE base URL or a missing CA bundle refetches the image for every later document',
     [('    return isinstance(exc, (_DocImageRefused, requests.ConnectionError, requests.Timeout,',
       '    return isinstance(exc, (_DocImageRefused, OSError, requests.ConnectionError, requests.Timeout,')]),
    ('UE2', RP, 'over',
     '⛔ A CERTIFICATE THAT FAILS VERIFICATION PASSES (SSLError is a ConnectionError): refetched by every document',
     [('    import requests\n    if isinstance(exc, requests.exceptions.SSLError):\n        return False\n',
       '    import requests\n')]),
    ('UE3', RP, 'over',
     'A DEFINITE UPLOAD ERROR IS NOT REMEMBERED — the classification is read and ignored',
     [('                return _DOC_IMG_MISS\n            return None\n        if resp.status_code >= 500:',
       '                return _DOC_IMG_MISS\n            return _DOC_IMG_MISS\n        if resp.status_code >= 500:')]),
    ('UE4', RP, 'under',
     '⛔⛔ A TLS HANDSHAKE THE GUARD CUT IS CACHED: its SSLError reads as a certificate failure, and the chart is a caption in every later document',
     [('            if guard.expired or _doc_img_upload_error_passes(exc):',
       '            if _doc_img_upload_error_passes(exc):')]),
    ('UE5', RP, 'under',
     'A TIMEOUT ON THE UPLOAD IS CACHED as a failed image',
     [('(_DocImageRefused, requests.ConnectionError, requests.Timeout,',
       '(_DocImageRefused, requests.ConnectionError,')]),
    ('UE6', RP, 'under',
     'AN ANSWER CUT OFF MID-BODY IS CACHED as a failed image',
     [('                            requests.exceptions.ChunkedEncodingError,\n',
       '')]),
    ('UE7', RP, 'under',
     'A BARE SOCKET RESET OR TIMEOUT IS CACHED as a failed image',
     [('                            ConnectionError, TimeoutError))',
       '                            ))')]),
    ('UE8', RP, 'under',
     'THE GUARD REFUSING A NEW UPLOAD CONNECTION IS CACHED — it passes the catch and fails the classification',
     [('    return isinstance(exc, (_DocImageRefused, requests.ConnectionError, requests.Timeout,',
       '    return isinstance(exc, (requests.ConnectionError, requests.Timeout,')]),

    # ── repair round 3: a link around an image to a platform host ────────────
    # ⭐ Since wave 10.9 the scrub also drops an lh3 or oaiusercontent link, so LK1 is
    # killed on the platform hosts the scrub keeps (gstatic, a chatgpt.com address
    # outside a conversation), where nothing but this rule can take the link out.
    ('LK1', RP, 'over',
     '⛔⛔ A CLICK-TO-ENLARGE LINK TO ANOTHER ADDRESS ON A PLATFORM HOST STAYS: `[![Chart](ref)](https://encrypted-tbn0.gstatic.com/…)` keeps a platform URL in the document and every share',
     [('        if sources and _doc_img_is_platform_host(href_host):\n            return inner\n',
       '')]),

    # ── repair round 3: one image connection is bounded by the image clock ───
    ('CN1', RP, 'under',
     '⛔⛔ urllib3\'s create_connection COMES BACK: thirty silent addresses, 5 s each, hold the worker ~150 s before the deadline can watch a socket',
     [('            sock = _doc_img_connect(self._dns_host, self.port, guard.deadline, self.socket_options)',
       '            sock = super()._new_conn()')]),
    ('CN2', RP, 'under',
     'EVERY RESOLVED ADDRESS IS TRIED — the cap goes',
     [('                                allowed_gai_family())[:_DOC_IMG_CONNECT_ADDRS]',
       '                                allowed_gai_family())')]),
    ('CN3', RP, 'under',
     '⛔ EACH CONNECT GETS THE FULL 5 s whatever is left of the image\'s time',
     [('            sock.settimeout(min(_DOC_IMG_TIMEOUT[0], left))',
       '            sock.settimeout(_DOC_IMG_TIMEOUT[0])')]),
    # ⭐ Re-aimed 2026-09-21 (wave 10.9): the connect's own deadline check moved into
    # `_doc_img_lookup`, the one bounded lookup both the URL check and the connect use.
    ('CN4', RP, 'over',
     'A LOOKUP STARTS AFTER THE IMAGE\'S DEADLINE',
     [('    left = min(_DOC_IMG_LOOKUP_TIMEOUT, deadline - time.monotonic())\n    if left <= 0:\n        raise TimeoutError("lookup")\n',
       '    left = min(_DOC_IMG_LOOKUP_TIMEOUT, deadline - time.monotonic())\n')]),
    ('CN5', RP, 'under',
     'A CONNECT STARTS WITH NO TIME LEFT: a socket is made and a negative timeout raises out of the loop, leaking it',
     [('        left = deadline - time.monotonic()\n        if left <= 0:\n            out_of_time = True\n            break\n',
       '        left = deadline - time.monotonic()\n')]),

    # ── repair round 3: image URLs do not count toward a length check ────────
    ('LN1', RP, 'over',
     '⛔ THE PROSE LENGTH COUNTS IMAGE URLS: three signed chart URLs lift a wrong artifact past every check',
     [('    if not text or "![" not in text:\n        return len(text or "")\n    return len(_DOC_IMG_MD_RE.sub(',
       '    return len(text or "")\n    return len(_DOC_IMG_MD_RE.sub(')]),
    ('LN9', RP, 'under',
     'THE PROSE LENGTH DROPS THE ALT TOO — a caption a reader sees stops counting',
     [("        lambda m: f\"![{m.group('alt')}]()\" if m.group(\"inline\") is not None else m.group(0), text))",
       "        lambda m: \"\" if m.group(\"inline\") is not None else m.group(0), text))")]),
    ('LN2', RP, 'over',
     '⛔⛔ CLAUDE\'S LENGTH-SANITY CHECK MEASURES THE URLS: a 4,000-character wrong artifact with three chart URLs passes the 30% check and is saved as the report',
     [('            _sanity_len = _doc_img_prose_len(text)',
       '            _sanity_len = len(text)')]),
    ('LN3', RP, 'over',
     'THE HTML CAPTURE FLOOR COUNTS IMAGE URLS: a nine-word ack with one chart passes as a report',
     [('                if md_text and _doc_img_prose_len(md_text) > 100:',
       '                if md_text and len(md_text) > 100:')]),
    ('LN4', RP, 'over',
     'THE FRAME DENSITY FLOOR COUNTS IMAGE URLS',
     [('                if md_text and _doc_img_prose_len(md_text) > 500:',
       '                if md_text and len(md_text) > 500:')]),
    ('LN5', RP, 'over',
     'THE COPY HIJACK\'S HTML FLOOR COUNTS IMAGE URLS',
     [('            if md and _doc_img_prose_len(md) >= min_chars:',
       '            if md and len(md) >= min_chars:')]),
    ('LN6', RP, 'over',
     'CHATGPT\'S T2 HTML FLOOR COUNTS IMAGE URLS',
     [('    if md and _doc_img_prose_len(md) > 2000:\n        if _is_sources_not_document(md, platform="chatgpt"):',
       '    if md and len(md) > 2000:\n        if _is_sources_not_document(md, platform="chatgpt"):')]),
    ('LN7', RP, 'over',
     '⛔ GEMINI\'S T1 2000-CHARACTER FLOOR COUNTS IMAGE URLS: a chat-side ack with a few charts ships as the report',
     [('    if md and _doc_img_prose_len(md) > 2000:\n        if _is_sources_not_document(md, platform="generic"):',
       '    if md and len(md) > 2000:\n        if _is_sources_not_document(md, platform="generic"):')]),
    ('LN8', RP, 'over',
     'CLAUDE CHAT-MODE\'S HTML FLOOR COUNTS IMAGE URLS',
     [('            if md_chat and _doc_img_prose_len(md_chat) > 100:',
       '            if md_chat and len(md_chat) > 100:')]),

    # ── repair round 4 (2026-09-14): the offline pass needs an EXIT, not a Stop ──
    ('EX1', RP, 'under',
     '⛔⛔ ANY STOP TAKES THE OFFLINE PASS AGAIN before the call: the 24-hour pause limit stops the run with no exit, and every unsaved image of its partials is a caption for good',
     [('        if _doc_img_exit_coming():\n            raise _DocImgStopRequested()\n        pool = _doc_img_executor()',
       '        if _controls.is_stop():\n            raise _DocImgStopRequested()\n        pool = _doc_img_executor()')]),
    ('EX2', RP, 'under',
     '⛔⛔ ANY STOP ENDS THE WAIT AGAIN: a gate-wait cancel or a hard reset mid-fetch captions the document though nothing exits',
     [('            if _doc_img_exit_coming():\n                raise _DocImgStopRequested()\n    finally:',
       '            if _controls.is_stop():\n                raise _DocImgStopRequested()\n    finally:')]),
    ('EX3', RP, 'under',
     'AN EXIT WITH NO STOP PRESSED STILL FETCHES: an update\'s exit lands while the document waits on its images',
     [('    return bool(_exit_scheduled)',
       '    return bool(_exit_scheduled) and _controls.is_stop()')]),
    ('EX4', RP, 'under',
     '⛔ THE EXIT HELPER NO LONGER MARKS THE EXIT: every Stop button press fetches past the process exit',
     [('    _exit_scheduled = True\n    # Clear currentRunId before the os._exit lands.',
       '    # Clear currentRunId before the os._exit lands.')]),

    # ── repair round 4: the last raw floor on converter output ───────────────
    ('LN10', RP, 'over',
     '⛔ CLAUDE\'S ARTIFACT-PANEL DOM FLOOR COUNTS IMAGE URLS: a partial panel with three signed chart URLs passes as the report and T3 never runs',
     [('        if md_dom and _doc_img_prose_len(md_dom) > 2000:',
       '        if md_dom and len(md_dom) > 2000:')]),

    # ── repair round 4: no socket for an address that is not public ──────────
    ('CP1', RP, 'over',
     '⛔⛔ THE CONNECT SKIPS NOTHING: a rebound name gets a TCP handshake with a LAN host before the peer check closes it',
     [('        if not _doc_img_address_is_public(addr[0]):\n            skipped = True\n            continue\n',
       '')]),
    ('CP3', RP, 'under',
     'A NAME THAT ANSWERS ONLY LAN HOSTS IS A PASSING FAILURE, not the refusal the peer check gave it',
     [('    raise _DocImageRefused("refused" if skipped and not tried and not out_of_time else "failed")',
       '    raise _DocImageRefused("failed")')]),
    ('CP4', RP, 'over',
     'A PUBLIC HOST THAT DID NOT ANSWER IS A REFUSAL because a private answer was skipped first',
     [('    raise _DocImageRefused("refused" if skipped and not tried and not out_of_time else "failed")',
       '    raise _DocImageRefused("refused" if skipped and not out_of_time else "failed")')]),
    ('CP5', RP, 'under',
     '⛔ THE RULE READS THE HOST NAME, not the address: every image host is skipped and every image is a caption',
     [('        if not _doc_img_address_is_public(addr[0]):',
       '        if not _doc_img_address_is_public(host):')]),

    # ── repair round 4: a heading's image is not its title ───────────────────
    ('HD1', RP, 'over',
     '⛔ SECTIONS KEEP THE IMAGE MARKUP: `![Logo](/document-images/…) Market overview` is a section title in the analysis view and the findings fallback',
     [(r'''[t for t in map(_find_heading_title,
                                       re.findall(r'^#{1,3}\s+(.+)$', content, re.MULTILINE)) if t]''',
       r"""re.findall(r'^#{1,3}\s+(.+)$', content, re.MULTILINE)""")]),
    ('HD2', RP, 'over',
     'AN IMAGE-ONLY HEADING IS AN EMPTY SECTION',
     [(r"""re.findall(r'^#{1,3}\s+(.+)$', content, re.MULTILINE)) if t]""",
       r"""re.findall(r'^#{1,3}\s+(.+)$', content, re.MULTILINE))]""")]),
    ('HD9', RP, 'under',
     '⛔ FIXUP\'S OWN DEFECT BACK — TITLED AFTER THE COUNT AND THE DEDUPE: a logo heading and its bold line are two "Overview" sections; two image-only headings skip the bold fallback',
     [(r'''[t for t in map(_find_heading_title,
                                       re.findall(r'^#{1,3}\s+(.+)$', content, re.MULTILINE)) if t]''',
       r"""re.findall(r'^#{1,3}\s+(.+)$', content, re.MULTILINE)"""),
      ('                sections = list(dict.fromkeys(sections))[:20]  # Dedupe\n',
       '                sections = list(dict.fromkeys(sections))[:20]  # Dedupe\n'
       '            sections = [t for t in map(_find_heading_title, sections) if t]\n')]),
    ('HD10', RP, 'over',
     'A BOLD SECTION LINE KEEPS ITS IMAGE CAPTION: `![Chart]() Quarterly revenue`',
     [('sections = sections + [t for t in map(_find_heading_title, bold_sections + numbered)\n'
       '                                       if 5 <= len(t) <= 80]',
       'sections = sections + bold_sections + numbered')]),
    ('HD3', RP, 'under',
     '⛔ THE FINDINGS HEADING KEEPS ITS IMAGE: past 80 characters, and a finding under it takes the heading above as its title',
     [('        heading = _find_heading_title(raw)',
       '        heading = raw')]),
    ('HD4', RP, 'under',
     'AN IMAGE-ONLY HEADING ENDS NO SECTION: a finding under it is titled by the heading before',
     [('            headings.append((hm.start(), ""))',
       '            pass')]),
    ('HD5', RP, 'under',
     'THE 80-CHARACTER LIMIT MEASURES THE RAW HEADING, image URL and all',
     [('        elif 2 <= len(heading) <= 80:',
       '        elif 2 <= len(raw) <= 80:')]),
    ('HD6', RP, 'over',
     'THE SPACE AN IMAGE LEFT IS KEPT: `Q3  results`',
     [(r'''    return re.sub(r"[ \t]{2,}", " ", out).strip()''',
       '    return out.strip()')]),
    ('HD7', RP, 'over',
     'A HEADING WITH NO IMAGE IS REWRITTEN TOO: its own spacing changes',
     [('    out = _FIND_MD_IMG_RE.sub("", text)\n    if out == text:\n        return text\n',
       '    out = _FIND_MD_IMG_RE.sub("", text)\n')]),
    ('HD8', RP, 'under',
     '⛔ THE HEADING REGEX CAPS THE RAW LINE AT 80 AGAIN: a rehosted image drops the heading from the findings',
     [(r"""_FIND_HEADING_RE = re.compile(r'^#{2,4}\s+(.+)$', re.MULTILINE)""",
       r"""_FIND_HEADING_RE = re.compile(r'^#{2,4}\s+(.{2,80})$', re.MULTILINE)""")]),

    # ── repair round 4: a brief supplied with phase 1 skipped ────────────────
    ('BR1', RP, 'over',
     '⛔ THE SKIP BRANCH LOSES ITS REHOST: a pasted data: URI or a platform URL goes to every phase-2 agent and stays in brief.md',
     [('            brief_text = await _rehost_skipped_brief(queue_dir, brief_text, _loaded_path)\n            brief_artifact = BriefArtifact(text=brief_text, url="")',
       '            brief_artifact = BriefArtifact(text=brief_text, url="")')]),
    ('BR2', RP, 'over',
     'THE INLINE BRIEF\'S FILE IS NEVER NAMED: the paste is rehosted and brief.md keeps the URLs',
     [('                    _loaded_path = Path(brief_file)\n',
       '')]),
    ('BR3', RP, 'over',
     'THE RUN\'S brief.md IS NEVER REWRITTEN: a resume and the phase-2 attachment read the platform URLs',
     [('            local.write_text(current[:len(current) - len(brief_text)] + out, encoding="utf-8")',
       '            pass')]),
    ('BR4', RP, 'over',
     '⛔ ANY SOURCE FILE REWRITES THE RUN\'S brief.md: an owner\'s own --brief-file overwrites the copy a RESUME already has — the document phase 3 ingests and phase 2 attaches. Measured 09-15: it makes no NEW document, as this said — with no brief.md the read raises first and only a fault line is logged, which is why the "never rewritten" test passed on it',
     [('        same_file = Path(loaded_from).resolve() == local.resolve()',
       '        same_file = True')]),
    ('BR5', RP, 'over',
     'A GATE BRIEF IS HANDED BACK UNREHOSTED',
     [('    if loaded_from is None or out == brief_text:\n        return out\n',
       '    if loaded_from is None or out == brief_text:\n        return brief_text\n')]),
    ('BR6', RP, 'over',
     'A FILE BRIEF IS HANDED BACK UNREHOSTED though its file was rewritten',
     [('            "WARN")\n    return out\n\n\ndef html_to_markdown(',
       '            "WARN")\n    return brief_text\n\n\ndef html_to_markdown(')]),
    ('BR7', RP, 'over',
     '⛔ FIXUP\'S OWN DEFECT BACK — brief.md IS REWRITTEN WHEN NOTHING CHANGED: a brief with no image loses its CRLF bytes',
     [('    if loaded_from is None or out == brief_text:\n        return out\n',
       '    if loaded_from is None:\n        return out\n')]),
    ('BR8', RP, 'over',
     '⛔ FIXUP\'S OWN DEFECT BACK — A FIXED HEADER IS WRITTEN BACK: `# Research Brief: EV batteries` gains a second `# Research Brief` above it',
     [('local.write_text(current[:len(current) - len(brief_text)] + out, encoding="utf-8")',
       'local.write_text(f"# Research Brief\\n\\n{out}", encoding="utf-8")')]),
    ('BR9', RP, 'over',
     'A brief.md THAT NO LONGER HOLDS THE BRIEF IS CUT AT A GUESSED OFFSET and overwritten',
     [('        if current.endswith(brief_text):\n',
       '        if True:\n')]),

    # ── wave 9 (2026-09-16): pictures survive the clock ──────────────────────
    #
    # ⛔⛔ A CLOCK EXPIRY WAS REPORTED AS A REFUSAL, and refusals are remembered for
    # the whole research. One private answer skipped, the image's deadline breaking
    # the loop before any public address was tried, and `skipped and not tried` was
    # true — so the image was a caption in EVERY later document of that research.
    ('W9A1', RP, 'under',
     '⛔⛔ THE CLOCK IS A REFUSAL AGAIN: a private answer skipped and the deadline breaking before any public address was tried is cached as "refused", and that chart is a caption in every later document of the research',
     [('    raise _DocImageRefused("refused" if skipped and not tried and not out_of_time else "failed")',
       '    raise _DocImageRefused("refused" if skipped and not tried else "failed")')]),
    ('W9A2', RP, 'under',
     '⛔ THE TIME BREAK IS NEVER MARKED, so the raise below cannot tell "nothing public to try" from "the budget ran out first" — the same cached caption by the other half of the wiring',
     [('            out_of_time = True\n            break\n',
       '            break\n')]),

    # ⛔⛔ A BOLD PSEUDO-HEADING WHOSE IMAGE WAS STORED WAS DROPPED. The 5-80 bound
    # measured the RAW line, image markup and all, while the '##' path strips first
    # and has no bound at all — the same section survived one way and not the other.
    ('W9B1', RP, 'under',
     '⛔ THE BOLD CAPTURE IS BOUNDED AT 80 RAW CHARACTERS AGAIN: `**![Chart](/document-images/…/<64 hex>.png) Quarterly revenue**` is 126 raw characters and stops being a section, though the same line written `## …` still is',
     [("bold_sections = re.findall(r'^\\*\\*(.{1,400})\\*\\*\\s*$', content, re.MULTILINE)",
       "bold_sections = re.findall(r'^\\*\\*(.{5,80})\\*\\*\\s*$', content, re.MULTILINE)")]),
    ('W9B2', RP, 'under',
     '⛔ THE NUMBERED-BOLD CAPTURE IS BOUNDED AT 80 RAW CHARACTERS AGAIN: `**1. ![Chart](…) Quarterly revenue**` loses its section to its own image',
     [("numbered = re.findall(r'^\\*\\*\\d+[\\.\\)]\\s*(.{1,400})\\*\\*', content, re.MULTILINE)",
       "numbered = re.findall(r'^\\*\\*\\d+[\\.\\)]\\s*(.{5,80})\\*\\*', content, re.MULTILINE)")]),
    ('W9B3', RP, 'over',
     'THE WIDENED CAPTURE REACHES meta.json UNBOUNDED: with the title bound gone, a 300-character bold sentence is a section title in the analysis view',
     [('                                       if 5 <= len(t) <= 80]',
       '                                       if t]')]),
    ('W9B4', RP, 'under',
     'THE LOWER BOUND STOPS CARRYING THE TRUTHINESS FILTER: an image-ONLY bold line strips to "" and comes back as an empty section',
     [('                                       if 5 <= len(t) <= 80]',
       '                                       if 0 <= len(t) <= 80]')]),

    # ⛔ THE REJECTION LINE PRINTED A NUMBER THE GATE NEVER WEIGHED: the floors
    # measure prose (image destinations left out), the messages printed len(). A
    # panel with three signed chart URLs logged a figure far ABOVE the floor it had
    # just failed, and the rejection read as a machine fault.
    ('W9C1', RP, 'under',
     '⛔ GEMINI\'S T1 REJECTION PRINTS THE RAW LENGTH AGAIN: "returned 6,400 chars … below 2000-char threshold"',
     [('        log(f"[{label}] T1 HTML→MD returned {_doc_img_prose_len(md)} chars of prose "',
       '        log(f"[{label}] T1 HTML→MD returned {len(md)} chars of prose "')]),
    ('W9C2', RP, 'under',
     '⛔ CLAUDE\'S T2 PANEL REJECTION PRINTS THE RAW LENGTH AGAIN, beside the floor it just failed',
     [('            log(f"[{label}] T2 HTML→MD returned {_doc_img_prose_len(md_dom)} chars of "',
       '            log(f"[{label}] T2 HTML→MD returned {len(md_dom)} chars of "')]),
]


def sh(args, **kw):
    return subprocess.run(args, capture_output=True, text=True, **kw)


def _mark(mid: str, fname: str) -> None:
    _INFLIGHT.write_text(f"{mid}\t{fname}\n", encoding="utf-8")


def _unmark() -> None:
    try:
        _INFLIGHT.unlink()
    except FileNotFoundError:
        pass


def _refuse_if_a_previous_run_died() -> "str | None":
    if not _INFLIGHT.exists():
        return None
    return _INFLIGHT.read_text(encoding="utf-8").strip()


def purge_pycache(root: Path) -> None:
    for d in root.rglob("__pycache__"):
        if ".venv" not in d.parts and "org-stage" not in d.parts and "agent" not in d.parts:
            shutil.rmtree(d, ignore_errors=True)


def _path_for(fname: str) -> Path:
    return ROOT / fname


def _digest() -> dict:
    """Content hash of every file this harness can touch.

    ⭐ CONTENT, NOT `git status`. Uncommitted work is the normal state mid-wave,
    so a git check would report dirty on every run and a real leftover mutant
    would be invisible inside that noise."""
    return {f: hashlib.sha256(_path_for(f).read_bytes()).hexdigest() for f in OURS}


def _pytest(args, cwd, env) -> str:
    """'green' | 'red' | 'nothing-collected'.

    ⛔⛔ EXIT 5 IS NOT A FAILURE. pytest returns 5 when nothing is collected, and
    a runner that only asks `returncode == 0` reads that as red — so one typo in
    the selection would score every mutant killed against zero tests."""
    code = sh(args, cwd=cwd, env=env).returncode
    if code == 5:
        return "nothing-collected"
    return "green" if code == 0 else "red"


def _py() -> str:
    return str(ROOT / ".venv" / "bin" / "python")


def run_tests(filtered: bool) -> bool:
    purge_pycache(ROOT)
    suites = MINE_ROOT.split() if filtered else [ALL_ROOT]
    out = _pytest([_py(), "-B", "-m", "pytest", *suites, "-q", "-p", "no:cacheprovider"],
                  ROOT, ENV)
    if out == "nothing-collected":
        raise AssertionError("the root leg collected NO tests — check the selection")
    return out == "green"


def _selected_count() -> int:
    out = sh([_py(), "-B", "-m", "pytest", *MINE_ROOT.split(), "--collect-only", "-q",
              "-p", "no:cacheprovider"], cwd=ROOT, env=ENV).stdout
    m = _re.search(r"^(\d+) tests? collected", out, _re.M)
    return int(m.group(1)) if m else 0


def _build(edits, original: str, fname: str) -> str:
    mutated = original
    for frm, to in edits:
        if frm == to:
            raise AssertionError("replacement is identical to the anchor")
        hits = mutated.count(frm)
        if hits != 1:
            raise AssertionError(
                f"anchor occurs {hits}x in {fname} (needs exactly 1): {frm[:70]!r}")
        mutated = mutated.replace(frm, to, 1)
    if mutated == original:
        raise AssertionError("the mutant is byte-identical to the original")
    # ⛔⛔ COMPILED BEFORE IT IS WRITTEN. A mis-indented anchor still
    # substring-matches and yields an unparseable file; the suite then goes red
    # on an import error and the mutant banks a kill it never earned.
    if fname.endswith(".py"):
        try:
            compile(mutated, fname, "exec")
        except SyntaxError as syn:
            raise AssertionError(
                f"the mutant does not parse ({syn.lineno}: {syn.msg}) — "
                "check the anchor's indentation") from None
    return mutated


def main() -> int:
    argv = [a.strip() for a in sys.argv[1:] if a.strip()]
    unfiltered = "--unfiltered" in argv
    dry = "--dry" in argv
    only = {a for a in argv if a not in ("--unfiltered", "--dry")}
    selected = [m for m in MUTANTS if not only or m[0] in only]

    ids = [m[0] for m in MUTANTS]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        print(f"duplicate mutant ids: {', '.join(sorted(dupes))}")
        return 2

    if dry:
        # ⭐ Every anchor unique, every mutant parses — WITHOUT writing a byte.
        bad = 0
        for mid, fname, _d, _w, edits in selected:
            try:
                _build(edits, _path_for(fname).read_text(encoding="utf-8"), fname)
            except AssertionError as exc:
                bad += 1
                print(f"! {mid}: {exc}")
        print(f"dry: {len(selected) - bad}/{len(selected)} mutants build")
        return 1 if bad else 0

    if only:
        unknown = only - set(ids)
        if unknown:
            print(f"no such mutant: {', '.join(sorted(unknown))}")
            return 2
        print(f"⚠ FILTERED to {', '.join(sorted(only))} — a spot check, not a score.")
    print("scope: THE WHOLE ROOT SUITE (--unfiltered)" if unfiltered
          else "scope: THIS WAVE'S OWN GUARDS ONLY — pass --unfiltered for the other number")

    stranded = _refuse_if_a_previous_run_died()
    if stranded:
        print("⛔⛔ A PREVIOUS RUN DIED WITH A MUTANT IN THE SOURCE:\n"
              f"    {stranded}\nRestore that file, then delete\n    {_INFLIGHT}")
        return 2

    if not unfiltered:
        n = _selected_count()
        print(f"the wave's own root files collect {n} test(s)")
        if n < MIN_SELECTED_ROOT:
            print(f"⛔⛔ TOO FEW (need >= {MIN_SELECTED_ROOT}) — a selection that matches "
                  "nothing exits 5 and scores every mutant killed. Refusing to run.")
            return 2

    before = _digest()
    print("baseline [root]… ", end="", flush=True)
    if not run_tests(filtered=not unfiltered):
        print("RED — fix the tree before mutating")
        return 2
    print("green")

    survivors, faults = [], []
    for mid, fname, direction, why, edits in selected:
        path = _path_for(fname)
        original = path.read_text(encoding="utf-8")
        try:
            mutated = _build(edits, original, fname)
            _mark(mid, fname)
            path.write_text(mutated, encoding="utf-8")
            if path.read_text(encoding="utf-8") != mutated:
                raise AssertionError("the mutation did not reach the file")
            killed = not run_tests(filtered=not unfiltered)
            flapped = False
            for _ in range(SURVIVOR_CONFIRMATIONS - 1):
                again = not run_tests(filtered=not unfiltered)
                if again != killed:
                    flapped = True
                    killed = False
            mark = "✓ killed  " if killed and not flapped else "✗ SURVIVED"
            note = "  ⚠ FLAPPED — verdicts disagreed across runs" if flapped else ""
            print(f"{mark} {mid} [{direction}] {why}{note}", flush=True)
            if not killed or flapped:
                survivors.append((mid, direction, why))
        except AssertionError as exc:
            print(f"! ERROR    {mid} {exc}", flush=True)
            faults.append((mid, direction, why, str(exc)))
        finally:
            path.write_text(original, encoding="utf-8")
            _unmark()

    after = _digest()
    leftover = [f for f in before if before[f] != after[f]]
    if leftover:
        print("\n⛔ THE TREE DID NOT COME BACK CLEAN — a mutant is still in your "
              "source:\n" + "\n".join(f"    {f}" for f in leftover))
        return 3

    over = sum(1 for m in selected if m[2] == "over")
    label = " (SPOT CHECK — not the wave's score)" if only else ""
    scope = " [whole root suite]" if unfiltered else " [own guards]"
    measured = len(selected) - len(faults)
    print(f"\n{measured - len(survivors)}/{measured} killed "
          f"({over} over-corrections){scope}{label}")
    if faults:
        print(f"⚠ {len(faults)} HARNESS FAULT(S) — measured nothing, counted out:")
        for mid, _d, _w, exc in faults:
            print(f"    {mid}: {exc}")
    if survivors:
        print("SURVIVORS:")
        for mid, direction, why in survivors:
            print(f"    {mid} [{direction}] {why}")
    return 1 if (survivors or faults) else 0


if __name__ == "__main__":
    raise SystemExit(main())
