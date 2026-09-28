"""Allow all, in the backend's own docs (wave 12 repair 2, cross-verify G30).

⛔⛔ WHAT THIS PINS. Every passage in README.md and ARCHITECTURE.md that tells an
owner how to turn Allow all off, or make the machine private, also says that
doing so removes nobody — "Anyone who already joined keeps access — remove people
in the web app (Shared with)." Before the repair none of them did, and the same
paragraph said Reset clears the tick — and Reset DOES remove everyone, so the
docs invited the reading that closing the door does too. The machine, the chat
and the agent terminal all say the sentence already; the docs were the one place
that did not.

Each check looks INSIDE the paragraph that gives the instruction, not anywhere in
the file: the sentence somewhere else would not reach the person reading how to
close the door.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
KEEPS = ("anyone who already joined keeps access — remove people in the web app "
         "(shared with)")


def _paragraphs(path: Path) -> list[str]:
    """The file's paragraphs (blank-line separated), whitespace folded and lower
    case, so a re-wrap never reads as a change of meaning."""
    text = path.read_bytes().decode("utf-8").replace("\r\n", "\n")
    return [" ".join(p.split()).lower() for p in text.split("\n\n") if p.strip()]


def _the_paragraph(path: Path, marker: str) -> str:
    hits = [p for p in _paragraphs(path) if marker.lower() in p]
    assert len(hits) == 1, (path.name, marker, len(hits))
    return hits[0]


@pytest.mark.parametrize("doc,marker", [
    # README §5a-bis — the section the finding names
    ("README.md", "**allow all** is the one exception, and only on a public machine"),
    # README, the pairing step's "change it any time" block
    ("README.md", "which writes the same field."),
    # README, the agent's owner verbs
    ("README.md", "**set who can find the machine.**"),
    # ARCHITECTURE, the machine's writer
    ("ARCHITECTURE.md", "allow all (wave 12) is the one door that opens without the owner"),
], ids=["readme-5a-bis", "readme-pair-step", "readme-agent-verbs", "architecture"])
def test_each_way_to_close_the_door_says_nobody_is_removed(doc, marker):
    assert KEEPS in _the_paragraph(ROOT / doc, marker)


def test_reset_is_named_as_the_one_that_does_remove_everyone():
    """⛔ The paragraph lists Reset beside private and hand-off as things that
    clear the tick; without this, "keeps access" read as true of Reset too."""
    para = _the_paragraph(ROOT / "README.md",
                          "**allow all** is the one exception, and only on a public machine")
    assert "reset is the one that does remove everyone" in para
