"""runview.flatten_links / is_terminal — the streaming presentation helpers."""

from facade import runview


def test_flatten_orders_by_phase_then_kind_and_skips_legacy_arrays():
    links = {
        "youtube": {"url": "u-yt", "label": "YouTube", "phase": 4},
        "brief": {"url": "u-brief", "label": "Brief", "phase": 1},
        "chatgpt": {"url": "u-cg", "phase": 2},
        "phase2": [{"url": "u-cg"}],  # legacy aggregate array → skipped
    }
    ev = runview.flatten_links(links)
    assert [e["kind"] for e in ev] == ["brief", "chatgpt", "youtube"]
    assert ev[0]["url"] == "u-brief"
    # missing label falls back to the kind
    assert next(e for e in ev if e["kind"] == "chatgpt")["label"] == "chatgpt"


def test_flatten_dedups_by_url_canonical_winner():
    # same url under two kinds → one entry, and the canonical (KIND_ORDER-first)
    # kind wins regardless of Firestore field/insertion order.
    a = runview.flatten_links({
        "audio": {"url": "same", "phase": 3},
        "audio_file": {"url": "same", "phase": 3},
    })
    b = runview.flatten_links({
        "audio_file": {"url": "same", "phase": 3},  # inserted first
        "audio": {"url": "same", "phase": 3},
    })
    assert len(a) == 1 and len(b) == 1
    assert a[0]["kind"] == "audio" and b[0]["kind"] == "audio"


def test_flatten_handles_bare_string_value():
    ev = runview.flatten_links({"doc": "https://x/doc"})
    assert ev == [{"kind": "doc", "phase": None, "url": "https://x/doc", "label": "doc"}]


def test_flatten_skips_entries_without_url():
    assert runview.flatten_links({"brief": {"label": "no url"}}) == []


def test_flatten_non_dict_is_empty():
    assert runview.flatten_links(None) == []
    assert runview.flatten_links([]) == []
    assert runview.flatten_links("nope") == []


def test_unknown_kind_sorts_last_but_present():
    ev = runview.flatten_links({"weird": {"url": "u-w", "phase": 2}, "brief": {"url": "u-b", "phase": 1}})
    assert [e["kind"] for e in ev] == ["brief", "weird"]


def test_is_terminal():
    for s in ("completed", "stopped", "error", "archived", "stopped_by_watchdog"):
        assert runview.is_terminal(s)
    for s in ("ongoing", "queued", None, "weird"):
        assert not runview.is_terminal(s)
