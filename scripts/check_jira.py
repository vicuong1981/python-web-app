"""Check that a pull request is linked to a real Jira work item.

Looks for a key such as KAN-12 in the PR title, branch name or description,
then (when Jira credentials are set) asks Jira whether each key exists.

Environment:
  PR_TITLE, PR_BRANCH, PR_BODY   pull request details (set by the workflow)
  JIRA_PROJECTS                  comma-separated project keys, e.g. "KAN,SAM1"
  JIRA_BASE_URL                  e.g. https://vicuong.atlassian.net
  JIRA_EMAIL, JIRA_API_TOKEN     optional; without them only the key format is checked

Exit code 0 = linked, 1 = not linked or the item doesn't exist.
"""

from __future__ import annotations

import base64
import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass


@dataclass
class Result:
    ok: bool
    lines: list[str]


def find_keys(projects: list[str], *texts: str) -> list[str]:
    """Jira keys for the given projects, in order of first appearance, without duplicates."""
    if not projects:
        return []
    pattern = re.compile(r"\b(" + "|".join(map(re.escape, projects)) + r")-(\d+)\b", re.IGNORECASE)
    keys: list[str] = []
    for text in texts:
        for project, number in pattern.findall(text or ""):
            key = f"{project.upper()}-{number}"
            if key not in keys:
                keys.append(key)
    return keys


def fetch_issue(base_url: str, email: str, token: str, key: str, opener=urllib.request.urlopen):
    """Return (status_code, data) for GET /rest/api/3/issue/{key}."""
    auth = base64.b64encode(f"{email}:{token}".encode()).decode()
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/rest/api/3/issue/{key}?fields=summary,status",
        headers={"Authorization": f"Basic {auth}", "Accept": "application/json"},
    )
    try:
        with opener(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, {}


def check(env: dict[str, str], opener=urllib.request.urlopen) -> Result:
    projects = [p.strip().upper() for p in env.get("JIRA_PROJECTS", "").split(",") if p.strip()]
    base = env.get("JIRA_BASE_URL", "").rstrip("/")
    keys = find_keys(
        projects, env.get("PR_TITLE", ""), env.get("PR_BRANCH", ""), env.get("PR_BODY", "")
    )

    if not keys:
        return Result(
            False,
            [
                f"No Jira work item found. Add a key from {', '.join(projects)} to the PR title "
                "(e.g. `KAN-12: Add login`) or the branch name (e.g. `KAN-12-add-login`).",
            ],
        )

    email, token = env.get("JIRA_EMAIL", ""), env.get("JIRA_API_TOKEN", "")
    if not (email and token and base):
        return Result(
            True,
            [
                f"Found {', '.join(keys)}. Not checked against Jira: the JIRA_EMAIL and "
                "JIRA_API_TOKEN secrets aren't set.",
            ],
        )

    ok, lines = True, []
    for key in keys:
        status, data = fetch_issue(base, email, token, key, opener)
        link = f"{base}/browse/{key}"
        if status == 200:
            fields = data.get("fields", {})
            state = (fields.get("status") or {}).get("name", "?")
            lines.append(f"✅ [{key}]({link}): {fields.get('summary', '')} ({state})")
        elif status == 404:
            ok = False
            lines.append(f"❌ {key} doesn't exist in Jira, or this account can't see it.")
        elif status in (401, 403):
            ok = False
            lines.append(
                f"❌ Jira refused the credentials (HTTP {status}). "
                "Check JIRA_EMAIL and JIRA_API_TOKEN."
            )
            break
        else:
            ok = False
            lines.append(f"❌ Couldn't check {key} (HTTP {status}).")
    return Result(ok, lines)


def main() -> int:
    result = check(dict(os.environ))
    for line in result.lines:
        print(line if result.ok else f"::error::{line}")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write("### Jira ticket\n\n" + "\n".join(f"- {line}" for line in result.lines) + "\n")
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
