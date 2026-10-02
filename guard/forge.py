#!/usr/bin/env python3
"""forge.py: the only way Laneguard talks to GitHub.

Everything a lane reads from or writes to the forge goes through this adapter, so other forges are
an adapter and not a rewrite. It enforces three things the model must not be trusted to do itself:

  * server time: ``now`` is the Date header of a GitHub API response, never the local clock;
  * trust: ``trust`` decides whether an issue may be acted on, and ``approvals`` verifies
    ``/approve <gate>`` comments (listed owner, real person, never edited after posting);
  * a write allowlist: only issues, pull requests, labels and comments on THIS repository, plus
    the single ``laneguard-review`` commit-status context that carries the reviewer's verdict.
    Secrets, workflows, settings, releases and other repositories are refused before any request.

All text that originates from users is returned under keys prefixed ``untrusted_`` so downstream
agents can see at a glance what is data. Transport is the ``gh`` CLI (GH_TOKEN is honoured).

Python 3, standard library only.

Usage (all output is JSON on stdout):
  forge.py now
  forge.py whoami
  forge.py permission LOGIN
  forge.py trust --issue N
  forge.py approvals --target issue|pr --number N --gate GATE
  forge.py read issue N | pr N | issues [--label L] | prs [--label L] | comments N | ci [--ref REF] | claims [--lane L]
  forge.py write comment --number N --body-file F
  forge.py write label-add|label-remove --number N --label L
  forge.py write issue --title T --body-file F [--label L ...]
  forge.py write pr --head B --base B --title T --body-file F [--label L ...]
  forge.py write merge --number N [--method squash|merge|rebase]
  forge.py write review-status --sha SHA --verdict APPROVE|REQUEST_CHANGES|BLOCK --lane LANE
  forge.py write claim --number N --lane LANE --run-id ID
  forge.py rules [--branch B]

Exit codes: 0 ok; 1 refused or condition not satisfied; 2 usage, config or transport error.
"""
from __future__ import annotations

import argparse
import datetime as dt
import email.utils
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import laneconfig  # noqa: E402

TRIAGE_PLUS = {"triage", "write", "maintain", "admin"}
HUMAN_ASSOCIATIONS = {"OWNER", "MEMBER", "COLLABORATOR"}
READY_LABEL = "laneguard-ready"
CLAIM_MARKER = "laneguard-claim"
REVIEW_CONTEXT = "laneguard-review"
MAX_BODY_CHARS = 6000


class ForgeError(RuntimeError):
    """Transport or protocol failure."""


class ForgeDenied(PermissionError):
    """The adapter refused a request because it is outside the allowlist."""


class Response:
    def __init__(self, status: int, headers: dict, data):
        self.status = status
        self.headers = {k.lower(): v for k, v in headers.items()}
        self.data = data


class GhTransport:
    """Runs ``gh api -i`` and parses the HTTP status line, headers and JSON body."""

    def request(self, method: str, path: str, body: Optional[dict] = None) -> Response:
        cmd = ["gh", "api", "-i", "-X", method, path]
        if body is not None:
            cmd += ["--input", "-"]
        try:
            p = subprocess.run(cmd, input=json.dumps(body) if body is not None else None,
                               capture_output=True, text=True, timeout=120)
        except FileNotFoundError:
            raise ForgeError("the gh CLI is not installed")
        except subprocess.TimeoutExpired:
            raise ForgeError(f"gh api timed out: {method} {path}")
        out = p.stdout.replace("\r\n", "\n")
        head, sep, payload = out.partition("\n\n")
        lines = head.split("\n")
        if not lines or not lines[0].startswith("HTTP/"):
            raise ForgeError(f"gh api gave no HTTP response: {(p.stderr or out).strip()[:300]}")
        try:
            status = int(lines[0].split()[1])
        except (IndexError, ValueError):
            raise ForgeError(f"unparseable status line: {lines[0]!r}")
        headers = {}
        for ln in lines[1:]:
            k, _, v = ln.partition(":")
            if _:
                headers[k.strip()] = v.strip()
        data = None
        if payload.strip():
            try:
                data = json.loads(payload)
            except ValueError:
                data = payload
        return Response(status, headers, data)


# Letters from other scripts that render like ASCII; folded before scanning so lookalikes cannot hide a phrase.
_CONFUSABLES = {
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x", "і": "i", "ј": "j", "ѕ": "s",
    "ԁ": "d", "һ": "h", "ո": "n", "ս": "u", "ᴠ": "v", "ɡ": "g", "ɑ": "a", "ο": "o", "ν": "v", "ι": "i",
    "τ": "t", "α": "a", "ρ": "p", "κ": "k", "μ": "u", "ɩ": "i",
}


def _fold(text: str) -> str:
    import unicodedata
    t = unicodedata.normalize("NFKC", text)
    t = re.sub("[\u200b-\u200f\u2060\ufeff\u202a-\u202e]", "", t)
    return "".join(_CONFUSABLES.get(c, _CONFUSABLES.get(c.lower(), c)) for c in t)


def scan_untrusted(text: str) -> list:
    """Cheap heuristics that flag text trying to steer an agent. Flags are advisory data for the
    observer; the real defence is that nothing downstream ever reads the raw text."""
    if not text:
        return []
    flags = []
    folded = _fold(text)
    low = folded.lower()
    rules = {
        "instruction-override": r"ignore (all |any |the )?(previous|prior|above|earlier) (instructions|rules|prompts?)|disregard (the )?(system|previous|above)",
        "role-reassignment": r"you are now |act as (the )?(owner|admin|maintainer)|new instructions:",
        "authority-claim": r"(i am|this is|message from) (the )?(owner|admin|maintainer|anthropic|system)|on behalf of (the )?(owner|admin)",
        "approval-claim": r"(owner|maintainer) (has )?(already )?(approved|authorized|authorised|pre-?approved)|/approve\b",
        "protected-path-request": r"\.laneguard/(guard|config)|\.github/(workflows|codeowners)|\.claude/",
        "secret-request": r"(print|reveal|show|send|echo|cat|exfiltrate|upload).{0,40}(env(ironment)?|secret|token|api[_ -]?key|password|credential)",
        "contact-or-publish": r"(email|message|post to|tweet|publish|send to|notify) .{0,40}(@|https?://)",
        "skip-review": r"skip (the )?(review|tests?|checks?|ci)|merge (this )?(immediately|now|without)|force[- ]push|--no-verify",
        "urgency-pressure": r"\b(urgent|immediately|asap|right now|emergency)\b.{0,40}(merge|deploy|bypass|disable)",
    }
    for name, rx in rules.items():
        if re.search(rx, low):
            flags.append(name)
    if re.search(r"[​‌‍⁠﻿‪-‮]", text):
        flags.append("hidden-characters")
    if re.search(r"(?:[A-Za-z0-9+/]{60,}={0,2})", text):
        flags.append("encoded-blob")
    if re.search(r"<!--.*?-->", text, re.S):
        flags.append("html-comment")
    return flags


def _truncate(text: Optional[str]) -> str:
    text = text or ""
    if len(text) > MAX_BODY_CHARS:
        return text[:MAX_BODY_CHARS] + f"\n[truncated {len(text) - MAX_BODY_CHARS} characters]"
    return text


class Forge:
    def __init__(self, repo: str, owners, approvals_required: int = 1, transport=None,
                 claim_expiry_hours: int = 24):
        self.repo = repo
        self.owners = {o.lower() for o in owners}
        self.approvals_required = approvals_required
        self.claim_expiry_hours = claim_expiry_hours
        self.t = transport if transport is not None else GhTransport()
        self._perm_cache: dict = {}

    # ------------------------------------------------------------------ allowlists

    def _read_allowed(self, path: str) -> bool:
        p = path.split("?", 1)[0]
        r = re.escape(self.repo)
        if p in ("/rate_limit", "/user", "/installation/repositories"):
            return True
        if re.search(r"/(secrets|variables)(/|$)", p) or "/environments/" in p or "/actions/runners" in p:
            return False
        return re.fullmatch(rf"/repos/{r}(/.*)?", p) is not None

    def _write_allowed(self, method: str, path: str) -> bool:
        r = re.escape(self.repo)
        p = path.split("?", 1)[0]
        table = [
            ("POST", rf"/repos/{r}/issues"),
            ("POST", rf"/repos/{r}/issues/\d+/comments"),
            ("POST", rf"/repos/{r}/issues/\d+/labels"),
            ("DELETE", rf"/repos/{r}/issues/\d+/labels/[^/]+"),
            ("POST", rf"/repos/{r}/labels"),
            ("POST", rf"/repos/{r}/pulls"),
            ("PATCH", rf"/repos/{r}/pulls/\d+"),
            ("PUT", rf"/repos/{r}/pulls/\d+/merge"),
            ("POST", rf"/repos/{r}/statuses/[0-9a-f]{{40}}"),
        ]
        return any(m == method and re.fullmatch(rx, p) for m, rx in table)

    def _get(self, path: str):
        if not self._read_allowed(path):
            raise ForgeDenied(f"read refused (outside this repository's allowlist): GET {path}")
        res = self.t.request("GET", path)
        if res.status >= 400:
            raise ForgeError(f"GET {path} -> {res.status}: {str(res.data)[:200]}")
        return res

    def _get_soft(self, path: str):
        """Like _get but returns None on 403/404 (for optional lookups)."""
        if not self._read_allowed(path):
            raise ForgeDenied(f"read refused (outside this repository's allowlist): GET {path}")
        res = self.t.request("GET", path)
        if res.status in (403, 404):
            return None
        if res.status >= 400:
            raise ForgeError(f"GET {path} -> {res.status}: {str(res.data)[:200]}")
        return res

    def _write(self, method: str, path: str, body: Optional[dict] = None):
        if not self._write_allowed(method, path):
            raise ForgeDenied(f"write refused (only issues, PRs, labels and comments on {self.repo} are allowed): "
                              f"{method} {path}")
        if "/statuses/" in path and (body or {}).get("context") != REVIEW_CONTEXT:
            raise ForgeDenied(f"only the '{REVIEW_CONTEXT}' status context may be written")
        res = self.t.request(method, path, body)
        if res.status >= 400:
            raise ForgeError(f"{method} {path} -> {res.status}: {str(res.data)[:300]}")
        return res.data

    def _paginate(self, path: str, limit_pages: int = 10) -> list:
        out: list = []
        sep = "&" if "?" in path else "?"
        for page in range(1, limit_pages + 1):
            res = self._get(f"{path}{sep}per_page=100&page={page}")
            data = res.data if isinstance(res.data, list) else []
            out.extend(data)
            if len(data) < 100:
                break
        return out

    # ------------------------------------------------------------------ identity and time

    def now(self) -> dt.datetime:
        res = self._get("/rate_limit")
        date = res.headers.get("date")
        if not date:
            raise ForgeError("the forge response carried no Date header; refusing to guess the time")
        t = email.utils.parsedate_to_datetime(date)
        if t.tzinfo is None:
            t = t.replace(tzinfo=dt.timezone.utc)
        return t.astimezone(dt.timezone.utc)

    def whoami(self) -> Optional[str]:
        res = self.t.request("GET", "/user")
        if res.status >= 400 or not isinstance(res.data, dict):
            return None  # e.g. a GitHub App installation token: not a person, therefore not an owner
        return res.data.get("login")

    def is_owner(self, login: Optional[str]) -> bool:
        return bool(login) and login.lower() in self.owners and not login.endswith("[bot]")

    def permission(self, login: str) -> str:
        key = login.lower()
        if key in self._perm_cache:
            return self._perm_cache[key]
        res = self._get_soft(f"/repos/{self.repo}/collaborators/{login}/permission")
        level = "none"
        if res is not None and isinstance(res.data, dict):
            level = res.data.get("role_name") or res.data.get("permission") or "none"
        self._perm_cache[key] = level
        return level

    def _is_trusted_person(self, login: Optional[str], user_type: str = "User") -> bool:
        if not login or user_type == "Bot" or login.endswith("[bot]"):
            return False
        return self.is_owner(login) or self.permission(login) in TRIAGE_PLUS

    # ------------------------------------------------------------------ trust

    def trust_issue(self, number: int) -> dict:
        issue = self._get(f"/repos/{self.repo}/issues/{number}").data
        creator = (issue.get("user") or {}).get("login")
        ctype = (issue.get("user") or {}).get("type", "User")
        labels = [l.get("name") for l in issue.get("labels", [])]
        creator_ok = self._is_trusted_person(creator, ctype)
        labeler = None
        labeler_ok = False
        if READY_LABEL in labels:
            events = self._paginate(f"/repos/{self.repo}/issues/{number}/events")
            relevant = [e for e in events if e.get("event") in ("labeled", "unlabeled")
                        and (e.get("label") or {}).get("name") == READY_LABEL]
            if relevant and relevant[-1].get("event") == "labeled":
                actor = relevant[-1].get("actor") or {}
                labeler = actor.get("login")
                labeler_ok = self._is_trusted_person(labeler, actor.get("type", "User"))
        trusted = creator_ok or labeler_ok
        reason = ("created by an owner or collaborator with triage permission or higher" if creator_ok
                  else f"'{READY_LABEL}' applied by a trusted user" if labeler_ok
                  else "created by and labelled by users who are neither owners nor triage-level collaborators")
        return {"issue": number, "trusted": trusted, "reason": reason, "creator": creator,
                "creator_trusted": creator_ok, "ready_labeler": labeler, "ready_labeler_trusted": labeler_ok}

    # ------------------------------------------------------------------ approvals

    def approvals(self, target: str, number: int, gate: str) -> dict:
        approvers: list = []
        rejected: list = []
        comments = self._paginate(f"/repos/{self.repo}/issues/{number}/comments")
        want = re.compile(rf"^/approve\s+{re.escape(gate)}\s*$", re.I)
        for c in comments:
            first = (c.get("body") or "").strip().split("\n", 1)[0].strip()
            if not want.match(first):
                continue
            user = c.get("user") or {}
            login = user.get("login")
            why = None
            if user.get("type") == "Bot" or (login or "").endswith("[bot]"):
                why = "author is a bot"
            elif not self.is_owner(login):
                why = "author is not listed in owners"
            elif c.get("author_association") not in HUMAN_ASSOCIATIONS:
                why = f"author association is {c.get('author_association')!r}"
            elif c.get("updated_at") != c.get("created_at"):
                why = "comment was edited after posting"
            if why:
                rejected.append({"login": login, "reason": why, "comment_id": c.get("id")})
            elif login.lower() not in [a.lower() for a in approvers]:
                approvers.append(login)
        if target == "pr" and gate == "merge":
            pr = self._get(f"/repos/{self.repo}/pulls/{number}").data
            head = (pr.get("head") or {}).get("sha")
            latest: dict = {}
            for r in self._paginate(f"/repos/{self.repo}/pulls/{number}/reviews"):
                u = (r.get("user") or {}).get("login")
                if u and r.get("state") in ("APPROVED", "CHANGES_REQUESTED", "DISMISSED"):
                    latest[u.lower()] = r
            for u, r in latest.items():
                login = (r.get("user") or {}).get("login")
                if r.get("state") != "APPROVED":
                    continue
                if (r.get("user") or {}).get("type") == "Bot" or not self.is_owner(login):
                    rejected.append({"login": login, "reason": "review author is not a listed owner"})
                elif r.get("commit_id") != head:
                    rejected.append({"login": login, "reason": "approval is for an older commit than the PR head"})
                elif login.lower() not in [a.lower() for a in approvers]:
                    approvers.append(login)
        return {"satisfied": len(approvers) >= self.approvals_required, "gate": gate, "target": target,
                "number": number, "approvers": approvers, "required": self.approvals_required,
                "rejected": rejected}

    # ------------------------------------------------------------------ reads

    def _label_names(self, item: dict) -> list:
        return [l.get("name") for l in item.get("labels", [])]

    def read_issue(self, number: int) -> dict:
        i = self._get(f"/repos/{self.repo}/issues/{number}").data
        trust = self.trust_issue(number)
        body = i.get("body") or ""
        return {
            "number": number, "state": i.get("state"), "labels": self._label_names(i),
            "author": (i.get("user") or {}).get("login"), "is_pull_request": "pull_request" in i,
            "trust": trust,
            "untrusted_title": i.get("title"), "untrusted_body": _truncate(body),
            "untrusted_flags": scan_untrusted((i.get("title") or "") + "\n" + body),
            "created_at": i.get("created_at"), "updated_at": i.get("updated_at"),
        }

    def read_comments(self, number: int) -> list:
        out = []
        for c in self._paginate(f"/repos/{self.repo}/issues/{number}/comments"):
            body = c.get("body") or ""
            out.append({
                "id": c.get("id"), "author": (c.get("user") or {}).get("login"),
                "association": c.get("author_association"), "created_at": c.get("created_at"),
                "edited": c.get("updated_at") != c.get("created_at"),
                "untrusted_body": _truncate(body), "untrusted_flags": scan_untrusted(body),
            })
        return out

    def read_issues(self, label: Optional[str] = None, state: str = "open") -> list:
        q = f"/repos/{self.repo}/issues?state={state}"
        if label:
            q += f"&labels={label}"
        out = []
        for i in self._paginate(q):
            if "pull_request" in i:
                continue
            out.append({
                "number": i.get("number"), "labels": self._label_names(i),
                "author": (i.get("user") or {}).get("login"),
                "author_association": i.get("author_association"),
                "untrusted_title": i.get("title"),
                "untrusted_flags": scan_untrusted((i.get("title") or "") + "\n" + (i.get("body") or "")),
                "created_at": i.get("created_at"), "updated_at": i.get("updated_at"),
            })
        return out

    def read_prs(self, label: Optional[str] = None, state: str = "open") -> list:
        out = []
        for p in self._paginate(f"/repos/{self.repo}/pulls?state={state}"):
            labels = self._label_names(p)
            if label and label not in labels:
                continue
            out.append({
                "number": p.get("number"), "labels": labels, "author": (p.get("user") or {}).get("login"),
                "head": (p.get("head") or {}).get("ref"), "head_sha": (p.get("head") or {}).get("sha"),
                "draft": p.get("draft"), "untrusted_title": p.get("title"),
                "created_at": p.get("created_at"), "updated_at": p.get("updated_at"),
            })
        return out

    def read_pr(self, number: int) -> dict:
        p = self._get(f"/repos/{self.repo}/pulls/{number}").data
        body = p.get("body") or ""
        return {
            "number": number, "state": p.get("state"), "merged": p.get("merged"),
            "labels": self._label_names(p), "author": (p.get("user") or {}).get("login"),
            "head": (p.get("head") or {}).get("ref"), "head_sha": (p.get("head") or {}).get("sha"),
            "base": (p.get("base") or {}).get("ref"), "mergeable_state": p.get("mergeable_state"),
            "untrusted_title": p.get("title"), "untrusted_body": _truncate(body),
            "untrusted_flags": scan_untrusted((p.get("title") or "") + "\n" + body),
        }

    def read_ci(self, ref: Optional[str] = None) -> dict:
        if ref is None:
            ref = self._get(f"/repos/{self.repo}").data.get("default_branch", "main")
        data = self._get(f"/repos/{self.repo}/commits/{ref}/check-runs?per_page=100").data
        runs = [{"name": r.get("name"), "status": r.get("status"), "conclusion": r.get("conclusion")}
                for r in (data or {}).get("check_runs", [])]
        failing = [r for r in runs if r["conclusion"] in ("failure", "timed_out", "cancelled", "action_required")]
        pending = [r for r in runs if r["status"] != "completed"]
        state = "failure" if failing else "pending" if pending else "success" if runs else "none"
        return {"ref": ref, "state": state, "runs": runs}

    def claims(self, lane: Optional[str] = None) -> list:
        """Active issue claims: a claim comment younger than claim_expiry_hours, or one with an open PR."""
        now = self.now()
        ttl = dt.timedelta(hours=self.claim_expiry_hours)
        open_prs = self._paginate(f"/repos/{self.repo}/pulls?state=open")
        out = []
        for i in self._paginate(f"/repos/{self.repo}/issues?state=open"):
            if "pull_request" in i:
                continue
            n = i.get("number")
            for c in self._paginate(f"/repos/{self.repo}/issues/{n}/comments"):
                m = re.match(rf"<!-- {CLAIM_MARKER} lane=([a-z0-9-]+) run=([^ ]+) -->", (c.get("body") or "").strip())
                if not m:
                    continue
                if lane and m.group(1) != lane:
                    continue
                created = dt.datetime.strptime(c["created_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
                has_pr = any(re.search(rf"(?<![0-9])#{n}(?![0-9])", (p.get("body") or "")) for p in open_prs)
                age = now - created
                out.append({"issue": n, "lane": m.group(1), "run_id": m.group(2), "claimed_at": c["created_at"],
                            "age_hours": round(age.total_seconds() / 3600, 1), "has_open_pr": has_pr,
                            "active": has_pr or age < ttl})
        return out

    def rules(self, branch: Optional[str] = None) -> dict:
        repo = self._get(f"/repos/{self.repo}").data
        branch = branch or repo.get("default_branch", "main")
        eff = self._get_soft(f"/repos/{self.repo}/rules/branches/{branch}")
        classic = self._get_soft(f"/repos/{self.repo}/branches/{branch}/protection")
        rulesets = self._get_soft(f"/repos/{self.repo}/rulesets")
        return {
            "branch": branch, "default_branch": repo.get("default_branch"),
            "permissions": repo.get("permissions"), "visibility": repo.get("visibility"),
            "effective_rules": eff.data if eff is not None else None,
            "classic_protection": classic.data if classic is not None else None,
            "rulesets": rulesets.data if rulesets is not None else None,
        }

    # ------------------------------------------------------------------ writes

    def comment(self, number: int, body: str) -> dict:
        d = self._write("POST", f"/repos/{self.repo}/issues/{number}/comments", {"body": body})
        return {"id": d.get("id"), "url": d.get("html_url")}

    def label_add(self, number: int, label: str) -> dict:
        self._write("POST", f"/repos/{self.repo}/issues/{number}/labels", {"labels": [label]})
        return {"ok": True}

    def label_remove(self, number: int, label: str) -> dict:
        from urllib.parse import quote
        self._write("DELETE", f"/repos/{self.repo}/issues/{number}/labels/{quote(label, safe='')}")
        return {"ok": True}

    def create_issue(self, title: str, body: str, labels=()) -> dict:
        d = self._write("POST", f"/repos/{self.repo}/issues", {"title": title, "body": body, "labels": list(labels)})
        return {"number": d.get("number"), "url": d.get("html_url")}

    def create_pr(self, head: str, base: str, title: str, body: str, labels=()) -> dict:
        d = self._write("POST", f"/repos/{self.repo}/pulls", {"head": head, "base": base, "title": title, "body": body})
        if labels:
            self._write("POST", f"/repos/{self.repo}/issues/{d['number']}/labels", {"labels": list(labels)})
        return {"number": d.get("number"), "url": d.get("html_url")}

    def merge_pr(self, number: int, method: str = "squash") -> dict:
        if method not in ("squash", "merge", "rebase"):
            raise ForgeDenied(f"unknown merge method {method!r}")
        d = self._write("PUT", f"/repos/{self.repo}/pulls/{number}/merge", {"merge_method": method})
        return {"merged": d.get("merged"), "sha": d.get("sha")}

    def post_review_status(self, sha: str, verdict: str, lane: str) -> dict:
        """Publish the independent reviewer's verdict as the required ``laneguard-review`` status.
        APPROVE -> success; anything else -> failure. Only this one context can ever be written."""
        state = "success" if verdict == "APPROVE" else "failure"
        body = {"state": state, "context": REVIEW_CONTEXT,
                "description": f"reviewer-{lane}: {verdict}"[:140]}
        self._write("POST", f"/repos/{self.repo}/statuses/{sha}", body)
        return {"sha": sha, "state": state}

    def claim(self, number: int, lane: str, run_id: str) -> dict:
        body = f"<!-- {CLAIM_MARKER} lane={lane} run={run_id} -->\nLaneguard `{lane}` lane claimed this issue (run `{run_id}`)."
        return self.comment(number, body)


def from_config(root: str = ".", transport=None) -> Forge:
    cfg = laneconfig.load_config(root=root)
    return Forge(cfg["repo"], cfg["owners"], cfg.get("approvals_required", 1), transport=transport,
                 claim_expiry_hours=cfg["limits"]["claim_expiry_hours"])


def _emit(obj) -> None:
    print(json.dumps(obj, indent=2, sort_keys=True, default=str))


def main(argv=None, forge: Optional[Forge] = None) -> int:
    ap = argparse.ArgumentParser(prog="forge.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", default=".")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("now")
    sub.add_parser("whoami")
    p = sub.add_parser("permission"); p.add_argument("login")
    p = sub.add_parser("trust"); p.add_argument("--issue", type=int, required=True)
    p = sub.add_parser("approvals")
    p.add_argument("--target", choices=["issue", "pr"], required=True)
    p.add_argument("--number", type=int, required=True)
    p.add_argument("--gate", required=True)
    p = sub.add_parser("rules"); p.add_argument("--branch")
    r = sub.add_parser("read")
    rs = r.add_subparsers(dest="what", required=True)
    for w in ("issue", "pr", "comments"):
        q = rs.add_parser(w); q.add_argument("number", type=int)
    for w in ("issues", "prs"):
        q = rs.add_parser(w); q.add_argument("--label"); q.add_argument("--state", default="open")
    q = rs.add_parser("ci"); q.add_argument("--ref")
    q = rs.add_parser("claims"); q.add_argument("--lane")
    w = sub.add_parser("write")
    ws = w.add_subparsers(dest="what", required=True)
    q = ws.add_parser("comment"); q.add_argument("--number", type=int, required=True); q.add_argument("--body-file", required=True)
    for n in ("label-add", "label-remove"):
        q = ws.add_parser(n); q.add_argument("--number", type=int, required=True); q.add_argument("--label", required=True)
    q = ws.add_parser("issue"); q.add_argument("--title", required=True); q.add_argument("--body-file", required=True)
    q.add_argument("--label", action="append", default=[])
    q = ws.add_parser("pr")
    q.add_argument("--head", required=True); q.add_argument("--base", required=True)
    q.add_argument("--title", required=True); q.add_argument("--body-file", required=True)
    q.add_argument("--label", action="append", default=[])
    q = ws.add_parser("merge"); q.add_argument("--number", type=int, required=True)
    q.add_argument("--method", default="squash")
    q = ws.add_parser("review-status"); q.add_argument("--sha", required=True)
    q.add_argument("--verdict", required=True, choices=["APPROVE", "REQUEST_CHANGES", "BLOCK"])
    q.add_argument("--lane", required=True)
    q = ws.add_parser("claim"); q.add_argument("--number", type=int, required=True)
    q.add_argument("--lane", required=True); q.add_argument("--run-id", required=True)
    args = ap.parse_args(argv)

    try:
        f = forge or from_config(args.root)
        if args.cmd == "now":
            _emit({"now": f.now().strftime("%Y-%m-%dT%H:%M:%SZ")})
        elif args.cmd == "whoami":
            login = f.whoami()
            _emit({"login": login, "is_owner": f.is_owner(login)})
        elif args.cmd == "permission":
            _emit({"login": args.login, "permission": f.permission(args.login)})
        elif args.cmd == "trust":
            res = f.trust_issue(args.issue)
            _emit(res)
            return 0 if res["trusted"] else 1
        elif args.cmd == "approvals":
            res = f.approvals(args.target, args.number, args.gate)
            _emit(res)
            return 0 if res["satisfied"] else 1
        elif args.cmd == "rules":
            _emit(f.rules(args.branch))
        elif args.cmd == "read":
            if args.what == "issue":
                _emit(f.read_issue(args.number))
            elif args.what == "pr":
                _emit(f.read_pr(args.number))
            elif args.what == "comments":
                _emit(f.read_comments(args.number))
            elif args.what == "issues":
                _emit(f.read_issues(args.label, args.state))
            elif args.what == "prs":
                _emit(f.read_prs(args.label, args.state))
            elif args.what == "ci":
                _emit(f.read_ci(args.ref))
            elif args.what == "claims":
                _emit(f.claims(args.lane))
        elif args.cmd == "write":
            if args.what == "comment":
                _emit(f.comment(args.number, Path(args.body_file).read_text()))
            elif args.what == "label-add":
                _emit(f.label_add(args.number, args.label))
            elif args.what == "label-remove":
                _emit(f.label_remove(args.number, args.label))
            elif args.what == "issue":
                _emit(f.create_issue(args.title, Path(args.body_file).read_text(), args.label))
            elif args.what == "pr":
                _emit(f.create_pr(args.head, args.base, args.title, Path(args.body_file).read_text(), args.label))
            elif args.what == "merge":
                _emit(f.merge_pr(args.number, args.method))
            elif args.what == "review-status":
                _emit(f.post_review_status(args.sha, args.verdict, args.lane))
            elif args.what == "claim":
                _emit(f.claim(args.number, args.lane, args.run_id))
    except ForgeDenied as e:
        print(json.dumps({"ok": False, "error": "denied", "detail": str(e)}), file=sys.stderr)
        return 1
    except (ForgeError, FileNotFoundError, laneconfig.YamlError, OSError) as e:
        print(json.dumps({"ok": False, "error": "failure", "detail": str(e)}), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
