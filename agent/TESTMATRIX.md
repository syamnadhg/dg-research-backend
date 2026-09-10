# Super Agent — test matrix (P7)

Run the suite with `pytest tests -q` from `agent/` (~2433 tests; `ruff check agent`
clean). The bridge owns the account session; CLI and skill commands reach it over
loopback — with one measured exception, the bridge-down `logout` path, which loads
the session and writes Firestore itself.

> ⛔⛔ **THIS FILE WAS CUT DOWN IN 7.9-5 BECAUSE IT KEPT BEING WRONG, TWICE IN ONE
> WAVE.** Its first version undercounted the suite by a factor of three, said "no
> bridge unit test yet" for routes tested since 7.9-1, and listed 17 of the
> routes. I rebuilt it from a measured run — and cross-verify then found the
> rebuild wrong in eight more places: it said 38 routes when there are **39**
> (`GET /icons/<name>` was in no row), credited `GET /healthz` to a test that
> sends `Host: evil.com` and asserts a **403 before the handler runs**, described
> a generator that **did not exist**, claimed every test file appeared in exactly
> one table when two appeared in none and four in several, and said "ruff clean"
> against six errors.
>
> ⭐⭐ SO IT NOW CLAIMS LESS. The route list is DERIVED from the dispatcher and a
> test asserts every declared route appears here (`test_route_matrix_795.py`) —
> which is the guard the old text falsely claimed to have. The credits below come
> from instrumenting the bridge's own HANDLER METHODS, not its request entry
> points, because that distinction is exactly what produced the false `/healthz`
> credit. Everything that could not be derived was deleted rather than corrected.
>
> ⛔ **THE COUNT IS A SNAPSHOT, NOT A GUARD** — a pinned count gets updated by
> whoever makes it red. Re-measure: `pytest tests -q --collect-only | tail -1`.

## Bridge routes — all 39 the dispatcher declares

Third column = test files measured RUNNING that route's handler. A blank means no
test drove it. Four routes have no dedicated handler (they answer inline), so
handler instrumentation cannot see them; they are marked rather than credited.

| Route | Handler exercised by |
|---|---|
| `/agent-install` | `test_sr_client` |
| `/device` | `test_bridge_device`, `test_device_projection_795` |
| `/device/ask` | `test_public_devices_792` |
| `/device/decide` | `test_owner_verbs_793` |
| `/device/pair` | `test_bridge_device`, `test_cli_device_commands_795`, `test_public_devices_792`, `test_sr_client` |
| `/device/remove` | `test_bridge_device`, `test_cli_device_commands_795`, `test_public_devices_792`, `test_sr_client`, `test_unlink_copy_795` |
| `/device/select` | `test_bridge_device`, `test_device_projection_795`, `test_e2e_lifecycle`, `test_public_devices_792`, `test_sr_client` |
| `/device/visibility` | `test_owner_verbs_793` |
| `/devices` | `test_bridge_device`, `test_bridge_routes`, `test_device_projection_795`, `test_e2e_lifecycle`, `test_signin_once_0901`, `test_sr_attention_copy_0831`, `test_sr_client` |
| `/devices/public` | `test_public_devices_792`, `test_sr_client` |
| `/devices/requests` | `test_owner_verbs_793`, `test_public_devices_792` |
| `/healthz` | `test_agent_log_out_0826`, `test_bridge_csrf`, `test_bridge_device`, `test_bridge_remote_login`, `test_bridge_resolve_0831`, `test_bridge_routes`, `test_bridge_shutdown`, `test_cli_device_commands_795`, `test_device_projection_795`, `test_e2e_lifecycle`, `test_owner_verbs_793`, `test_public_devices_792`, `test_send_logs_agent_0825`, `test_signin_announce_0826`, `test_signin_once_0901`, `test_sr_attention_copy_0831`, `test_sr_client`, `test_stretch45_agent_0827`, `test_unlink_copy_795` |
| `/icons/<name>` | ⚠ no dedicated handler — not measurable this way |
| `/install-backend` | `test_sr_client` |
| `/login` | ⚠ no dedicated handler — not measurable this way |
| `/login/callback` | `test_bridge_csrf`, `test_signin_announce_0826` |
| `/login/config` | ⚠ no dedicated handler — not measurable this way |
| `/login/remote/pending` | `test_bridge_remote_login`, `test_signin_announce_0826`, `test_sr_client`, `test_stretch45_agent_0827` |
| `/login/remote/poll` | `test_bridge_remote_login`, `test_e2e_lifecycle`, `test_signin_once_0901` |
| `/login/remote/start` | `test_bridge_remote_login`, `test_e2e_lifecycle`, `test_signin_announce_0826`, `test_sr_client` |
| `/logout` | `test_bridge_routes`, `test_e2e_lifecycle` |
| `/logs/agent-log` | `test_agent_log_out_0826` |
| `/logs/bundle` | `test_send_logs_agent_0825` |
| `/logs/runs` | `test_send_logs_agent_0825` |
| `/logs/send` | `test_send_logs_agent_0825` |
| `/research` | `test_bridge_device`, `test_bridge_routes`, `test_e2e_lifecycle`, `test_signin_announce_0826`, `test_sr_client` |
| `/research/<id>` | ⚠ no dedicated handler — not measurable this way |
| `/research/<id>/cancel` | `test_bridge_device` |
| `/research/<id>/pause` | `test_sr_client` |
| `/research/<id>/podcast` | `test_bridge_routes`, `test_e2e_lifecycle`, `test_sr_client` |
| `/research/<id>/resolve` | `test_bridge_resolve_0831`, `test_sr_attention_copy_0831`, `test_sr_client` |
| `/research/<id>/resume` | `test_bridge_resolve_0831`, `test_sr_client` |
| `/research/<id>/skip` | `test_bridge_device`, `test_e2e_lifecycle`, `test_sr_client` |
| `/research/<id>/stop` | `test_e2e_lifecycle`, `test_sr_client` |
| `/researches` | `test_bridge_device`, `test_bridge_routes` |
| `/shutdown` | `test_bridge_shutdown` |
| `/status` | `test_bridge_remote_login`, `test_e2e_lifecycle`, `test_sr_client` |
| `/updates` | `test_bridge_device`, `test_bridge_resolve_0831`, `test_e2e_lifecycle`, `test_signin_announce_0826`, `test_signin_once_0901`, `test_sr_attention_copy_0831`, `test_sr_client`, `test_stretch45_agent_0827` |
| `/version` | `test_sr_client` |

⛔⛔ **`GET /login`, `GET /login/config`, `GET /icons/<name>` and `GET /healthz`
ARE THE THIN SPOTS.** `/login/config` and `/login/callback` are covered by
`test_bridge_csrf`; the `/login` PAGE itself, the icon route and `/healthz` are
driven by nothing that asserts their own behaviour — and the row that used to
stand here described `/login` as covered. Recorded, not fixed, in 7.9-5.

## Everything that is not a bridge route

Client surfaces, the store, the session, Firestore REST, prefs, the routers and
the copy guards are covered by the files in `agent/tests/`. ⛔ This file no
longer lists them one by one: the previous attempt claimed "every file appears in
exactly one of these tables" and two appeared in none. `pytest tests -q
--collect-only` is the authority on what exists; each file's own module docstring
says what it protects.

## Live-only (the human checkpoint — needs a signed-in account + a live device)

These can't be unit-tested (real Google sign-in, a real device daemon, real LLM
spend); run them once after `agent login`:

1. `agent connect <runtime>` → skill lands in the runtime's skills dir.
2. `agent serve` → bridge up; `agent doctor` all-green.
3. `agent login` (or chat `/sr login`) → real Google sign-in → connected.
   Note: after `agent connect`, run `/reload-skills` once before `/sr` registers.
4. `agent device` → real devices listed; `agent device use <id>`.
5. **The one live enqueue:** `agent research "<topic>" --no-video --no-email`
   → returns a run id <1s.
6. `agent watch <id>` → per-phase links stream (Brief → agents → NLM/Audio → Doc).
7. **Verify it appears in the web app as a normal chat** (tagged "from Super
   Agent") with the same links.
8. `agent skip <id> report` mid-run → the Report phase is skipped when reached.
9. `agent cancel <id>` → the run stops.
10. Reboot → the autostart task brings the bridge back; the session persists.
11. **Unlink a computer you own** → the reply carries a NEW pair code, the old one
    is refused by `device-add`, and the new one re-links the machine. Live-only
    because rotation happens in the web app against a real device document.

Status: P0 read-gate proven live 2026-06-05 (two test accounts, sessions then
revoked). The full live enqueue (step 5) awaits a fresh sign-in.
