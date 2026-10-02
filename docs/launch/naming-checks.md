# Name availability checks for `laneguard`

All boxes are **unchecked** on purpose: the owner must run these from their own machine and tick them. Where an automated attempt was made while drafting this file, its raw result is recorded under the item, with the date, and is **not** a substitute for the owner's check (it ran from a sandbox behind a proxy; a "not found" from there is a hint, not a clearance).

If a real conflict appears, the fallback shortlist in the [design spec](../design-spec.md#16-open-questions-for-owner) is Sluice, then Portcullis. Do not announce anything until this list is done.

## 1. GitHub

- [ ] No other user or organization named `laneguard`:
  ```bash
  gh api users/laneguard --jq '.login, .type'          # a 404 means the name is free
  ```
- [ ] No notable repositories or projects with the same or a confusingly similar name:
  ```bash
  gh search repos laneguard --limit 20
  gh search repos "lane guard" --limit 20
  gh search code "laneguard" --limit 20
  ```
- [ ] Decide whether to claim a `laneguard` organization to hold the repository (the current repository is `wernerh/laneguard`, and the plugin manifests and `init --engine-repo` default point at it; moving later means updating them).
- [ ] The repository `wernerh/laneguard` exists and is public when you intend to launch:
  ```bash
  gh repo view wernerh/laneguard --json visibility,url
  ```

Automated attempt, 2026-10-02: `gh api users/laneguard` and `gh search` were blocked by the sandbox (HTTP 403, "sessions are bound to their configured repositories"). **Not checked.** `gh api repos/wernerh/laneguard --jq .full_name` returned `wernerh/laneguard`, which only confirms the repository exists.

## 2. Package registries

- [ ] npm (the name is wanted even if the project is not published there, to prevent squatting and confusion):
  ```bash
  npm view laneguard name         # E404 means the name is unclaimed
  npm view @laneguard/cli name    # scope check, if you want a scope
  ```
- [ ] PyPI:
  ```bash
  curl -s -o /dev/null -w '%{http_code}\n' https://pypi.org/pypi/laneguard/json    # 404 means unclaimed
  ```
- [ ] Claim what you want to hold (a placeholder package on npm and/or PyPI), or decide not to.

Automated attempt, 2026-10-02 (about 20:19 UTC), from the sandbox:

```text
$ npm view laneguard name
npm error code E404
npm error 404 Not Found - GET https://registry.npmjs.org/laneguard - Not found
npm error 404  'laneguard@*' is not in this registry.

$ curl -s -o /dev/null -w '%{http_code}' https://pypi.org/pypi/laneguard/json
404
```

Both returned not-found, which suggests the names are unclaimed at that moment. **Owner still has to confirm** and claim them if wanted.

## 3. Domains

- [ ] `laneguard.com`, `laneguard.dev`, `laneguard.io`, `laneguard.ai` (decide which you want):
  ```bash
  for tld in com dev io ai; do echo "== laneguard.$tld"; whois laneguard.$tld | head -15; done
  # or use your registrar's search
  ```
- [ ] If any is already registered, check what is served there:
  ```bash
  curl -sIL https://laneguard.com | head -5
  ```
- [ ] Register the domain you want, or decide none is needed for launch.

Automated attempt, 2026-10-02: `curl` to `laneguard.com` and `laneguard.dev` was blocked by the sandbox proxy (HTTP 403 on CONNECT). **Not checked.**

## 4. Trademark and similar names

Not legal advice; if the project will be commercial or you have any doubt, ask a trademark attorney.

- [ ] USPTO (US) trademark search, wordmark `LANEGUARD` and close variants (`LANE GUARD`, `LANEGAURD`), classes 9 (software), 42 (SaaS and software development), 35 if relevant: https://tmsearch.uspto.gov/
- [ ] WIPO Global Brand Database: https://branddb.wipo.int/
- [ ] EUIPO TMview (EU and other offices): https://www.tmdn.org/tmview/
- [ ] Web search for the name plus "software", "security", "AI", "agents", "GitHub", and each of: `"Laneguard"`, `"Lane Guard"`, `"LaneGuard"`. Note any product in developer tools, security or CI.
- [ ] Check the likely confusables: names with `Guard`/`Lane` in developer-security products (for example, "Lane" and "Guard" product names in CI, security and agent tooling).
- [ ] Check the Claude Code plugin marketplaces and awesome lists for an existing plugin with this name.
- [ ] Record the date, the databases searched and the result here, then decide go or fallback.

Result log (owner fills in):

| Date | Check | Result |
|---|---|---|
| | | |
