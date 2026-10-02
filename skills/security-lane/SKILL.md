---
name: security-lane
description: Parameters and objective for the Laneguard security lane - one gated security fix or hardening task per run, reviewed by reviewer-security. Use when running /laneguard:run security or when a scheduled security lane fires.
---

# Security lane

Run the protocol in the `core` skill. This skill only supplies the lane parameters. If anything here conflicts with `core`, `core` wins.

| Parameter | Value |
|---|---|
| Lane name | `security` |
| Label | `laneguard-security` (from `lanes.security.label` in config) |
| Branch prefix | `laneguard-security/` |
| Owned paths | `docs/security/` (plus the repo source a finding names) |
| Reviewer | `reviewer-security` |
| Default schedule | every 4 hours |

## Objective

Find and close security weaknesses in the project's own code and dependencies, one major task per run, without weakening any control.

## Priority order

1. Open findings from the project's own scanners or advisories that are labelled for this lane, highest severity first.
2. Secrets or credentials found in the repository. Do not echo the value anywhere, including issues, PR text and reports: reference the file and line only, and open a `needs-human` issue because rotation is an owner action.
3. Dependency advisories with a fix available.
4. Hardening items from `docs/security/` that have acceptance criteria in the approved plan.

If nothing qualifies, the run is quiet: report that and stop.

## Lane-specific rules

- A fix must close the finding at its root, not hide the symptom. The reviewer traces the vulnerable path before and after.
- Never disable, loosen or skip a scanner, test, lint rule or threshold to make a finding go away.
- Never touch CI, branch protection, CODEOWNERS, token scopes or tool allowlists. Those are protected paths: a need to change them is a `needs-human` issue.
- Rotating a credential, changing cloud or identity-provider settings, or disclosing a vulnerability to anyone outside the project are owner gates. Stop and open a `needs-human` issue.
- Do not publish exploit details in public issues or PR text. Describe the weakness and the fix at the level a maintainer needs.
