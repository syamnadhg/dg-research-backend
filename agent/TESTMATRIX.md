# Super Agent — test matrix (P7)

Run the suite with `pytest tests -q` from `agent/` (**4283 collected**; a full run
here on 2026-09-19 reported 4274 passed, 9 skipped). ⛔ `ruff check agent` is **not**
clean: 11 errors, ten of them in four test files added since 7.9-5. The bridge
owns the account session; CLI and skill commands reach it over loopback — with one
measured exception, the bridge-down `logout` path, which loads the session and
writes Firestore itself.

> ⛔⛔ **THIS FILE WAS CUT DOWN IN 7.9-5 BECAUSE IT KEPT BEING WRONG, TWICE IN ONE
> WAVE.** Its first version undercounted the suite by a factor of three, said "no
> bridge unit test" for routes tested since 7.9-1, and listed 17 of the
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
> ⛔⛔ **AND THEN IT WENT STALE BY 1850 TESTS.** The header said "~2433" and was
> never re-measured through 7.9-5b, waves 1.1 and 1.2, wave 8 and wave 9. SEVEN
> files landed after that sentence was written and they collect **1915** tests
> between them — more than the 1850 the headline was short by, so the old figure
> was not even right for the suite it was describing. Three of the seven
> (`test_router_captures_0911`, `test_bulk_gate_0910`, `test_router_gates_0911`)
> are each larger than any other single file in the suite.
>
> ⛔⛔ **AND THE RUFF SENTENCE WAS WRONG A SECOND TIME.** The confession above
> records "ruff clean" being claimed against six errors; the corrected file then
> claimed it again. There are 11 today — `E731` in `facade/skill/scripts/sr.py`,
> and `F401`/`F541`/`E741` across `test_agent_log_alone_0916`,
> `test_router_captures_0911`, `test_router_gates_0911` and
> `test_wave8_survival_0916`. A lint claim ages exactly as fast as a count.
>
> ⛔ **THE COUNT IS A SNAPSHOT, NOT A GUARD** — a pinned count gets updated by
> whoever makes it red. Re-measure: `pytest tests -q --collect-only | tail -1`.

## Bridge routes — all 40 the dispatcher declares

Third column = test files measured RUNNING that route's handler. A blank means no
test drove it. THREE routes answer inline in the `do_GET`/`do_POST` arm with no
handler method of their own -- `/healthz`, `/login` and `/login/config` -- so
handler instrumentation cannot see them; they are marked rather than credited.

⛔ THAT SET WAS WRONG HERE UNTIL 2026-09-19, and wrong in the direction that
hides coverage. It named four routes including `/icons/<name>` and
`/research/<id>`, both of which DO have handler methods (`_icon` and `_research_status`, both defined in facade/bridge.py), while omitting
`/healthz`, which genuinely is inline in the `do_GET` arm and yet
carries credits the stated method could not have produced. A marker saying "not
measurable" on a route that is measurable retires the question.

| Route | Handler exercised by |
|---|---|
| `/agent-install` | `test_sr_client` |
| `/device` | `test_bridge_device`, `test_device_projection_795` |
| `/device/ask` | `test_public_devices_792` |
| `/device/decide` | `test_owner_verbs_793` |
| `/device/pair` | `test_bridge_device`, `test_cli_device_commands_795`, `test_public_devices_792`, `test_sr_client` |
| `/device/remove` | `test_bridge_device`, `test_cli_device_commands_795`, `test_crossverify_fixes_795`, `test_public_devices_792`, `test_sr_client`, `test_unlink_copy_795` |
| `/device/select` | `test_bridge_device`, `test_device_projection_795`, `test_e2e_lifecycle`, `test_public_devices_792`, `test_sr_client` |
| `/device/visibility` | `test_owner_verbs_793` |
| `/devices` | `test_bridge_device`, `test_bridge_routes`, `test_device_projection_795`, `test_e2e_lifecycle`, `test_signin_once_0901`, `test_sr_attention_copy_0831`, `test_sr_client`, `test_wave8_survival_0916` |
| `/devices/public` | `test_crossverify_fixes_795`, `test_public_devices_792`, `test_sr_client` |
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
| `/logs/agent-log` | `test_agent_log_alone_0916`, `test_agent_log_out_0826` |
| `/logs/bundle` | `test_send_logs_agent_0825` |
| `/logs/runs` | `test_send_logs_agent_0825` |
| `/logs/send` | `test_send_logs_agent_0825` |
| `/research` | `test_bridge_device`, `test_bridge_routes`, `test_e2e_lifecycle`, `test_signin_announce_0826`, `test_sr_client` |
| `/research/<id>` | `test_bridge_resolve_0831` |
| `/research/<id>/cancel` | `test_bridge_device` |
| `/research/<id>/pause` | `test_sr_client` |
| `/research/<id>/podcast` | `test_bridge_routes`, `test_e2e_lifecycle`, `test_sr_client` |
| `/research/<id>/resolve` | `test_bridge_resolve_0831`, `test_sr_attention_copy_0831`, `test_sr_client` |
| `/research/<id>/resume` | `test_bridge_resolve_0831`, `test_sr_client` |
| `/research/<id>/skip` | `test_bridge_device`, `test_e2e_lifecycle`, `test_sr_client` |
| `/research/<id>/stop` | `test_e2e_lifecycle`, `test_sr_client` |
| `/researches` | `test_bridge_device`, `test_bridge_routes` |
| `/shutdown` | `test_bridge_shutdown` |
| `/signin/ack` | `test_signout_closes_signin_0925` |
| `/status` | `test_bridge_remote_login`, `test_e2e_lifecycle`, `test_sr_client` |
| `/updates` | `test_bridge_device`, `test_bridge_resolve_0831`, `test_e2e_lifecycle`, `test_signin_announce_0826`, `test_signin_once_0901`, `test_sr_attention_copy_0831`, `test_sr_client`, `test_stretch45_agent_0827` |
| `/version` | `test_sr_client` |

⛔ **THE CREDIT COLUMN IS A 7.9-5 MEASUREMENT AND IT IS A FLOOR, NOT A CENSUS.**
Four credits above were added afterwards by a DIFFERENT method — reading the
tests — and the mix is recorded here rather than hidden, because hiding a method
change is how the `/healthz` credit happened. The method: a test that stands a
real `ThreadingHTTPServer` on `bridge._make_handler` and then asserts on a given
route's response body has necessarily run that route's handler, which IS
derivable from source where coverage in general is not. The four are
`test_crossverify_fixes_795` on `/devices/public` and `/device/remove`,
`test_agent_log_alone_0916` on `/logs/agent-log`, and `test_wave8_survival_0916`
on `/devices`. ⛔⛔ The first of those shipped in 7.9-5 ITSELF and appeared in no
row of the table 7.9-5 wrote — so a blank cell means nothing was measured, never
that nothing runs it.

⛔⛔ **`GET /login`, `GET /login/config`, `GET /icons/<name>` and `GET /healthz`
ARE THE THIN SPOTS.** `/login/config` and `/login/callback` are covered by
`test_bridge_csrf`; the `/login` PAGE itself, the icon route and `/healthz` are
driven by nothing that asserts their own behaviour — and the row that used to
stand here described `/login` as covered. Recorded, not fixed, in 7.9-5. Still
true on 2026-09-19, but not for the reason first written here: several tests type
the string `/login` (`test_agent_log_alone_0916:251`, `test_empty_state_794`,
`test_routing_794`, `test_public_devices_792`, `test_crossverify_fixes_795`) and
every one of them is asserting on COPY -- what a refusal or a hint says -- rather
than requesting the route. Nothing performs a bare `GET /login`, which is the
gap. ⛔ The sentence that stood here claimed `test_crossverify_fixes_795` was
the only one and that it arrived after 7.9-5; it is neither (those lines shipped
IN 7.9-5, at :166-170). Corrected by cross-verification the same day it was
written -- the conclusion survived, the evidence for it did not.

## Everything else — the suite by area

⭐⭐ THE TABLE ABOVE IS INDEXED BY ROUTE; THIS ONE IS INDEXED BY FILE, and a file
that drives the bridge is in both — above for what its requests ran, below for
what it is for. Counts and grouping were derived on 2026-09-19 from `pytest tests
--collect-only -q`. All **70** test modules in `agent/tests/` are in
exactly one group and the eight groups sum to 4283 (the directory holds 72 `.py`
files; `conftest.py` and `_helpers.py` carry no tests and are not listed): that was CHECKED against the collection
listing, because the last version of this section made the same claim by hand and
two files were in no table at all.

⛔ IT IS STILL A SNAPSHOT AND STILL NOT A GUARD. Nothing makes a new file join a
group; only `test_route_matrix_795.py` fails when this file goes short, and it
only watches the route list.

### The natural-language router — 7 files, 2024 tests

Half the suite. This is `_nl_resolve` in the skill client: the chat runtime hands
it the person's message verbatim and it decides whether to act, on which verb, and
on which machine. It is measured by DRIVING THE LIVE RESOLVER over generated
corpora, never by testing a predicate in isolation — because 7.9-5b's gate scored
52/52 as a predicate while 96 real machine names were unusable across six verbs,
and wave 1's 12,700-phrasing sweep then found 124 defects, 39 of them executing.
The gate half and the capture half are deliberately separate files so a diff in
either is attributable to one kind of change.

| File | Tests | Holds |
|---|---|---|
| `test_router_captures_0911` | 718 | wave 1.2 — what NAME comes out, expected by construction; the politeness word that refused 592 working phrasings |
| `test_bulk_gate_0910` | 661 | 7.9-5b — "all/every/each" as a SET vs a machine actually called that, on a generated two- and three-token name corpus |
| `test_router_gates_0911` | 414 | wave 1.1 — the vetoes, each asserted by where the message LANDS, not by absence |
| `test_routing_794` | 163 | the shared machine-noun list, parametrised over the whole list so a seventh narrow copy fails by name |
| `test_sr_do` | 29 | `sr.py do` — the deterministic NL fallback, with the 2026-07-01 live chat failures as fixtures |
| `test_sr_skip_agents` | 21 | "skip Claude in P2" from chat, matching the app's per-agent toggles |
| `test_negation_apostrophe_0917` | 18 | both apostrophes of one sentence must get the same answer — a Mac's `’` had turned every negation veto off |

### Machines — pairing, selection, visibility, access requests — 12 files, 791 tests

Public computers and who may reach them: a machine's join policy, a stranger
asking to use one, the owner answering, and what a device row is allowed to carry
off the bridge. The through-line is that both clients must word the same decision
the same way, and that no device row leaks a credential.

| File | Tests | Holds |
|---|---|---|
| `test_chat_owner_793` | 227 | the owner verbs on both clients — routing, wording, and the confirm contract |
| `test_chat_public_792` | 144 | the chat surface for public computers: the three verbs and the routing rules that had to sit above two older ones |
| `test_bridge_device` | 96 | the `/device` routes (owned flag, selection) and `/research` device resolution |
| `test_owner_verbs_793` | 62 | answering somebody who asked, and setting who can find a machine at all |
| `test_public_devices_792` | 57 | the bridge's three public-computer routes and the terminal verbs on top of them |
| `test_empty_state_794` | 49 | one wording for "this account has no research computer", on every surface, always offering both ways out |
| `test_wave8_survival_0916` | 48 | the `visibility` → `joinPolicy` rename, the pairing filter that announced "Started" on an unusable machine, and three more silent faults |
| `test_unlink_copy_795` | 45 | `device-remove` telling the truth about the ROTATED pair code, and nine refusals worded identically on both clients |
| `test_wave9_server_stamp_0916` | 21 | the server-stamped heartbeat: decoding `timestampValue` at all, and reading liveness NEW-first while `joinPolicy` reads OLD-first |
| `test_device_projection_795` | 17 | every device row the bridge emits pruned to `_DEVICE_PUBLIC_KEYS` |
| `test_prefs` | 13 | the non-secret prefs store (selected device) |
| `test_cli_device_commands_795` | 12 | `agent device remove` / `agent device add` — the SCREEN, not the helpers |

### Logs — send-logs, and the agent's own log — 11 files, 411 tests

Two different things that keep being confused. A research computer zips and
uploads its OWN logs with its OWN device token, per run, after somebody was shown
what leaves the machine; the agent's `~/.super-agent/bridge.log` is on whatever
host a person is typing on and now travels on its own, with a support code of its
own. Consent is the spine: `consent: true` on the wire is a claim that a person
saw the plan, so the tests pin the plan, not just the flag.

| File | Tests | Holds |
|---|---|---|
| `test_agent_log_out_0826` | 69 | the agent's own log made findable, readable and sendable when asked |
| `test_send_logs_skill_0825` | 65 | `sr.py send-logs` from a chat runtime — the confirm step IS the consent |
| `test_send_logs_cli_0825` | 56 | `agent send-logs` at a terminal — the printed plan is what makes `consent: true` true |
| `test_send_logs_agent_0825` | 45 | asking a research computer for logs from the agent, on a box many people share |
| `test_send_logs_crossverify_791` | 43 | the 38 defects cross-verification found after 7.9-1 was green; the four blockers among them |
| `test_send_logs_picker_791` | 35 | a number for the agent's own log, in a picker that had to be built before it could be added to |
| `test_agent_log_alone_0916` | 35 | wave 8 — the agent log sent with no research computer in the picture, with a code of its own, and the rotated backups |
| `test_chat_picker_791` | 24 | chat naming a subset, and the flags the router emits surviving the trip to argparse |
| `test_log_locality_791` | 19 | where the log lives, where it goes, and the two homes that must not drift apart |
| `test_agent_log_consent_791` | 14 | what a person is told about the agent's log before agreeing to send it |
| `test_logsetup` | 6 | operational logging setup |

### Sign-in, the session, and the two remote stores — 13 files, 270 tests

The bridge is the single owner of the account session; everything else asks it.
This group covers the remote device-flow login, the token cache and its refresh,
the sign-in announce (durable, said once, never lost), and the two things the
agent talks to over HTTP — Firestore REST and the web app's JSON API — both of
which have to force-refresh and retry once on a 401 rather than trust the local
clock.

| File | Tests | Holds |
|---|---|---|
| `test_signin_announce_0826` | 67 | the announce: durable, one clearing point, and a fourth outcome |
| `test_signin_once_0901` | 33 | the announce said ONCE, and never lost |
| `test_agent_session` | 29 | #790 agent-session lifecycle — connect-write, heartbeat, revoke-consult, self-logout |
| `test_firestore_rest` | 28 | the REST client: the value codec, the 401 force-refresh retry, and the device / research / agent-session calls |
| `test_fe_json_792` | 27 | the agent's two JSON calls to the web app — the GET that did not exist, and the POST's missing 401 retry |
| `test_fe_bytes_retry_791` | 19 | the log upload retrying once on a 401 with a freshly minted token |
| `test_remote_autopoll` | 17 | the `serve()`-owned remote-login auto-poller and the shared transition helper (#848) |
| `test_bridge_remote_login` | 11 | the remote-login flow end to end against a mock FE broker |
| `test_session_custom_token` | 10 | `AccountSession.from_custom_token` — the device-flow exchange |
| `test_bridge_csrf` | 9 | the bridge's anti-CSRF and session-fixation defences |
| `test_devicelogin` | 9 | the device-flow HTTP client against a mock broker |
| `test_session` | 6 | the token cache: unexpired hit, rotation on refresh, force-refresh, revoked |
| `test_store` | 5 | the secret store — keyring, and the 0600-file fallback when there is none |

### A run in flight — 5 files, 149 tests

What the agent knows about a run it did not start, and what it tells a person
about one that has stopped needing a human. The planner decides which card a
blocked run is on and what chat can DO about it; the copy tests pin the consumer,
because a planner nobody calls proves nothing.

| File | Tests | Holds |
|---|---|---|
| `test_sr_stream` | 58 | the streaming watchdog (`sr_attention_poll.py`) — quiet until completion, fed by per-run `phaseUpdates` |
| `test_decision_plan_0831` | 38 | the blocked-run planner — which card a run is on, replacing pattern-matching on `pendingDecision.kind` |
| `test_sr_attention_copy_0831` | 24 | what a PERSON is told about a blocked run, in `sr.py` and in the proactive push |
| `test_bridge_resolve_0831` | 22 | the routes that act on a blocked run, over a live loopback bridge: the row read and the route that acts must agree |
| `test_runview` | 7 | `flatten_links` / `is_terminal` — the streaming presentation helpers |

### The host — install, update, autostart, the bridge process — 13 files, 463 tests

Everything between a person's machine and a running bridge: the skill installer,
the durable pipx install the login pin depends on, the self-update floor, the
Windows Scheduled Task, the port the client and the bridge must agree on, and the
teardown verbs.

| File | Tests | Holds |
|---|---|---|
| `test_cli_commands` | 98 | `_disconnect_pairs`, `_logout_session` (the #790 bridge-down row deletion), and the resurrect / retire / disconnect bodies |
| `test_connect` | 69 | `agent connect` — the skill installer |
| `test_stretch45_agent_0827` | 59 | five things the agent side said that were not true — starting with a client and the bridge it just spawned aiming at two different ports |
| `test_durable_install` | 57 | the login pin must never point into pipx's evictable run cache |
| `test_autostart` | 37 | the Windows Scheduled Task — windowless launcher, detached start, `schtasks` argv, non-Windows guards |
| `test_selfupdate` | 36 | PyPI version notices and the detached reconnect spawner |
| `test_selfupdate_version_floor` | 29 | DGOPS-9507 — the monotonicity floor, and the three calls that must NOT carry it |
| `test_cli_parser` | 24 | argument parsing, especially `-v`/`--verbose` in BOTH positions |
| `test_review_wave2_0813` | 20 | `ensure_durable_install()`'s second rung, and the unpadded version comparator that called a good install unusable |
| `test_branding` | 13 | the branded terminal helpers — brand mark, channel row, grouped Next block |
| `test_bridge` | 12 | `serve()`'s port-holder probe — a real bridge on the port vs a foreign squatter |
| `test_sr_update_notice` | 6 | the once-daily skill-update notice cron: fresh check, ONE nudge per new version |
| `test_config` | 3 | the web client config keys, the origins, and the isolated secret-store namespace |

### The guards — what this package says about itself — 5 files, 46 tests

Small, and the reason the rest can be trusted. They run over the shipped text and
the shipped source: the app-plane proof, the claims in `facade/__init__.py` and
`SKILL.md`, the commands `SKILL.md` tells the model to run, the route list in THIS
file, and the repairs a cross-verify round demanded — pinned, because three waves
running, every unpinned repair came back as a surviving mutant.

| File | Tests | Holds |
|---|---|---|
| `test_crossverify_fixes_795` | 17 | the repairs 7.9-5's cross-verify demanded, derived from the findings rather than from my own repair list |
| `test_claims_stay_true_795` | 11 | the claims this package makes about itself — including this file's confession, both directions: the fact present AND the falsehood absent |
| `test_app_plane_unchanged` | 7 | the "app plane unchanged" proof — no facade module imports the research app, and the writer allowlist is derived from the code |
| `test_skill_commands_resolve` | 6 | every command `SKILL.md` tells the agent to run is a REAL `sr.py` subcommand |
| `test_route_matrix_795` | 5 | every route the dispatcher declares is named here, and the count in the prose is the derived one |

### End to end — 4 files, 129 tests

The whole arc through the real surfaces, against a live bridge with a faked
Firestore and a mock FE broker. `test_e2e_lifecycle` and `test_bridge_shutdown`
collect one test each and both are long.

| File | Tests | Holds |
|---|---|---|
| `test_sr_client` | 89 | `facade/skill/scripts/sr.py` loaded the way a runtime loads it, driven against a live bridge |
| `test_bridge_routes` | 38 | the account routes (`/researches`, `/devices`, `/research`) with a fake session |
| `test_e2e_lifecycle` | 1 | the full chat lifecycle: not-signed-in → login → device → enqueue → watch → skip → cancel → logout |
| `test_bridge_shutdown` | 1 | `POST /shutdown` stops the bridge (the host `agent stop`) |

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
