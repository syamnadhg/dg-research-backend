# Eren's PR#2 review — findings & our actions (for the org push + reviewer reply)

**Reviewer:** erenfn-dg (GitHub) — round-2 backend/rules correctness review.
**PR:** Org **PR#2** on `dg-eng/super-research-frontend`, target branch `feature/DGOPS-8545-fe-feedback`.
**Result:** 18 findings — **17 fixed, 1 deferred-by-design** (P3).
**All 17 fixes** landed in ONE FE commit on personal `main`: **`5c44913`** *"fix(fe): resolve PR#2 review round-2 findings (dedup, claim TOCTOU, TTL, rules)"* (+672/−178, 23 files). Two same-day **BE twins** shipped alongside and are live in BE HEAD: HV clean auto-skip `0fde577`, and the L4 agent-side `sr.py` twin `9770c05`.

> This file lives in the **BE repo** (`research-automate/release/`). The org PR is in the **FE repo** — do the push there. Keeping this note out of FE main is deliberate: the org push snapshots FE `main`, so anything tracked there would leak into the org PR.

---

## Findings & resolutions

| # | Sev | Finding | Eren's concern | Our fix | Status |
|---|-----|---------|----------------|---------|--------|
| **F1** | High | Notification dedup not server-authoritative | Client `getDoc` gate is a TOCTOU race across devices/tabs and keys on the inApp inbox doc → duplicate emails, and email/push-only prefs re-send on every listener replay | `api/notify/route.ts`: atomic `create()` of `users/{uid}/notify_dedup/{dedupKey}` gates push+email (2nd request fails `ALREADY_EXISTS`). inApp not gated (idempotent by doc-id). **Fail-open rollback** (marker deleted if neither out-of-band channel delivered) + **7-day TTL**. Client getDoc kept as a cheap pre-filter only. Rule: `notify_dedup` owner-read / `write:if false` | ✅ fixed |
| **F2** | High | `sharedWith` claim drift (TOCTOU) in storage-auth | storage.rules authorizes off the custom **claim**, not the device doc; `setCustomUserClaims` is non-transactional and old code recomputed from a pre-op snapshot → revoked sharer keeps upload / legit sharer 403s | NEW `lib/devices/sync-claim.ts` `syncDeviceClaim()`: projects `device.sharedWith` from a **fresh read** with monotonic `mutSeq` (increment on every sharedWith mutation) + post-write verify loop (re-project ≤5× if mutSeq advanced). Wired into unshare / unpair-self / claim / reset-pair-code | ✅ fixed |
| **F3** | Med | Orphaned cross-tree runs on unpair/owner-unlink | Reset already TTL'd stuck cross-tree runs, but `unpair-self` (full-retire AND owner-unlink) didn't — and device-doc delete doesn't cascade → sharer runs stuck forever, queue subdocs orphaned | NEW `lib/devices/expire-device-runs.ts` `expireOrphanedDeviceRuns()`: TTL-stamps stuck-state researches across user trees + all `devices/{id}/queue` subdocs (by id, works after device-doc delete). Wired into retire + owner-unlink, durable-state-first | ✅ fixed |
| **F4** | Med | TTL field overrides missing from `firestore.indexes.json` | `expireAt` reaping had no declared TTL policies → the fields were inert | Declared all **6** TTL fieldOverrides (`researches`, `queue`, `agentLogins`, `devices`, `pending`, `notify_dedup`). **Deployed 2026-07-11** (additive-first, zero deletions). ⚠️ **re-confirm still live before telling Eren "deployed"** | ✅ fixed |
| **F5** | Low | FCM `createdAt` overwritten every foreground tick | merge-write reset the token's true age → defeats age-based culling | `lib/messaging.ts` `persistFcmToken()`: reads first, writes `createdAt` only on first create; refreshes the rest | ✅ fixed |
| **F6** | Low | `setPendingDecision` dropped re-authored cards | dedup compared only `alert_id+kind+phase` → a body/action rewrite under the same id was silently dropped | `store.ts`: dedup now also requires identical content (title/details/message/reason/type/… + stringified platforms) | ✅ fixed |
| **F7** | Low | announcements cursor poisoned by NaN | `typeof === 'number'` admits NaN → `Math.max(m, NaN)` poisons the cursor → all announcements suppressed | `announcements.ts`: `Number.isFinite()` + unit test | ✅ fixed |
| **L1** | Low | CI actions floating + over-privileged token | floating action tags + `firebase-tools@latest` + default GITHUB_TOKEN scope | `firestore-rules.yml`: `permissions: contents: read`; SHA-pinned checkout/setup-node/setup-java (version in trailing comment); `firebase-tools@15.23.0` | ✅ fixed |
| **L2** | Med | reset-pair-code revoked tokens before the durable flip | irreversible `revokeRefreshTokens` ran before the awaiting-re-pair flip → a later throw bricked the device | `reset-pair-code/route.ts`: token revoke moved to step 5b (after the durable flip commits). + `mutSeq` increment (upholds F2) | ✅ fixed |
| **L3** | Low | install.sh guessable `$$` temp log path | symlink/truncate race on shared `/tmp` | `install.sh`: `mktemp …sr_install.XXXXXX` (atomic 0600, unpredictable) + die-on-fail | ✅ fixed |
| **L4** | Low | `sr.py` `_request` leaked raw tracebacks | non-JSON 200 + socket/OS errors escaped as raw tracebacks to the chat runtime | FE served copy `public/.well-known/skills/sr/scripts/sr.py`: `ValueError`→friendly "unexpected non-JSON reply"; `except OSError`→"bridge unreachable". **BE/agent canonical twin `9770c05`.** ⚠️ **only reaches installers once the agent wheel is republished — done: agent bumped 0.1.24→0.1.25 (`0c9ff46`), wheel built, pending publish** | ✅ fixed |
| **L5** | Low | ChatMessage retry timer never cleared | `setTimeout` with no ref/cleanup → setState-after-unmount | `ChatMessage.tsx`: timer in `retryCooldownRef`, cleared before re-arm + on unmount | ✅ fixed |
| **N1** | Low | Notification email links not absolutized | relative links break in mail clients | `messaging.ts` htmlTemplate: footer/settings links via `appOrigin()` | ✅ fixed |
| **N2** | Low | chat route returned an empty assistant message | `.text()` returns '' when MAX_ROUNDS exhausted mid-tool-call (or SDK throws) | `chat/route.ts`: `.text()` in try/catch → helpful non-empty fallback | ✅ fixed |
| **P1** | High | shares `read` rule allowed signed-out enumeration | single `allow read` over get+list → signed-out `getDocs(shares)` harvests every share + author uid | `firestore.rules`: split into `allow get` (public by unguessable id) + `allow list: if request.auth != null && createdBy == uid`. +7 rules tests. Verified live | ✅ fixed |
| **P2** | Low | apphosting.yaml comments leaked identities | comments named the delegation user + 3 GCP owner accounts | `apphosting.yaml`: comments scrubbed to generic | ✅ fixed |
| **P4** | Med | AudioMiniPlayer didn't auto-advance real tracks | `onEnded` just paused when `audioUrl` is set (the simulated tick that auto-advances is skipped) | `AudioMiniPlayer.tsx`: `onEnded` advances when `hasNext`, else pauses | ✅ fixed |
| **P3** | Low | deauth-device path performs a device-doc read | flagged as tightenable/removable | **DEFERRED BY DESIGN** — removing it re-arms the #723 sharer-rehydration / per-doc `deviceId` rules fast-path race (`0fc009a`). Kept intentionally | ⏸ deferred |

### Reply to Eren (summary)
> 17 of 18 addressed in `5c44913` (server-authoritative dedup, fresh-read `sharedWith` claim with `mutSeq`, cross-tree orphan TTL cleanup, the 6 declared TTL overrides, the shares `get`/`list` split, + the low/medium hardening items). The **one** item not changed is **P3** (the deauth-device device-doc read) — kept intentionally, because removing it re-arms the #723 per-doc-`deviceId` rules fast-path race (`0fc009a`). Happy to revisit if you'd prefer a different guard there.

⚠️ Before telling Eren "F4/P1 are deployed," **re-confirm live**: the 6 TTL fieldOverrides and the shares `get`/`list` split (they were deployed 2026-07-11; verify they're still applied).

---

## Org push recipe (run on Mac, in the **FE** repo)

Org gating: **personal is default; org push only when explicitly asked + confirmed each push.** I stage/propose, I never commit to org. **NO AI attribution / `Co-Authored-By` in org commit messages.**

```bash
cd <research-app/web>                              # FE repo; remote `org` = dg-eng/super-research-frontend
git fetch org
git checkout feature/DGOPS-8545-fe-feedback        # the org PR branch (was at 576c914)
git checkout main -- .                             # snapshot current personal main onto the branch
# delete the 5 oauth routes removed by #927 (present on the org branch, absent on main — a checkout won't remove them):
git rm src/app/api/oauth/google/callback/route.ts \
       src/app/api/oauth/google/disconnect/route.ts \
       src/app/api/oauth/google/start/route.ts \
       src/app/api/oauth/request-access/route.ts \
       src/app/api/oauth/validate/route.ts
# keep .claude/git-workflow.md
git commit -S -F <org_commit_msg.txt>              # YubiKey-signed; write a CLEAN org message, NO AI attribution
git push org HEAD:feature/DGOPS-8545-fe-feedback
# verify CI: .github/workflows/firestore-rules.yml (rules + unit gates)
```

### ⚠️ Decision before you push — it's a **superset**, not a 1:1 of the review
Personal `main` is **~26+ commits past** the review-fix commit `5c44913`. `git checkout main -- .`
carries **all** of that later work into the org PR — the #955 alert overhaul, sharer-keys #938,
delivery-aware completion, etc. — not just the 17-finding batch. **Decide:**
- **push the whole current `main`** (tell Eren the PR update is a superset of his review + the later work), **or**
- **cherry-pick just the review batch** (`5c44913` + the specific follow-ups) onto the org branch for a 1:1 mapping to his review.

Status: org branch still at `576c914` (only the 2 initial-import commits); `5c44913` is reachable only from personal `main`. Task **#935** (org push) remains open.
