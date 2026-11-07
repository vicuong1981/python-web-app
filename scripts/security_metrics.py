"""Collect Bandit and SonarQube Cloud results, then share them.

1. Writes a summary to the GitHub Actions job page.
2. On pull requests, adds or updates one "Security scan" comment. Its first
   line is a hidden marker gitStream reads (see .cm/gitstream.cm), e.g.
   <!-- security-summary bandit_high=0 bandit_medium=0 bandit_low=0 sonar_gate=OK -->
3. Reports each number to LinearB's External Custom Metrics API.

Every part is optional: missing tokens or reports are skipped with a note,
and the script always exits 0 so reporting never blocks a merge (Bandit's own
job does the blocking).

Environment (all optional):
  BANDIT_REPORT        path to `bandit -f json` output
  SONAR_TOKEN, SONAR_PROJECT_KEY, SONAR_HOST (default https://sonarcloud.io)
  LINEARB_API_TOKEN    LinearB API token (x-api-key)
  GITHUB_TOKEN, GITHUB_REPOSITORY, PR_NUMBER, PR_URL, COMMIT_SHA, BRANCH
  GITHUB_SERVER_URL, GITHUB_STEP_SUMMARY
"""

from __future__ import annotations

import base64
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime

MARKER = "<!-- security-summary"
LINEARB_URL = "https://public-api.linearb.io/api/v1/report/metric"
SEVERITIES = ("high", "medium", "low")

# Overall values on a branch; "new code" values on a pull request.
SONAR_BRANCH_KEYS = ["bugs", "vulnerabilities", "security_hotspots", "code_smells", "coverage"]
SONAR_PR_KEYS = [f"new_{k}" for k in SONAR_BRANCH_KEYS]


# ---------------------------------------------------------------- inputs


def load_bandit(path: str | None) -> dict | None:
    """Issue counts by severity from a Bandit JSON report, or None if there's no report."""
    if not path or not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        results = json.load(f).get("results", [])
    counts = {s: 0 for s in SEVERITIES}
    for issue in results:
        severity = str(issue.get("issue_severity", "")).lower()
        if severity in counts:
            counts[severity] += 1
    counts["total"] = sum(counts[s] for s in SEVERITIES)
    return counts


def _get_json(url: str, headers: dict, opener) -> dict:
    with opener(urllib.request.Request(url, headers=headers), timeout=20) as resp:
        return json.loads(resp.read() or b"{}")


def sonar_status(env: dict, opener=urllib.request.urlopen) -> dict | None:
    """Quality gate and key measures from SonarQube Cloud, or None if not configured."""
    token, key = env.get("SONAR_TOKEN"), env.get("SONAR_PROJECT_KEY")
    if not (token and key):
        return None
    host = env.get("SONAR_HOST", "https://sonarcloud.io").rstrip("/")
    auth = {"Authorization": "Basic " + base64.b64encode(f"{token}:".encode()).decode()}
    pr = env.get("PR_NUMBER")
    scope = {"pullRequest": pr} if pr else {"branch": env.get("BRANCH") or "main"}
    keys = SONAR_PR_KEYS if pr else SONAR_BRANCH_KEYS
    try:
        gate = _get_json(
            f"{host}/api/qualitygates/project_status?"
            + urllib.parse.urlencode({"projectKey": key, **scope}),
            auth,
            opener,
        )
        measures = _get_json(
            f"{host}/api/measures/component?"
            + urllib.parse.urlencode({"component": key, "metricKeys": ",".join(keys), **scope}),
            auth,
            opener,
        )
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        return {"error": str(e)}

    values: dict[str, float] = {}
    for m in measures.get("component", {}).get("measures", []):
        raw = m.get("value")
        if raw is None:  # "new_*" measures come back under period(s)
            raw = (m.get("period") or (m.get("periods") or [{}])[0]).get("value")
        if raw is not None:
            values[m["metric"].removeprefix("new_")] = float(raw)
    return {
        "gate": gate.get("projectStatus", {}).get("status", "NONE"),
        "scope": "new code" if pr else "overall",
        "url": f"{host}/dashboard?id={urllib.parse.quote(key)}"
        + (f"&pullRequest={pr}" if pr else ""),
        **values,
    }


# ---------------------------------------------------------------- outputs


def marker_line(bandit: dict | None, sonar: dict | None) -> str:
    parts = []
    if bandit:
        parts += [f"bandit_{s}={bandit[s]}" for s in SEVERITIES]
    if sonar and "gate" in sonar:
        parts.append(f"sonar_gate={sonar['gate']}")
        parts += [f"sonar_{k}={int(sonar[k])}" for k in ("bugs", "vulnerabilities") if k in sonar]
    return f"{MARKER} {' '.join(parts)} -->"


def render_comment(bandit: dict | None, sonar: dict | None) -> str:
    rows = []
    if bandit is None:
        rows.append("| Bandit | Not run |")
    else:
        icon = "❌" if bandit["high"] or bandit["medium"] else "✅"
        rows.append(
            f"| Bandit | {icon} {bandit['high']} high · {bandit['medium']} medium · "
            f"{bandit['low']} low |"
        )
    if sonar is None:
        rows.append("| SonarQube Cloud | Not set up (add the `SONAR_TOKEN` secret) |")
    elif "error" in sonar:
        rows.append("| SonarQube Cloud | Couldn't read results |")
    else:
        icon = {"OK": "✅", "ERROR": "❌"}.get(sonar["gate"], "➖")
        bits = [
            f"{int(sonar[k])} {k.replace('_', ' ')}" for k in SONAR_BRANCH_KEYS[:4] if k in sonar
        ]
        if "coverage" in sonar:
            bits.append(f"{sonar['coverage']:.0f}% coverage")
        rows.append(
            f"| SonarQube Cloud | {icon} Quality gate {sonar['gate']} · {sonar['scope']}: "
            f"{' · '.join(bits) or 'no measures yet'} · [details]({sonar['url']}) |"
        )
    return "\n".join(
        [
            marker_line(bandit, sonar),
            "### 🔒 Security scan",
            "",
            "| Check | Result |",
            "|---|---|",
            *rows,
            "",
            "<sub>Updated on every push. gitStream reads the first line of this comment;"
            " the numbers are also reported to LinearB as custom metrics.</sub>",
        ]
    )


def linearb_payloads(bandit: dict | None, sonar: dict | None, env: dict, now=None) -> list[dict]:
    """One LinearB custom-metric report per number."""
    ts = (now or datetime.now(UTC)).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    repo_url = (
        f"{env.get('GITHUB_SERVER_URL', 'https://github.com')}/{env.get('GITHUB_REPOSITORY', '')}"
    )
    entity = {"repo_url": repo_url}
    if env.get("PR_URL"):
        entity["pr_url"] = env["PR_URL"]
    if env.get("COMMIT_SHA"):
        entity["commit_sha"] = env["COMMIT_SHA"]
    tags = {
        "branch": env.get("BRANCH", ""),
        "event": "pull_request" if env.get("PR_NUMBER") else "push",
    }

    def metric(name: str, value: float, source: str) -> dict:
        return {
            "metric_name": name,
            "value": value,
            "timestamp": ts,
            "source": source,
            "entity": entity,
            "tags": tags,
        }

    out = []
    if bandit:
        out += [metric(f"security_bandit_{s}", bandit[s], "bandit") for s in (*SEVERITIES, "total")]
    if sonar and "gate" in sonar:
        prefix = "security_sonar_new_" if env.get("PR_NUMBER") else "security_sonar_"
        out.append(
            metric(f"{prefix}quality_gate_passed", 1 if sonar["gate"] == "OK" else 0, "sonarqube")
        )
        out += [
            metric(f"{prefix}{k}", sonar[k], "sonarqube") for k in SONAR_BRANCH_KEYS if k in sonar
        ]
    return out


def post_linearb(payloads: list[dict], api_key: str, opener=urllib.request.urlopen) -> list[str]:
    results = []
    for p in payloads:
        req = urllib.request.Request(
            LINEARB_URL,
            data=json.dumps(p).encode(),
            headers={"Content-Type": "application/json", "x-api-key": api_key},
            method="POST",
        )
        try:
            with opener(req, timeout=20) as resp:
                results.append(f"{p['metric_name']}={p['value']}: HTTP {resp.status}")
        except urllib.error.HTTPError as e:
            results.append(f"{p['metric_name']}: HTTP {e.code}")
        except (urllib.error.URLError, TimeoutError) as e:
            results.append(f"{p['metric_name']}: failed ({e})")
    return results


def upsert_pr_comment(env: dict, body: str, opener=urllib.request.urlopen) -> str:
    """Create the summary comment, or update the one this script made before."""
    repo, pr, token = env["GITHUB_REPOSITORY"], env["PR_NUMBER"], env["GITHUB_TOKEN"]
    api = env.get("GITHUB_API_URL", "https://api.github.com")
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
    }
    comments = _get_json(f"{api}/repos/{repo}/issues/{pr}/comments?per_page=100", headers, opener)
    existing = next((c for c in comments if str(c.get("body", "")).startswith(MARKER)), None)
    if existing:
        url, method = f"{api}/repos/{repo}/issues/comments/{existing['id']}", "PATCH"
    else:
        url, method = f"{api}/repos/{repo}/issues/{pr}/comments", "POST"
    req = urllib.request.Request(
        url, data=json.dumps({"body": body}).encode(), headers=headers, method=method
    )
    with opener(req, timeout=20) as resp:
        return f"{'Updated' if existing else 'Added'} PR comment (HTTP {resp.status})"


# ---------------------------------------------------------------- main


def main(env: dict | None = None, opener=urllib.request.urlopen) -> int:
    env = dict(os.environ) if env is None else env
    bandit = load_bandit(env.get("BANDIT_REPORT"))
    sonar = sonar_status(env, opener)
    body = render_comment(bandit, sonar)
    log = [body.split("\n", 1)[0]]

    if env.get("PR_NUMBER") and env.get("GITHUB_TOKEN"):
        try:
            log.append(upsert_pr_comment(env, body, opener))
        except (urllib.error.URLError, TimeoutError) as e:
            log.append(f"Couldn't update the PR comment: {e}")

    if env.get("LINEARB_API_TOKEN"):
        payloads = linearb_payloads(bandit, sonar, env)
        log.append(f"LinearB custom metrics ({len(payloads)}):")
        log += ["  " + r for r in post_linearb(payloads, env["LINEARB_API_TOKEN"], opener)]
    else:
        log.append("::notice::LINEARB_API_TOKEN not set - skipping LinearB custom metrics.")

    print("\n".join(log))
    if env.get("GITHUB_STEP_SUMMARY"):
        with open(env["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(body.split("\n", 1)[1] + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
