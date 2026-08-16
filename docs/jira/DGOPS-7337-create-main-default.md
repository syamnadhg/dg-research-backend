# Push Instructions — DGOPS-7337 (A1)

**Ticket:** DGOPS-7337 — A1: Create `main` default branch + switch from `DGOPS-6933`
**Status:** Todo
**Priority:** Medium
**Due:** 2026-05-13
**Source:** `dg-project-template/.claude/git-workflow.md` § "New Repository Setup" (lines 220-247)

This MD is the single source you need to finish this task — everything below is taken directly from the org's git-workflow doc, with the placeholders filled in for this repo.

---

## What this task is

The repo `dg-eng/super-research-backend` defaults to `DGOPS-6933` instead of `main`. Per org convention, `main` must be the default branch — org-level branch protection and PR-target conventions depend on it.

The org git-workflow doc says:

> When creating a new GitHub repository in the dg-eng org, the first branch pushed becomes the default. To ensure `main` is the default branch...
>
> The feature branch will be set as default initially. Fix this immediately.

That's exactly the situation here.

---

## Step 1 — Create `main` from the current branch and push

```bash
git checkout -b main DGOPS-6933
git push -u origin main
```

This creates `main` from the current `DGOPS-6933` HEAD and pushes it.

---

## Step 2 — Set `main` as the GitHub default

```bash
gh repo edit dg-eng/super-research-backend --default-branch main
```

---

## Step 3 — Verify

```bash
gh repo view dg-eng/super-research-backend --json defaultBranchRef
```

Expected output:

```json
{"defaultBranchRef":{"name":"main"}}
```

---

## Why this matters (from the org doc)

- Org-level branch protection rules apply to the default branch
- If a feature branch is default, you can't push additional commits to it
- PRs need to target `main`, not a feature branch

---

## Rules from the org git-workflow that apply here

- **Never modify git config.** This task only creates a branch and changes the GitHub default — no config changes needed.
- **No force pushes.** Not needed for this task.
- **Claude stages, authorized developer signs commits.** This task involves no commits (only a branch creation and a `gh` config change), so YubiKey signing doesn't apply to the branch creation itself. From here on, any commits to `main` follow the standard rule:
  ```
  git commit -S -m "<type>(DGOPS-XXXX): <short summary>"
  ```
- **Branch naming going forward:** `feature/DGOPS-XXXX-short-description`, branched from `main`. Never commit directly to `main`.

---

## After

- `DGOPS-6933` stays as a live feature branch — no deletion needed
- Future PRs target `main`
- Branch protection rules from the org template apply automatically
- Mark **DGOPS-7337** as Done in Jira

---

*Compiled 2026-04-29 — single source for DGOPS-7337, sourced verbatim from `dg-project-template/.claude/git-workflow.md`.*
