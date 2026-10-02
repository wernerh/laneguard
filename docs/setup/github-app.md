# Set up the GitHub App (the lane's bot identity)

Lanes must run as their own identity, never as you. Laneguard's rule "only an owner can change protected paths" is only meaningful if the identity a lane uses is not an owner and cannot bypass branch protection. A GitHub App gives you that with short-lived, repository-scoped tokens and no seat or password.

> Status: pre-alpha. The workflow templates and `doctor` exist and have unit tests. They have not been run end to end against live GitHub, so treat the steps below as the intended setup and read the output of `doctor` rather than trusting this page.

## 1. Create the App

GitHub: **Settings > Developer settings > GitHub Apps > New GitHub App** (for an organization, use the organization's settings instead).

| Field | Value |
|---|---|
| Name | Anything unique, for example `<yourname>-laneguard-bot` |
| Homepage URL | Your repository URL |
| Webhook | **Uncheck "Active"**. Lanes poll; they do not need events |
| Where can this app be installed | **Only on this account** |

### Repository permissions

Grant exactly these and nothing else:

| Permission | Access | Why |
|---|---|---|
| Contents | Read and write | Push lane branches, the `laneguard-data` branch and the lock ref |
| Pull requests | Read and write | Open PRs, merge its own labelled PRs in `autonomous` mode |
| Issues | Read and write | Claims, `needs-human` issues, labels, comments (PR comments and labels use the issues API) |
| Commit statuses | Read and write | Post the reviewer verdict as the `laneguard-review` status |
| Metadata | Read-only | Added automatically by GitHub |

### Do not grant

- **Administration.** It would let the bot change branch protection, which defeats every other control. (`doctor` fails a lane token that reports admin or maintain rights.)
- **Workflows.** Without it the bot cannot create or edit anything under `.github/workflows/`, so a lane cannot rewrite its own scheduler or the guard workflow.
- **Secrets, Environments, Actions, organization permissions, Deployments, Pages**, or anything not listed above.

Never use a personal access token for a lane.

## 2. Generate a private key and note the App ID

On the App's settings page, note the **App ID** and click **Generate a private key**. GitHub downloads a `.pem` file. Keep it only long enough to paste it into the secret in step 4, then delete the local copy.

## 3. Install the App on the repository

App settings > **Install App** > choose your account > **Only select repositories** > select the one repository Laneguard will run in. Do not install it on all repositories.

## 4. Store the credentials in the repository

Names must match the lane workflow template (`templates/github/workflows/laneguard-lane.yml.tmpl`, rendered to `.github/workflows/laneguard-lane-<lane>.yml`):

| Kind | Name | Value |
|---|---|---|
| Variable | `LANEGUARD_APP_ID` | The App ID (not secret) |
| Secret | `LANEGUARD_APP_PRIVATE_KEY` | The full contents of the `.pem`, including the `BEGIN` and `END` lines |
| Secret | `ANTHROPIC_API_KEY` | An Anthropic API key used by the lane's Claude Code run |

With the GitHub CLI, run as yourself (an owner), from the repository:

```bash
gh variable set LANEGUARD_APP_ID --body "123456"
gh secret set LANEGUARD_APP_PRIVATE_KEY < path/to/downloaded-key.pem
gh secret set ANTHROPIC_API_KEY            # prompts for the value
```

Use a dedicated Anthropic key with its own spend limit, so a runaway lane cannot spend against your other work. Laneguard's budgets (`budgets.per_run`, `monthly_cost_ceiling_usd`) are a second line of defence, not a replacement.

How the workflow uses them: the first step, `actions/create-github-app-token`, exchanges the App ID and private key for a short-lived installation token. That token (not `GITHUB_TOKEN`, which is read-only here) is what the checkout, `gh` and the guard scripts use. The private key is passed only to that step; the later Claude Code step receives the resulting token and the Anthropic key.

## 5. Why the bot must never be an owner or a bypass actor

- **Owner.** `owners:` in `.laneguard/config.yaml` lists the people who may approve gates, remove pause flags and change protected paths. If the bot were listed, it could approve its own work. `init` refuses a `[bot]` owner, `doctor` fails the `owners` check on one, and `check.py` and `forge.py` refuse to count a bot as an owner even if its name is in the list.
- **CODEOWNERS.** Do not list the bot in `.github/CODEOWNERS`. Code-owner review is what keeps the bot from merging changes to protected paths.
- **Bypass actor.** A ruleset or branch-protection bypass lets an actor merge or push without the required review and checks. If the App were a bypass actor, every other control on the branch would be optional for it. `doctor` fails (`branch.bypass`) when it sees a GitHub App among the bypass actors, and warns when it sees any other bypass actor so you can confirm the bot is not among them.
- **Your own token.** A lane that runs with your token inherits your rights. `doctor --as lane` fails (`token`) when the lane's identity is a configured owner.

## 6. Verify

Run `/laneguard:doctor` (or `python3 .laneguard/guard/doctor.py --as owner`) as yourself to check branch protection, then run it with the lane's installation token (`--as lane`) to check the token. Lanes run `doctor --strict --as lane` before every `autonomous` run and stop if it fails.

## Limits of this setup

- Permission scoping limits what the token can do on GitHub. It does **not** limit what code running in the same job can do with the Anthropic key or with the network. It is not a sandbox; see the [security model](../security-model.md).
- `doctor` can only read the lane token's repository permissions if GitHub returns them for that token; if it cannot, the check is reported as skipped (and fails in `--strict` mode).
- The reviewer verdict (`laneguard-review`) is posted with this same token, so the status is **not** independent of the lane by identity. Its independence is a separate model and a fresh context. Details in the [security model](../security-model.md#known-limits).
