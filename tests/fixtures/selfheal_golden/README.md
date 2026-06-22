# Phoenix self-heal — golden DOM corpus (PX-0 scaffolding)

This directory is the **seed** of the resolver-eval corpus described in
`PhoenixRecipe.md` §9. Each file is one captured (platform, ui_fingerprint,
intent) example that the PX-2 `semantic_match` resolver is evaluated against
(`scripts/eval_resolver.py`, built at PX-2) — it must re-find each intent's
control from durable signals and clear a pass bar before any heal activates.

**Status (PX-0):** scaffolding only. The three files here are **synthetic but
schema-correct** seeds derived from the real diagnostic-dump shapes
(`_GEMINI_DR_STATE_JS`, the ChatGPT Step-2 menu dump, the Claude Step-3A composer
dump). They carry `a11y_snapshot` in the exact `selfheal.probe_region` record
shape so the resolver can be unit-tested today. `raw_html` and `screenshot` are
left null — those get populated from **real captures** taken during a flag-on E2E
(the `probe_count` + snapshot land in `logs/selfheal_shadow.jsonl`; a future
capture step writes full corpus entries here). Keep old fingerprints for
regression when a platform's UI rotates.

## Schema

```jsonc
{
  "platform": "gemini",                  // one of chatgpt|gemini|claude
  "intent_id": "enable_deep_research",   // matches selfheal intents
  "ui_fingerprint": "seed-2026-06",      // hash of the surface's durable anchors
  "region": "composer",                  // a selfheal.REGIONS key
  "captured_ts": null,                   // ISO ts of a real capture; null = synthetic seed
  "account_type": "personal",            // personal|team|enterprise (gating matters — §6)
  "region_locale": "us",
  "outcome_predicate": "gemini_dr_state:placeholderResearch||pressed",
  "known_good_selector": { "by": "role+name", "value": "button|deep research" },
  "a11y_snapshot": [                      // selfheal.probe_region record shape
    { "role": "...", "accessible_name": "...", "text": "...",
      "attrs": { "...": "..." }, "bounds": {"x":0,"y":0,"w":0,"h":0}, "visible": true }
  ],
  "raw_html": null,                       // populated from a real capture
  "screenshot": null,                     // populated from a real capture (PX-3/Vision)
  "source": "free-text provenance"
}
```

`tests/test_selfheal_report.py::test_golden_corpus_seeds_are_schema_valid` pins
every file in this directory to the schema above, so a malformed seed fails CI.
