# Super Agent — test matrix (P7)

What each surface is covered by, and what only a live run can prove. Run the
suite with `pytest` (652 tests; ruff clean). The bridge is the single owner of
the account session — every CLI/skill command routes through it over loopback.

## Coverage

| Surface | Bridge route | Covered by (automated) |
|---|---|---|
| OAuth capture (local page) | `POST /login/callback` | `test_bridge_csrf` (nonce, Origin, Host, rotation) |
| Remote login (device flow) | `POST /login/remote/{start,poll}` | `test_devicelogin`, `test_bridge_remote_login`, `test_session_custom_token` |
| Custom-token exchange | — (Identity Toolkit) | `test_session_custom_token` (decode, error paths) |
| Token refresh / revoke | — (securetoken) | `test_session` |
| Secret store (keyring + file) | — | `test_store`, `test_app_plane_unchanged` (isolation) |
| Prefs (selected device, runtime) | — | `test_prefs` (uid-binding, runtime) |
| Status / health | `GET /healthz /status` | `test_bridge_routes`, `test_sr_client` |
| List researches | `GET /researches` | `test_bridge_routes`, `test_firestore_rest` |
| Devices: list + owned label | `GET /devices` | `test_bridge_device` |
| Device select / current / stale | `GET /device`, `POST /device/select` | `test_bridge_device` |
| Device pair (add by access code) | `POST /device/pair` | — (live-only; no bridge unit test yet) |
| Device remove | `POST /device/remove` | — (live-only; no bridge unit test yet) |
| Install backend (from chat) | `POST /install-backend` | — (live-only; no bridge unit test yet) |
| Vision act-tier dispatcher wiring (source guard) | — | `test_vision_act_wiring` (asserts the `_shadow_observed_cua` per-hotspot dispatcher is wired; source-guard only — does NOT flip `DG_VISION_TIER` default; act stays opt-in / CUA-primary, #900 open) |
| Start a run (+ device resolve) | `POST /research` | `test_bridge_routes`, `test_bridge_device` |
| Run status (+ events) | `GET /research/<id>` | `test_bridge_device` |
| Streaming snapshot | `GET /updates` | `test_bridge_device`, `test_runview` |
| Cancel | `POST /research/<id>/cancel` | `test_bridge_device` |
| Skip phases | `POST /research/<id>/skip` | `test_bridge_device`, `test_firestore_rest` |
| Shutdown | `POST /shutdown` | `test_bridge_shutdown` |
| Version (SKILL only — no backend line; explicit ask = fresh PyPI read) + skill "newer" nudge | `GET /version?fresh=1`, `GET /status` | `test_sr_client`, `test_selfupdate` |
| Skill self-update (`update` / `update-skill`; + "already up to date") | `POST /agent-install` | `test_sr_client`, `test_selfupdate` |
| Backend-update ask is redirected (agent no longer updates the backend) | — | `test_sr_client` (`test_no_backend_update_surface_left`) |
| Agent-only (do-NOT-relay) marker wraps the arm/stream cronjob directive | `sr.py` (skill client) | `test_sr_client` (marker ordering + hidden cronjob), `test_sr_skip_agents` |
| Once-daily skill-update notice (fresh check, once-per-version nudge, 3-strike cron self-removal) | `sr_update_notice.py` + `GET /version?fresh=1` | `test_sr_update_notice` |
| Install backend from chat | `POST /install-backend` | `test_sr_client`, `test_selfupdate` |
| Body cap / RST guard / rid guard | `do_POST` | `test_bridge_device` (413, malformed rid) |
| CLI parsing (all commands) | — | `test_cli_parser` |
| Skill client (`sr.py`) | all of the above | `test_sr_client`, `test_e2e_lifecycle` |
| `agent connect` installer | — | `test_connect` |
| Autostart (schtasks argv) | — | `test_autostart` |
| Logging setup | — | `test_logsetup` |
| **Full chat lifecycle** | login→device→research→status→updates→skip→cancel→logout | **`test_e2e_lifecycle`** (mock FE + fake Firestore) |
| **App plane unchanged** | — | **`test_app_plane_unchanged`** (no app/automate imports; all Firestore paths account-scoped; store isolated) |

## Live-only (the human checkpoint — needs a signed-in account + a live device)

These can't be unit-tested (real Google sign-in, a real device daemon, real LLM
spend); run them once after `agent login`:

1. `agent connect <runtime>` → skill lands in the runtime's skills dir.
2. `agent serve` → bridge up; `agent doctor` all-green.
3. `agent login` (or chat `/sr login`) → real Google sign-in → connected.
   Note: after `agent connect`, run `/reload-skills` once before `/sr` registers.
4. `agent device` → real devices listed; `agent device use <id>`.
5. **The one live enqueue:** `agent research "<topic>" --no-video --no-email`
   (light smoke; skips P4 video to spare YouTube quota) → returns a run id <1s.
6. `agent watch <id>` → per-phase links stream (Brief → agents → NLM/Audio → Doc).
7. **Verify it appears in the web app as a normal chat** (tagged "from Super
   Agent") with the same links — this is the "runs surface in the app" proof.
8. `agent skip <id> report` mid-run → the Report phase is skipped when reached.
9. `agent cancel <id>` → the run stops.
10. Reboot → the autostart task brings the bridge back; the session persists.

Status: P0 read-gate proven live 2026-06-05 (two test accounts, sessions then
revoked). The full live enqueue (step 5) awaits a fresh sign-in.
