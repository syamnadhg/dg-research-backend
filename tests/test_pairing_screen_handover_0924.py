"""The pairing screen says where the access code GOES — both places, and no button
that is not there.

⭐ OWNER-APPROVED WORDING (2026-09-24), printed under the code + QR by
`cmd_pair_v2`'s `_on_code`:

    Send this code to your chat assistant, or enter it in the Super Research web
    app under Account → Pipeline Connection.

⛔⛔ WHAT IT REPLACED. "Enter this code in the Super Research app: • Account →
Pipeline Connection → Add Device". Two faults: it never said a chat assistant takes
the code (the one-message `/sr device-add` route is how most people add a computer
now), and for a FIRST computer the "+ add device" button does not render — the
Pipeline Connection section shows the code field directly. It is also the nearest
product wording to the "code from the Super Research app" a relay invented, though
that screen is where the code is ENTERED, never where it comes from.

Only this line is pinned here; the "Access code" heading and the wire names are
pinned by test_terminal_words_0916.py and must not move.
"""

import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import research  # noqa: E402

from conftest import code_only  # noqa: E402


def _on_code_source() -> str:
    """`_on_code` is nested in `cmd_pair_v2`, so it is sliced out of the parent's
    source — comments blanked, string literals kept."""
    src = code_only(inspect.getsource(research.cmd_pair_v2))
    i = src.index("def _on_code(")
    j = src.index("def _on_waiting(", i)
    return src[i:j]


def test_the_pairing_screen_names_the_chat_and_the_web_app_section():
    body = _on_code_source()
    # ⚠ split across two printed lines at a word boundary; the words are the
    # owner's, in order
    assert "Send this code to your chat assistant, or enter it in the" in body
    assert "Super Research web app under Account → Pipeline Connection." in body


def test_the_retired_line_and_the_button_that_does_not_render_are_gone():
    body = _on_code_source()
    assert "Enter this code in the Super Research app" not in body
    assert "→ Add Device" not in body


def test_the_heading_above_the_code_is_untouched():
    """The rewrite is under the code + QR only — the heading keeps the web's word."""
    body = _on_code_source()
    assert "'Access code'" in body
    assert body.index("'Access code'") < body.index("Send this code to your chat")


def test_the_timeout_names_both_handovers_too():
    """⛔ THE SAME FLOW'S TIMEOUT MUST NOT UNSAY IT. A few lines on, a pairing window
    that runs out used to blame "the code was never entered in the web app" — true
    of one handover, silent about the chat one the screen above now offers first."""
    src = code_only(inspect.getsource(research.cmd_pair_v2))
    tail = src[src.index("except v2_flow.PollTimeout"):]
    tail = tail[:tail.index("return")]
    assert "never sent to a chat assistant or entered in the" in tail
    assert "never entered in the web app, or" not in tail
