import pytest

from odoo_code_radar import github
from odoo_code_radar.github import GitHub, GitHubError, find_token, ref_from_item


class FakeResponse:
    def __init__(self, status=200, payload=None, headers=None, text=""):
        self.status_code = status
        self._payload = payload
        self.headers = headers or {}
        self.text = text
        self.content = b"x" if payload is not None else b""

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.headers = {}
        self.calls = []

    def request(self, method, url, timeout=None, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)


def test_token_is_never_sent_to_other_hosts():
    gh = GitHub("secret", session=FakeSession([]))
    with pytest.raises(GitHubError, match="Refusing to send the GitHub token"):
        gh._request("GET", "https://evil.example/steal")


def test_repr_hides_the_token():
    assert "secret" not in repr(GitHub("secret", session=FakeSession([])))


def test_rate_limit_waits_and_retries():
    waits = []
    session = FakeSession(
        [
            FakeResponse(403, {"message": "rate limit"}, {"Retry-After": "7"}, "API rate limit exceeded"),
            FakeResponse(200, {"items": [{"path": "a"}], "total_count": 1}),
        ]
    )
    gh = GitHub("t", session=session, sleep=waits.append)
    assert gh.search_code("q") == [{"path": "a"}]
    assert 7.0 in waits


def test_permission_errors_are_not_retried():
    session = FakeSession([FakeResponse(403, {"message": "Resource not accessible"}, text="forbidden")])
    with pytest.raises(GitHubError, match="Resource not accessible"):
        GitHub("t", session=session, sleep=lambda _: None).repo("a/b")


def test_search_paginates_up_to_the_limit():
    page = [{"path": str(i)} for i in range(100)]
    session = FakeSession(
        [
            FakeResponse(200, {"items": page, "total_count": 250}),
            FakeResponse(200, {"items": page, "total_count": 250}),
        ]
    )
    items = GitHub("t", session=session, sleep=lambda _: None).search_code("q", max_results=150)
    assert len(items) == 150
    assert [c[2]["params"]["page"] for c in session.calls] == [1, 2]


def test_ref_from_item():
    assert ref_from_item({"url": "https://api.github.com/repos/a/b/contents/x?ref=deadbeef"}) == "deadbeef"
    assert ref_from_item({}) == "HEAD"


def test_find_token_prefers_environment(monkeypatch):
    for var in github.TOKEN_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("GITHUB_TOKEN", "from-env")
    assert find_token() == "from-env"
    monkeypatch.setenv("ODOO_CODE_RADAR_TOKEN", "radar")
    assert find_token() == "radar"
