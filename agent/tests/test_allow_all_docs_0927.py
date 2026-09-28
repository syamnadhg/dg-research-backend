"""Allow all, in the agent's README (wave 12 repair 2, cross-verify G30 and G8).

⛔⛔ WHAT THIS PINS. The two paragraphs that tell an owner how to take a computer
off the list (`device-visibility private`) and how to stop letting anyone join
(`device-allow-all no`) each say that doing so removes nobody, and where people
ARE removed: "Anyone who already joined keeps access — remove people in the web
app (Shared with)." The chat and the agent terminal print that sentence; the
README said only half of it, and in one paragraph not at all.

And the joiner's paragraph says what the join now does with an owner who had not
chosen a computer (G8): it saves the one of theirs the router was already using,
so their research never moves to the stranger's.

Each check looks INSIDE the paragraph that gives the instruction.
"""

from __future__ import annotations

from pathlib import Path

import pytest

README = Path(__file__).resolve().parents[1] / "README.md"
KEEPS = ("anyone who already joined keeps access — remove people in the web app "
         "(shared with)")


def _the_paragraph(marker: str) -> str:
    text = README.read_bytes().decode("utf-8").replace("\r\n", "\n")
    paras = [" ".join(p.split()).lower() for p in text.split("\n\n") if p.strip()]
    hits = [p for p in paras if marker.lower() in p]
    assert len(hits) == 1, (marker, len(hits))
    return hits[0]


@pytest.mark.parametrize("marker", [
    "`device-visibility private` takes it off the list again",
    "`device-allow-all no` goes back to approving each person",
], ids=["going-private", "allow-all-off"])
def test_each_way_to_close_the_door_says_nobody_is_removed(marker):
    assert KEEPS in _the_paragraph(marker)


def test_the_join_paragraph_says_your_own_computer_is_kept():
    para = _the_paragraph("a public row marked *joins at once* lets `device-ask`")
    assert "saves that one as your choice" in para
    assert "never moves off a computer of your own" in para


# ── wave 12 repair 3 ─────────────────────────────────────────────────────────

def test_the_join_paragraph_says_a_computer_mid_reset_is_kept_too():
    """Cross-verify H9: a join inside the person's own Reset saves THEIR computer,
    so their research comes back to it after the re-pair."""
    para = _the_paragraph("a public row marked *joins at once* lets `device-ask`")
    assert "a computer of yours part-way through a reset counts too" in para
    assert "comes back to it once the re-pair is done" in para


@pytest.mark.parametrize("marker", [
    "`devices-public` browses what's on offer",
    "a public row marked *joins at once* lets `device-ask`",
], ids=["ask", "join"])
def test_every_ask_and_join_says_the_owner_sees_name_and_email(marker):
    """Cross-verify H22: "your name, or your email if you haven't set one" here,
    "name and email" on the join — one sentence now, the web's and the chat's."""
    para = _the_paragraph(marker)
    assert "the owner sees your name and email." in para
    assert "or your email" not in para
