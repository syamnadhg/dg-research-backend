"""Every route the bridge declares appears in TESTMATRIX.md.

⛔⛔ THIS IS THE GUARD TESTMATRIX.md CLAIMED TO HAVE AND DID NOT. Its own text
said "the generator carries an assertion that every route the dispatcher declares
appears here, so the table cannot go short again in silence". No generator
existed — the table was built by a script in a scratchpad, run once, and the
sentence described it as a standing check. Cross-verify found the file short by
exactly the route that claim was supposed to protect: `GET /icons/<name>`, which
appeared in no row.

⭐ A DOCUMENT CANNOT BE KEPT TRUE BY INTENTION. The route list is derived from
the dispatcher here, in a test that runs in agent CI, so adding a route without
mentioning it is red.

⛔ WHAT THIS DELIBERATELY DOES NOT DO: assert anything about COVERAGE. The
previous version of the matrix credited `GET /healthz` to a test that sends
`Host: evil.com` and asserts a 403 — the handler never ran, and the credit was an
artifact of instrumenting the request entry point instead of the handler. Per-route
coverage is not reliably derivable from source, so it is measured out-of-band and
this guard makes no claim about it. A guard that overreaches is how the file got
into this state.
"""

import re
from pathlib import Path

AGENT = Path(__file__).resolve().parents[1]
BRIDGE = AGENT / "facade" / "bridge.py"
MATRIX = AGENT / "TESTMATRIX.md"


def declared_routes() -> set[str]:
    """Every path the dispatcher can answer, read out of the dispatcher.

    ⛔ THREE SHAPES, AND MISSING THE THIRD IS THE BUG THIS EXISTS FOR. Static
    equality (`path == "/devices"`), the dynamic run verbs
    (`path.endswith("/skip")`), and the PREFIX routes
    (`path.startswith("/icons/")`) — that last family is what an earlier count of
    "38 routes" left out, because it only looked for the first two.
    """
    src = BRIDGE.read_text(encoding="utf-8")
    routes = set(re.findall(r'path == "([^"]+)"', src))
    routes |= {"/research/<id>/" + t
               for t in re.findall(r'path\.endswith\("/([a-z]+)"\)', src)}
    routes |= {p + "<name>"
               for p in re.findall(r'path\.startswith\("(/[a-z]+/)"\)', src)}
    # `/research/<name>` is an artefact of the prefix pattern above — the real
    # dynamic family is enumerated by its verbs, plus the bare document read.
    routes.discard("/research/<name>")
    routes.add("/research/<id>")
    return routes


def test_the_dispatcher_declares_the_routes_we_think_it_does():
    """A floor, not a pin. If this drops sharply somebody deleted a route family
    and the derivation below would silently agree with them."""
    routes = declared_routes()
    assert len(routes) >= 39, f"only found {len(routes)}: {sorted(routes)}"


def test_every_declared_route_is_named_in_the_matrix():
    """⛔⛔ THE ONE THAT WOULD HAVE CAUGHT `GET /icons/<name>`."""
    matrix = MATRIX.read_text(encoding="utf-8")
    missing = sorted(r for r in declared_routes() if f"`{r}`" not in matrix)
    assert not missing, (
        "TESTMATRIX.md does not mention these routes the bridge declares:\n  "
        + "\n  ".join(missing))


def test_the_matrix_states_the_derived_count():
    """The count in the prose has to be the derived one — the previous version
    said 38 against a real 39, and the sentence was the only thing anybody read."""
    n = len(declared_routes())
    matrix = MATRIX.read_text(encoding="utf-8")
    assert f"all {n} the dispatcher declares" in matrix, (
        f"the matrix should say 'all {n} the dispatcher declares'")


def test_the_matrix_names_its_own_thin_spots():
    """⛔ THE HONEST HALF. Four routes answer inline with no dedicated handler, so
    handler instrumentation cannot see them and three of the four are driven by
    nothing that asserts their behaviour. A matrix may say "none"; it may not be
    wrong in the optimistic direction, which is what the row for `/login` was."""
    matrix = MATRIX.read_text(encoding="utf-8")
    for route in ("`GET /login`", "`GET /icons/<name>`", "`GET /healthz`"):
        assert route in matrix, f"{route} must be named as a thin spot"
    assert "ARE THE THIN SPOTS" in matrix


def test_the_matrix_does_not_claim_a_guard_it_does_not_have():
    """⛔⛔ THE CLAIM THAT STARTED THIS. "the generator carries an assertion…"
    described a scratchpad script as a standing check. If the file names a
    generator again, the generator has to be a real file."""
    matrix = MATRIX.read_text(encoding="utf-8")
    if "generator" in matrix.lower():
        assert (AGENT / "tests" / "test_route_matrix_795.py").exists()
    # and the specific false sentence stays gone
    assert "the generator carries an assertion" not in matrix
