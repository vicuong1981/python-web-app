"""The Jira ticket check used by .github/workflows/jira-check.yml."""

import io
import json
import urllib.error

from scripts.check_jira import check, find_keys

BASE = {"JIRA_PROJECTS": "KAN,SAM1", "JIRA_BASE_URL": "https://vicuong.atlassian.net"}
CREDS = {"JIRA_EMAIL": "me@example.com", "JIRA_API_TOKEN": "test-token"}


class FakeResponse(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def fake_jira(issues):
    """An opener that answers like Jira for the given {key: (summary, status)}."""
    calls = []

    def opener(req, timeout=None):
        calls.append(req)
        key = req.full_url.split("/issue/")[1].split("?")[0]
        if key not in issues:
            raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)
        summary, status = issues[key]
        body = {"fields": {"summary": summary, "status": {"name": status}}}
        return FakeResponse(json.dumps(body).encode())

    opener.calls = calls
    return opener


def test_finds_keys_in_title_branch_and_body():
    assert find_keys(["KAN", "SAM1"], "kan-12: Add login", "KAN-12-add-login", "see SAM1-3") == [
        "KAN-12",
        "SAM1-3",
    ]


def test_ignores_other_projects_and_lookalikes():
    assert find_keys(["KAN"], "Fix UTF-8 handling in ABC-5", "main", "") == []


def test_fails_without_a_key():
    result = check({**BASE, "PR_TITLE": "Add login", "PR_BRANCH": "add-login"})
    assert not result.ok
    assert "No Jira work item" in result.lines[0]


def test_key_only_when_no_credentials():
    result = check({**BASE, "PR_TITLE": "KAN-1: Add login"})
    assert result.ok
    assert "Not checked against Jira" in result.lines[0]


def test_existing_ticket_passes():
    opener = fake_jira({"KAN-1": ("Add login", "In Progress")})
    result = check({**BASE, **CREDS, "PR_BRANCH": "KAN-1-add-login"}, opener=opener)
    assert result.ok
    assert "Add login" in result.lines[0] and "In Progress" in result.lines[0]
    assert opener.calls[0].get_header("Authorization").startswith("Basic ")


def test_missing_ticket_fails():
    opener = fake_jira({})
    result = check({**BASE, **CREDS, "PR_TITLE": "KAN-999: Ghost"}, opener=opener)
    assert not result.ok
    assert "doesn't exist" in result.lines[0]


def test_bad_credentials_fail_clearly():
    def opener(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, None)

    result = check({**BASE, **CREDS, "PR_TITLE": "KAN-1: x"}, opener=opener)
    assert not result.ok
    assert "refused the credentials" in result.lines[0]
