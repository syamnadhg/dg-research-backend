"""A one-line bibliography lead never cuts the report (Windows release review, 2026-10-01).

⛔⛔ THE DEFECT. A lead naming a bibliography with its entries on the same line —
"**Key sources:** OFA, AKC." — was read as a bibliography TITLE ("bib"), after
which every "**Budget:** …"-style paragraph counted as a source entry. A ChatGPT
document holds no public link, so its "own sources section" was everything from
that lead to the end, and `_number_document_sources` replaced it with ours: the
budget, the health screening and the final recommendation were gone from the
saved report, its Firestore copy, NotebookLM, the share and the synthesis.

A one-line lead now opens nothing after it, exactly as "**References:** AKC."
already did. The bold-period bibliography TITLE ("**Cited-source bibliography.**
The principal sources…", ChatGPT's real 09-30 shape) still opens its category
lines, and a one-line lead that IS the report's last paragraph is still the
report's own section, replaced by ours.
"""
import pytest

import research
from test_doc_visited_sources_1001 import BODY, sources_sections

VISITED = ["https://www.akc.org/dog-breeds/", "https://ofa.org/diseases/hip-dysplasia/"]


def _numbered(md):
    return research._document_with_sources(md, visited=list(VISITED), label="ChatGPT")


#: The reviewer's shapes: a one-line bibliography lead, then more of the report,
#: all of it bold-colon paragraphs or a list — nothing a "line" lead allows.
GOES_ON = {
    "key-sources-then-budget": (
        "**Key sources:** OFA hip registry, AKC breed standard, VetCompass longevity data.\n\n"
        "**Budget:** Expect about $2,000-$3,500 for a puppy from health-tested parents.\n\n"
        "**Health screening:** Ask for OFA hip and elbow scores for both parents.\n\n"
        "**Final recommendation:** Buy only from a breeder who shows both parents' scores.\n",
        ["**Budget:**", "**Health screening:**", "**Final recommendation:**"]),
    "main-sources-then-bottom-line": (
        "**Main sources:** OFA; AKC.\n\n"
        "**Bottom line:** A good family dog for an active household.\n",
        ["**Bottom line:**"]),
    "selected-references-then-next-steps": (
        "**Selected references:** AKC breed standard; OFA statistics.\n\n"
        "**Next steps:** before you visit a breeder\n\n"
        "- Ask for two previous puppy buyers to talk to\n"
        "- Ask to meet both parents\n",
        ["**Next steps:**", "Ask for two previous puppy buyers", "Ask to meet both parents"]),
}


@pytest.mark.parametrize("shape", sorted(GOES_ON))
def test_a_one_line_bibliography_lead_the_report_goes_on_after_is_never_cut(shape):
    tail, kept = GOES_ON[shape]
    md = BODY + "\n" + tail
    out = _numbered(md)
    for text in kept:
        assert text in out, (shape, text, out)
    assert out.startswith(md.rstrip()), "something before the sources list changed"


@pytest.mark.parametrize("lead", [
    "**Key sources:** OFA hip registry; AKC breed standard.\n",
    "**Main sources:** OFA; AKC.\n",
    "**Selected sources**: AKC breed page; OFA hip page.\n"])
def test_a_one_line_lead_that_is_the_last_paragraph_is_still_the_reports_own(lead):
    """The control: as the report's last paragraph it is still its own link-less
    sources section, replaced by ours — one sources section, not two."""
    out = _numbered(BODY + "\n" + lead)
    assert lead.strip() not in out, out
    assert sources_sections(out) == ["##### Sources"], out


def test_a_bibliography_title_still_opens_its_category_lines():
    """The control the fix must not move: ChatGPT's bold-period bibliography title
    with "**Health:** …" category lines after it is still the report's own section."""
    tail = ("**Cited-source bibliography.** The principal sources.\n\n"
            "**Health:** OFA; AKC.\n\n**Behaviour:** AVSAB.\n")
    out = _numbered(BODY + "\n" + tail)
    assert "**Health:** OFA; AKC." not in out and "Cited-source bibliography" not in out
    assert sources_sections(out) == ["##### Sources"], out
