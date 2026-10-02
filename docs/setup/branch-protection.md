# Branch protection and rulesets

Branch protection is the enforcement point for "no merge without an owner" and "the checker cannot be skipped". `check.py` only protects you if GitHub refuses to merge when it fails. Set this up before you let any lane open a PR you care about, and re-run `doctor` after any change.

> Status: pre-alpha. The JSON and `gh api` calls below follow GitHub's documented REST API but have not been run against a live repository as part of Laneguard's tests. After applying them, run `doctor` and read what it reports instead of assuming they took effect. The required-check name in particular must be confirmed on a live repository (see [Confirm the check name](#confirm-the-check-name)).

## What to enforce on the default branch

| Rule | Value | Why |
|---|---|---|
| Require a pull request before merging | on | A lane cannot push straight to the default branch |
| Required approving reviews | at least 1 | The review that CODEOWNERS routes to an owner |
| Require review from Code Owners | on | Protected paths need an owner, which the bot is not |
| Dismiss stale approvals on new commits | on (recommended) | An approval should apply to what was reviewed |
| Required status check | `laneguard-guard / check` | Runs `check.py` against the PR diff |
| Required status check, autonomous lanes only | `laneguard-review` | The reviewer's verdict. Without it an `autonomous` lane could merge with no independent review |
| Block force pushes | on | No history rewrite |
| Block deletions | on | The default branch cannot be removed |
| Bypass list | **empty for the lane's App** | Never list the bot. See [GitHub App setup](github-app.md#5-why-the-bot-must-never-be-an-owner-or-a-bypass-actor) |

Also have a CODEOWNERS file (`init` writes one) that names your owners for `/.laneguard/`, `/.github/` and `/.claude/`. Code-owner review does nothing without it.

> **Autonomous mode and the scaffolded CODEOWNERS.** The template CODEOWNERS starts with `* <owners>`, which makes an owner the code owner of every file. With "Require review from Code Owners" on, the bot then cannot merge any PR without an owner approving it, so `autonomous` mode would not merge anything on its own. That is the safe default for `propose`. If you move a lane to `autonomous`, narrow the catch-all line yourself, in an owner-reviewed PR, and keep the protected-path lines. `doctor` only samples the protected paths for CODEOWNERS coverage, so it will pass either way; this is a decision for you, not something `doctor` checks.

> **Solo owner.** GitHub does not let you approve your own PR. If you are the only owner, you cannot satisfy "1 approval from a code owner" on PRs you author. The usual workaround is to put yourself (your user or the Admin role) on the bypass list. `doctor` will WARN `branch.bypass` ("bypass actors are configured; confirm the lane's bot identity is not among them"). That warning is expected for this setup; the thing to check is that the list contains you and not the App. A second owner avoids the issue.

## Option A: a repository ruleset (recommended)

Rulesets are visible to `doctor` through the effective-rules API, which is the most reliable thing it reads.

UI: **Settings > Rules > Rulesets > New ruleset > New branch ruleset**. Enforcement **Active**. Target the default branch. Leave "Bypass list" empty (or, solo owner, add yourself, never the App). Enable: *Restrict deletions*, *Block force pushes*, *Require a pull request before merging* (1 approval, *Require review from Code Owners*, *Dismiss stale pull request approvals*), *Require status checks to pass* (add the checks above).

With the CLI, run as an owner with admin rights on the repository:

```bash
gh api --method POST repos/OWNER/REPO/rulesets --input - <<'JSON'
{
  "name": "laneguard: default branch",
  "target": "branch",
  "enforcement": "active",
  "conditions": { "ref_name": { "include": ["~DEFAULT_BRANCH"], "exclude": [] } },
  "bypass_actors": [],
  "rules": [
    { "type": "deletion" },
    { "type": "non_fast_forward" },
    { "type": "pull_request",
      "parameters": {
        "required_approving_review_count": 1,
        "require_code_owner_review": true,
        "dismiss_stale_reviews_on_push": true,
        "require_last_push_approval": false,
        "required_review_thread_resolution": false
      } },
    { "type": "required_status_checks",
      "parameters": {
        "strict_required_status_checks_policy": false,
        "required_status_checks": [
          { "context": "laneguard-guard / check" }
        ]
      } }
  ]
}
JSON
```

For an `autonomous` lane, add `{ "context": "laneguard-review" }` to `required_status_checks`. The status only exists once a lane has posted it on some commit; GitHub may not offer it in the UI picker until then, but a ruleset created through the API accepts the context name.

## Option B: classic branch protection

```bash
gh api --method PUT repos/OWNER/REPO/branches/main/protection --input - <<'JSON'
{
  "required_status_checks": { "strict": false, "contexts": ["laneguard-guard / check"] },
  "enforce_admins": true,
  "required_pull_request_reviews": {
    "required_approving_review_count": 1,
    "require_code_owner_reviews": true,
    "dismiss_stale_reviews": true
  },
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false
}
JSON
```

Replace `main` with your default branch. Add `"laneguard-review"` to `contexts` for an `autonomous` lane. Classic protection can only be read by `doctor` with enough rights on the repository; if it cannot read it, the check is reported as skipped. Prefer a ruleset.

## Confirm the check name

`doctor` and this page expect the required check to be named exactly `laneguard-guard / check` (workflow `laneguard-guard`, job `check`). Open a pull request on the repository once the guard workflow is in place, then look at the check as GitHub lists it in the ruleset's check picker. If GitHub shows a different name (for example only the job name), a required check with the wrong name will never be satisfied and PRs will wait forever, or `doctor` will report `branch.required-checks` as failed even though a check is set. If that happens, please open an issue: the constant in `guard/doctor.py` and these docs need to agree with what GitHub records.

## Protect the `laneguard-data` branch

Run history (`runs.jsonl`) and pause flags (`PAUSED`, `PAUSED.<lane>`) live on an orphan branch named `laneguard-data`, written by `history.py`. It is never merged and the lane pushes to it directly, so do **not** require pull requests there. Protect it so that history and flags cannot be erased by force-push or branch deletion:

```bash
gh api --method POST repos/OWNER/REPO/rulesets --input - <<'JSON'
{
  "name": "laneguard: data branch",
  "target": "branch",
  "enforcement": "active",
  "conditions": { "ref_name": { "include": ["refs/heads/laneguard-data"], "exclude": [] } },
  "bypass_actors": [
    { "actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "always" }
  ],
  "rules": [
    { "type": "deletion" },
    { "type": "non_fast_forward" }
  ]
}
JSON
```

This blocks everyone except the bypass list from deleting the branch or force-pushing it. The example bypass is the repository **Admin** role (role id 5), which should be you and not the App; check the id against GitHub's current documentation and confirm only owners hold that role. The App has no administration permission, so it cannot use that bypass.

What this does not do: a ruleset cannot stop an ordinary commit that deletes the `PAUSED` file, because that is a normal push. Two other things cover that: `history.py unpause` refuses callers who are not configured owners (enforced by the script, which a lane could in principle go around with raw git), and the lane's tool allowlist denies the obvious commands for it. See [known limits](../security-model.md#known-limits). The lock itself is the ref `refs/laneguard/lock`, which branch rulesets do not cover.

## What `doctor` verifies

`doctor` reads the effective rules for the default branch (and classic protection and rulesets where it can) and reports one check per row. Check ids come from `analyze_rules` in `guard/doctor.py`:

| Check id | PASS when | Otherwise |
|---|---|---|
| `branch.pull-request` | a pull request is required | FAIL |
| `branch.codeowner-review` | code-owner review is required **and** at least 1 approval | FAIL |
| `branch.required-checks` | `laneguard-guard / check` is a required check | FAIL |
| `branch.force-push` | force-pushes are blocked | FAIL |
| `branch.deletion` | deleting the default branch is blocked | WARN |
| `branch.review-check` | `laneguard-review` is required (only evaluated when a lane is in `autonomous` mode) | FAIL |
| `branch.bypass` | no bypass actors | FAIL if a GitHub App is a bypass actor; WARN for any other bypass actor |
| `branch-protection` | (only appears when nothing could be read) | SKIP; a failure under `--strict` |
| `token` | the lane's token has no admin or maintain rights and is not an owner | FAIL, or SKIP if permissions cannot be read |
| `codeowners` | every protected-path sample is owned by a configured owner | FAIL, or WARN if only teams own them |

Run it:

```bash
python3 .laneguard/guard/doctor.py --as owner          # you, checking branch protection
python3 .laneguard/guard/doctor.py --strict --as lane  # what a lane runs before an autonomous run
```

Things `doctor` does **not** check, so you must:

- the `laneguard-data` ruleset above (it reads rules for the default branch only);
- that the bypass list contains you and not the App when the API returns bypass details only on a per-ruleset request (the list endpoint may omit them; check the ruleset in the UI);
- that the required-check name matches what GitHub actually records;
- repository-level settings such as "Allow auto-merge", merge methods, and who has write or admin access.
