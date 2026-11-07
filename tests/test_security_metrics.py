"""scripts/security_metrics.py: Bandit + SonarQube Cloud summary, PR comment and LinearB metrics."""

import io
import json
import re
from datetime import UTC, datetime

from scripts import security_metrics as sm


class FakeResponse(io.BytesIO):
    def __init__(self, body=b"{}", status=200):
        super().__init__(body)
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeHTTP:
    """Records requests and answers from a {url-substring: payload} map."""

    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def __call__(self, req, timeout=None):
        body = json.loads(req.data) if req.data else None
        self.calls.append((req.get_method(), req.full_url, body, dict(req.header_items())))
        for part, payload in self.routes.items():
            if part in req.full_url:
                return FakeResponse(json.dumps(payload).encode())
        return FakeResponse(b"{}")


def bandit_report(tmp_path, severities):
    path = tmp_path / "bandit-report.json"
    path.write_text(json.dumps({"results": [{"issue_severity": s} for s in severities]}))
    return str(path)


SONAR_PR = {
    "/api/qualitygates/project_status": {"projectStatus": {"status": "ERROR"}},
    "/api/measures/component": {
        "component": {
            "measures": [
                {"metric": "new_bugs", "period": {"value": "1"}},
                {"metric": "new_vulnerabilities", "periods": [{"value": "2"}]},
                {"metric": "new_coverage", "period": {"value": "81.5"}},
            ]
        }
    },
}


def test_counts_bandit_findings(tmp_path):
    counts = sm.load_bandit(bandit_report(tmp_path, ["HIGH", "LOW", "LOW", "MEDIUM"]))
    assert counts == {"high": 1, "medium": 1, "low": 2, "total": 4}


def test_missing_bandit_report_is_none():
    assert sm.load_bandit("does-not-exist.json") is None


def test_sonar_skipped_without_token():
    assert sm.sonar_status({"SONAR_PROJECT_KEY": "k"}) is None


def test_sonar_reads_new_code_on_a_pull_request():
    http = FakeHTTP(SONAR_PR)
    sonar = sm.sonar_status(
        {"SONAR_TOKEN": "t", "SONAR_PROJECT_KEY": "org_repo", "PR_NUMBER": "7"}, http
    )
    assert sonar["gate"] == "ERROR" and sonar["scope"] == "new code"
    assert sonar["bugs"] == 1 and sonar["vulnerabilities"] == 2 and sonar["coverage"] == 81.5
    assert all("pullRequest=7" in url for _, url, _, _ in http.calls)
    assert http.calls[0][3]["Authorization"].startswith("Basic ")


def test_marker_is_what_gitstream_reads():
    line = sm.marker_line(
        {"high": 0, "medium": 2, "low": 1, "total": 3},
        {"gate": "OK", "bugs": 0.0, "vulnerabilities": 0.0},
    )
    assert line == (
        "<!-- security-summary bandit_high=0 bandit_medium=2 bandit_low=1 "
        "sonar_gate=OK sonar_bugs=0 sonar_vulnerabilities=0 -->"
    )
    # Same pattern as has.security_problems in .cm/gitstream.cm
    assert re.search(
        r"(bandit_(high|medium)=[1-9]|sonar_gate=ERROR|sonar_vulnerabilities=[1-9])", line
    )


def test_clean_scan_does_not_trip_gitstream():
    line = sm.marker_line({"high": 0, "medium": 0, "low": 4, "total": 4}, None)
    assert not re.search(r"(bandit_(high|medium)=[1-9]|sonar_gate=ERROR)", line)


def test_comment_explains_missing_sonar():
    body = sm.render_comment({"high": 0, "medium": 0, "low": 0, "total": 0}, None)
    assert body.startswith(sm.MARKER)
    assert "Not set up" in body and "✅ 0 high" in body


def test_linearb_payloads_for_a_pull_request():
    env = {
        "GITHUB_REPOSITORY": "vicuong1981/python-web-app",
        "PR_NUMBER": "7",
        "PR_URL": "https://github.com/vicuong1981/python-web-app/pull/7",
        "COMMIT_SHA": "abc123",
        "BRANCH": "feature/x",
    }
    sonar = {"gate": "OK", "scope": "new code", "url": "u", "bugs": 0.0, "coverage": 90.0}
    now = datetime(2026, 11, 7, 20, 30, 0, 123000, tzinfo=UTC)
    payloads = sm.linearb_payloads({"high": 1, "medium": 0, "low": 2, "total": 3}, sonar, env, now)
    by_name = {p["metric_name"]: p for p in payloads}
    assert by_name["security_bandit_high"]["value"] == 1
    assert by_name["security_sonar_new_quality_gate_passed"]["value"] == 1
    assert by_name["security_sonar_new_coverage"]["value"] == 90.0
    first = payloads[0]
    assert first["timestamp"] == "2026-11-07 20:30:00.123"
    assert first["entity"] == {
        "repo_url": "https://github.com/vicuong1981/python-web-app",
        "pr_url": env["PR_URL"],
        "commit_sha": "abc123",
    }
    assert first["tags"] == {"branch": "feature/x", "event": "pull_request"}


def test_posts_metrics_with_api_key():
    http = FakeHTTP({})
    out = sm.post_linearb([{"metric_name": "m", "value": 1}], "secret-key", http)
    method, url, body, headers = http.calls[0]
    assert method == "POST" and url == sm.LINEARB_URL and body["metric_name"] == "m"
    assert headers["X-api-key"] == "secret-key"
    assert out == ["m=1: HTTP 200"]


def test_updates_existing_pr_comment_instead_of_adding_another():
    env = {"GITHUB_REPOSITORY": "o/r", "PR_NUMBER": "7", "GITHUB_TOKEN": "t"}
    http = FakeHTTP({"/issues/7/comments": [{"id": 99, "body": sm.MARKER + " old -->"}]})
    assert sm.upsert_pr_comment(env, "new body", http).startswith("Updated")
    method, url, body, _ = http.calls[-1]
    assert (
        method == "PATCH" and url.endswith("/issues/comments/99") and body == {"body": "new body"}
    )


def test_main_runs_everything_and_never_fails(tmp_path):
    env = {
        "BANDIT_REPORT": bandit_report(tmp_path, ["LOW"]),
        "GITHUB_REPOSITORY": "o/r",
        "PR_NUMBER": "7",
        "GITHUB_TOKEN": "t",
        "LINEARB_API_TOKEN": "k",
        "GITHUB_STEP_SUMMARY": str(tmp_path / "summary.md"),
    }
    http = FakeHTTP({"/issues/7/comments": []})
    assert sm.main(env, http) == 0
    methods = [(m, u) for m, u, _, _ in http.calls]
    assert ("POST", "https://api.github.com/repos/o/r/issues/7/comments") in methods
    assert sum(1 for m, u in methods if u == sm.LINEARB_URL) == 4  # bandit high/medium/low/total
    assert "Security scan" in (tmp_path / "summary.md").read_text()
