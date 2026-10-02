"""Wave 14, 2026-10-02 — every equation in a saved document keeps its source.

⛔⛔ THE DEFECT. Gemini keeps each equation's TeX in a `data-math` attribute —
`div.math-block` for one on its own line, `span.math-inline` in a sentence — and
draws it with KaTeX inside (the owner's recording, fixtures/gemini_1002/
report_recording.json: 14 such elements on one report). The converter wrote the
DRAWING, so the 10-01 Gemini document reads "zk\u200b=d\u200bhstate⊤\u200bWc\u200bhoptk\u200b\u200b\u200b" (65
zero-width spaces in it) where the report shows an equation.

Now an equation is written from its source: `$$ tex $$` in a sentence, a `$$` block
on its own lines, the one shape the web draws. A KaTeX root that carries its TeX
(`annotation[encoding="application/x-tex"]`, as KaTeX renders on ChatGPT's and
Claude's pages) is read the same way.

⛔ Expected values are the recording's own: each TeX is read from the recorded
`data-math` attribute (`_gemini_1002_pages.math_samples`), and the KaTeX pages are
real KaTeX output (fixtures/gemini_1002/katex_samples.json, rendered once with
KaTeX 0.16.47) with the TeX each was rendered from. The Gemini and Claude pages
run in real headless Chrome through the production extraction code; nothing
leaves the machine (`page.set_content`).
"""
import pytest

import research
import test_chatgpt_new_page_0928 as base
import _gemini_1002_pages as G

chrome = base.chrome
page = base.page
fast = base.fast

MATH = G.math_samples()


@pytest.fixture
def lines(monkeypatch):
    out = []
    monkeypatch.setattr(research, "log", lambda msg, level="INFO", *a, **k: out.append(str(msg)))
    monkeypatch.setattr(research, "emit_event", lambda *a, **k: None)
    return out


def _report():
    """A report holding the recording's equations where the recording shows them:
    the two blocks each in their own `data-path-to-node` div, the four inline ones
    each at the start of a list item's text. The words around them are ASSUMED."""
    inline = "".join(
        f'<li><p><span data-path-to-node="162,{i},0,0">{m["html"]} represents a '
        f"measured part of the net value.</span></p></li>"
        for i, m in enumerate(MATH[2:]))
    return ("<h1>Technical Evaluation of the System</h1>"
            f"<h2>Cache keys</h2><p>{G.prose(1)}</p>"
            f'<div data-path-to-node="104">{MATH[0]["html"]}</div>'
            f"<p>{G.prose(2)}</p><h2>Net value</h2><p>{G.prose(3)}</p>"
            f'<div data-path-to-node="160">{MATH[1]["html"]}</div>'
            f"<p>Where:</p><ul>{inline}</ul><h2>Verdict</h2><p>{G.prose(4)}</p>"
            f"<p>{G.prose(5)}</p><p>{G.prose(6)}</p>")


def _gemini(chrome, page, report_html, **kw):
    G.offline(chrome, page)
    chrome.run(page.set_content(G.report_page(report_html, **kw)))
    return chrome.run(research.extract_gemini_response(page))


def test_geminis_equations_are_written_from_their_source(chrome, page, fast, lines):
    """⭐⭐ Through Gemini's real extraction (its side panel read as HTML): each
    block is a `$$` block on its own lines holding exactly the recorded TeX, each
    inline one is `$$ tex $$` where it stood, and not one glyph of KaTeX's drawing —
    nor a zero-width space — is in the document.
    (The fixture first: the recording's two blocks and four inline equations,
    each keeping its TeX in `data-math`, none with a TeX annotation.)"""
    rec = G.recording()["math"]
    assert (rec["dataMath"], rec["katex"], rec["texAnnotations"]) == (14, 14, 0)
    assert [m["block"] for m in MATH] == [True, True, False, False, False, False]
    assert MATH[2]["tex"] == r"S_{\text{tokens}}"
    assert all("katex" in m["html"] and "\u200b" in m["html"] for m in MATH[1:])
    md = _gemini(chrome, page, _report())
    assert md, lines
    for m in MATH[:2]:
        assert "\n\n$$\n%s\n$$\n\n" % m["tex"] in md
    for m in MATH[2:]:
        assert "- $$ %s $$ represents a measured part" % m["tex"] in md
    assert md.count("$$") == 2 * 2 + 2 * 4
    assert "\u200b" not in md
    assert "CacheKey=SHA256" not in md and "Net\u00a0Value" not in md
    assert "Stokens" not in md and "S tokens" not in md


def test_an_element_names_its_kind_by_its_class_its_tag_or_mathml():
    """With no class to say, a `div` holding `data-math` is a block and a `span`
    is inline; a bare MathML `<math display="block">` with its TeX is a block, and
    one with no `display` is inline."""
    ann = ('<math{d}><semantics><mi>a</mi><annotation encoding="application/x-tex">'
           "{t}</annotation></semantics></math>")
    md = research.html_to_markdown(
        '<div data-math="x^2"></div><p>so <span data-math="y_1"></span> and '
        + ann.format(d="", t="c+d") + " hold</p>" + ann.format(d=' display="block"', t="a+b"))
    assert md == "$$\nx^2\n$$\n\nso $$ y_1 $$ and $$ c+d $$ hold\n\n$$\na+b\n$$"


def test_a_tex_with_underscores_and_stars_is_written_unescaped():
    """⛔ The converter escapes `_` and `*` in prose; the TeX is written as the page
    holds it, or it would draw a literal underscore."""
    tex = r"a_{i}^{*} = \max_j x_j * y"
    md = research.html_to_markdown(f'<p>Then <span class="math-inline" data-math="{tex}">'
                                   "<span class='katex'>drawn</span></span> holds.</p>")
    assert md == "Then $$ %s $$ holds." % tex


def test_a_block_has_no_blank_line_and_inline_tex_is_one_line():
    """A blank line would end the block early on the web; a sentence's equation
    is one line."""
    tex = "a = b\n\n  + c\n"
    md = research.html_to_markdown(f'<div class="math-block" data-math="{tex}"></div>'
                                   f'<p>x <span class="math-inline" data-math="{tex}"></span> y</p>')
    assert md == "$$\na = b\n  + c\n$$\n\nx $$ a = b + c $$ y"


def test_in_a_table_cell_or_heading_an_equation_is_one_line():
    """A table cell and a heading are one line each: a block there is written
    inline, and in a cell a bare `|` is written `\\vert ` so it does not end the
    cell (a `\\|` the TeX holds is left as it is)."""
    md = research.html_to_markdown(
        "<table><tr><th>Rule</th></tr><tr><td>"
        '<div class="math-block" data-math="|x| \\| y"></div></td></tr></table>'
        '<h2>On <div class="math-block" data-math="E = mc^2"></div></h2>')
    assert "| $$ \\vert x\\vert \\| y $$ |" in md
    assert "## On $$ E = mc^2 $$" in md


#: Each bar an equation in a cell may hold, and what the cell is written with:
#: one Gemini puts in a table ("p(j | x)"), an absolute value, a real double bar,
#: KaTeX's sized ones, and a bar right after TeX's row break `\\`.
_CELL_BARS = [
    (r"E[L] = \sum_j j \cdot p(j | x)", r"E[L] = \sum_j j \cdot p(j \vert x)"),
    (r"|w|", r"\vert w\vert"),
    (r"\|y\|", r"\|y\|"),
    (r"\left| z \right|", r"\left\vert z \right\vert"),
    (r"a \\| b", r"a \\\vert b"),
]


def test_a_bar_in_a_table_cell_draws_the_same_single_bar():
    """⛔⛔ Review 10-02: a bare `|` in a cell was written `\\|`, and the web hands
    an equation's TeX to KaTeX as written — so "p(j | x)" in a table drew
    "p(j‖x)", the DOUBLE bar, and a real `\\|` could no longer be told from it.
    Now a bare `|` is `\\vert ` (the one bar KaTeX draws for `|`), a `\\|` stays
    the double bar it is, and not one bare `|` is left in the cell to end it. The
    same TeX outside a table is written as the page holds it."""
    for tex, cell in _CELL_BARS:
        md = research.html_to_markdown(
            "<table><tr><th>Type</th><th>Output</th></tr><tr><td>Score</td><td>Expected "
            f'<span class="math-inline" data-math="{tex}">d</span></td></tr></table>'
            f'<p>Outside <span class="math-inline" data-math="{tex}">d</span> here.</p>')
        rows = md.split("\n")
        assert rows[2] == "| Score | Expected $$ %s $$ |" % cell, (tex, md)
        assert rows[-1] == "Outside $$ %s $$ here." % tex, (tex, md)


def _eq(tex, kind="inline"):
    return f'<span class="math-{kind}" data-math="{tex}">drawn</span>'


def test_an_equation_never_runs_into_a_dollar_beside_it():
    """⛔ Review 10-02: two inline equations with nothing between them were
    written "$$a$$$$b$$", which the web reads as ONE equation "a$$$$b" (a red
    error); one whose TeX ends in a dollar, "$$C = 100\\$$$", was never read as
    an equation; a price's dollar touching one ran into its delimiter. Now each
    is written `$$ tex $$`, with a space between it and any dollar outside it —
    the equation beside it (inside its own elements too), or a price."""
    a, b, cost, x = _eq("a"), _eq("b"), _eq(r"C = 100\$"), _eq("x")
    md = research.html_to_markdown(
        f"<p>Ratio {a}{b} end</p><p>Ratio <span>{a}</span><span>{b}</span> end</p>"
        f"<p>Cost {cost} total</p><p>Cost 5${x}$ more</p>")
    assert md.split("\n\n") == [
        "Ratio $$ a $$ $$ b $$ end", "Ratio $$ a $$ $$ b $$ end",
        "Cost $$ C = 100\\$ $$ total", "Cost 5$ $$ x $$ $ more"]
    assert research._DOC_MATH_OPEN not in md and research._DOC_MATH_CLOSE not in md


def test_a_block_inside_bold_italics_a_link_or_a_quote_is_written_inline():
    """⛔ Review 10-02: a display equation inside bold or italics was written on
    its own lines between the marks ("*$$\\nx^2\\n$$*"), which the web shows as
    raw TeX. Inside any mark that holds one line — bold, italics, strike-through,
    a link, a quote — it is written inline, with a space each side of its own (a
    block's neighbours lose theirs, as in a table cell; two spaces draw as one);
    outside them it stays a block."""
    def inside(tag, attrs=""):
        return research.html_to_markdown(
            f"<p>Before <{tag}{attrs}>{_eq('x^2', 'block')}</{tag}> after</p>")
    assert inside("em") == "Before  *$$ x^2 $$*  after"
    assert inside("i") == "Before  *$$ x^2 $$*  after"
    assert inside("strong") == "Before  **$$ x^2 $$**  after"
    assert inside("b") == "Before  **$$ x^2 $$**  after"
    assert inside("del") == "Before  ~~$$ x^2 $$~~  after"
    assert inside("s") == "Before  ~~$$ x^2 $$~~  after"
    assert inside("a", ' href="https://e.example.org/a"') == (
        "Before  [$$ x^2 $$](https://e.example.org/a)  after")
    assert inside("q") == 'Before " $$ x^2 $$ " after'
    assert inside("span") == "Before\n\n$$\nx^2\n$$\n\n after"


def test_an_equation_inside_code_stays_as_the_code_shows_it():
    """⛔ Inside code nothing is maths: the code's own text is kept — while the
    same element in the sentence after it is written from its source."""
    eq = '<span class="math-inline" data-math="y^2">y2</span>'
    md = research.html_to_markdown(f"<pre><code>x = {eq}</code></pre><p>so {eq} grows</p>")
    assert md.split("\n")[1] == "x = y2"
    assert md.endswith("so $$ y^2 $$ grows")


def test_an_element_with_no_source_is_converted_as_before():
    """An empty `data-math`, or a KaTeX root with no TeX annotation, is written as
    it always was, from what it shows — and the root beside it with its source is
    written from that."""
    real = G.katex_samples()[1]
    assert research.html_to_markdown(
        '<p>a <span class="math-inline" data-math=" "><span>x2</span></span> b '
        f'{real["html"]}</p>') == "a x2 b $$ %s $$" % real["tex"]
    assert research.html_to_markdown(
        '<p>a <span class="katex"><span class="katex-html">x2</span></span> b '
        f'{real["html"]}</p>') == "a x2 b $$ %s $$" % real["tex"]


def _katex_page(samples):
    css = ("<style>.katex .katex-mathml{border:0;clip-path:inset(50%);height:1px;"
           "overflow:hidden;padding:0;position:absolute;width:1px}"
           ".katex-display{display:block;margin:1em 0}</style>")
    body = "".join(f"<p>{G.prose(i)}</p><p>Where {s['html']} holds.</p>"
                   for i, s in enumerate(samples))
    return ("<!doctype html><html><head><meta charset='utf-8'>" + css + "</head><body>"
            "<aside><div class='prose'><h1>Report</h1>" + body + "</div></aside></body></html>")


def test_a_katex_root_with_its_tex_is_written_from_it_on_claudes_page(chrome, page, fast, lines):
    """⭐ Claude's page read (its artifact panel, read as HTML): KaTeX's own output
    keeps the TeX in an annotation; each equation is written from it — a display
    one as a block, an inline one in its sentence."""
    samples = G.katex_samples()
    G.offline(chrome, page)
    chrome.run(page.set_content(_katex_page(samples)))
    md = chrome.run(research._extract_html_to_md(page, ["aside .prose"], "Claude"))
    assert md, lines
    for s in samples:
        if s["display"]:
            assert "\n\n$$\n%s\n$$\n\n" % s["tex"] in md
        else:
            assert "Where $$ %s $$ holds." % s["tex"] in md
    assert md.count("$$") == 2 * len(samples)
    assert "\u200b" not in md and "application/x-tex" not in md


def test_citations_beside_an_equation_are_untouched_through_the_write():
    """⛔⛔ An equation never touches a citation. A Claude-style `\\[n\\]` beside an
    equation is linked to its own list at the write exactly as without the
    equation, and the equation comes through the write byte for byte."""
    eq = research.html_to_markdown('<p>Then <span class="math-inline" data-math="p \\in [0, 1]">'
                                   "</span> holds.</p>")
    assert eq == "Then $$ p \\in [0, 1] $$ holds."
    body = ("# Claude Research\n\n## Findings\n\n" + G.prose(1) + "\\[1\\]\n\n" + eq
            + "\\[2\\]\n\n$$\nE = mc^2\n$$\n\n## Sources\n\n"
            "1. [One](https://one.example.org/a)\n2. [Two](https://two.example.org/b)\n")
    out = research._number_document_sources(body, [], [], label="Claude")
    assert "Then $$ p \\in [0, 1] $$ holds.[\\[2\\]](https://two.example.org/b)" in out
    assert "[\\[1\\]](https://one.example.org/a)" in out
    assert "\n\n$$\nE = mc^2\n$$\n\n" in out
