# Vision V1 fixtures

Each fixture is a pair of files identified by a stem (`NAME`):

```
NAME.png    — viewport screenshot, 1280×800 PNG
NAME.json   — { "flow_context": { workflow_name, phase, current_step,
                                   platform, viewport, ... },
                "expected_action": "click" | "type" | ... ,
                "expected_target_bbox": [x1, y1, x2, y2]   # optional, 0-1 ratios
                "min_confidence": 0.6 }
```

## How to add a fixture

During an E2E run, navigate the test browser to a hotspot (e.g. Gemini's
"Share & Export" submenu). Then in another shell:

```
CAPTURE_PROFILE_DIR=/path/to/playwright-profile python vision_test.py --capture gemini_share_submenu
```

The script opens the same profile, asks where to navigate, and prompts
for the fixture metadata. The PNG + JSON land in this directory.

## How to validate

```
python vision_test.py --fixtures
```

Replays every fixture, asserts the model returns the `expected_action`,
coords land inside `expected_target_bbox`, and confidence ≥ `min_confidence`.

## V1 ship target

5 of 8 hotspot fixtures green + #1, #3, #6 verified live. See
`../../../../VisionRecipe.md` (root `DG Research/`) for the full hotspot
inventory + Pattern A/B classification + promotion roadmap.

Priority order for fixture collection:
1. `gemini_share_submenu` — hotspot #1, highest Playwright failure rate
2. `notebooklm_anyone_with_link` — hotspot #3, audio + notebook share share this flow
3. `gdoc_general_access` — hotspot #6, Phase 5 publish gate
4. `claude_artifact_publish` — hotspot #2
5. `notebooklm_audio_share` — hotspot #4
6. `phase0_login_verify` — hotspot #5 (capture multiple variants if possible)
7. `gmail_compose` — hotspot #7 (lower priority — long-tail per advisor)
8. `youtube_upload_meta` — hotspot #8 (lowest priority)

Fixtures are gitignored as a directory by default — none committed yet.
After collecting, decide per-fixture whether to commit (rule of thumb:
commit if it doesn't contain authed session UI like email addresses).
