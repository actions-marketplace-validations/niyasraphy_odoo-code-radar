"""A small GitHub REST client: only the calls odoo-code-radar needs, with rate limits handled.

The token stays in this process. It is read from the environment (or the GitHub CLI), kept in
memory, sent only to GitHub's own hosts, and never printed or written to disk.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from collections.abc import Callable, Iterator
from typing import Any
from urllib.parse import parse_qs, quote, urlparse

import requests

from . import tokens

API = "https://api.github.com"
RAW = "https://raw.githubusercontent.com"
TOKEN_HOSTS = {"api.github.com", "raw.githubusercontent.com"}

TOKEN_VARS = ("ODOO_CODE_RADAR_TOKEN", "GITHUB_TOKEN", "GH_TOKEN")

# Code search allows 10 requests a minute, repository search 30.
SEARCH_INTERVALS = {"/search/code": 6.5, "/search/repositories": 2.1}


class GitHubError(RuntimeError):
    pass


def find_token() -> str | None:
    """A token from the environment, the saved token file, or the GitHub CLI login, in that order."""
    for var in TOKEN_VARS:
        if os.environ.get(var):
            return os.environ[var]
    saved = tokens.load()
    if saved:
        return saved
    if shutil.which("gh"):
        try:
            out = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            return None
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    return None


def ref_from_item(item: dict[str, Any]) -> str:
    """The commit a code-search hit was found at, so its manifest can be fetched from raw."""
    refs = parse_qs(urlparse(item.get("url", "")).query).get("ref")
    return refs[0] if refs else "HEAD"


class GitHub:
    def __repr__(self) -> str:
        return "GitHub(token=***)"

    def __init__(
        self,
        token: str,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "odoo-code-radar",
            }
        )
        self._sleep = sleep
        self._last_search: dict[str, float] = {}

    # -- plumbing -----------------------------------------------------------------

    def _request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        if urlparse(url).hostname not in TOKEN_HOSTS:
            raise GitHubError(f"Refusing to send the GitHub token to {urlparse(url).hostname}")
        response: requests.Response | None = None
        for attempt in range(6):
            response = self.session.request(method, url, timeout=30, **kwargs)
            if response.status_code in (403, 429) and _rate_limited(response):
                self._sleep(_wait_seconds(response))
                continue
            if response.status_code >= 500 and attempt < 5:
                self._sleep(2**attempt)
                continue
            return response
        assert response is not None
        return response

    def _json(self, method: str, path: str, **kwargs: Any) -> Any:
        url = path if path.startswith("http") else API + path
        response = self._request(method, url, **kwargs)
        if response.status_code >= 400:
            try:
                message = response.json().get("message", response.text)
            except ValueError:
                message = response.text
            raise GitHubError(f"{method} {path} failed ({response.status_code}): {message}")
        return response.json() if response.content else None

    def _paginate(self, path: str, params: dict[str, Any] | None = None, limit: int = 1000) -> Iterator[Any]:
        params = {**(params or {}), "per_page": 100}
        page, seen = 1, 0
        while seen < limit:
            batch = self._json("GET", path, params={**params, "page": page})
            if not batch:
                return
            for item in batch:
                yield item
                seen += 1
                if seen >= limit:
                    return
            if len(batch) < 100:
                return
            page += 1

    def _search(self, path: str, query: str, max_results: int) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        page = 1
        while len(items) < max_results:
            wait = self._last_search.get(path, 0.0) + SEARCH_INTERVALS[path] - time.monotonic()
            if wait > 0:
                self._sleep(wait)
            self._last_search[path] = time.monotonic()
            data = self._json("GET", path, params={"q": query, "per_page": 100, "page": page})
            batch = data.get("items", [])
            items.extend(batch)
            # Search never returns more than 1000 results.
            if len(batch) < 100 or page * 100 >= min(data.get("total_count", 0), 1000):
                break
            page += 1
        return items[:max_results]

    # -- calls ----------------------------------------------------------------------

    def search_code(self, query: str, max_results: int = 200) -> list[dict[str, Any]]:
        return self._search("/search/code", query, max_results)

    def search_repos(self, query: str, max_results: int = 30) -> list[dict[str, Any]]:
        return self._search("/search/repositories", query, max_results)

    def raw(self, repo: str, ref: str, path: str) -> str | None:
        url = f"{RAW}/{repo}/{quote(ref, safe='')}/{quote(path)}"
        response = self._request("GET", url)
        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            raise GitHubError(f"Could not read {repo}/{path} ({response.status_code})")
        return response.text

    def user(self) -> str:
        """The login the token belongs to; also a cheap check that the token works."""
        return str(self._json("GET", "/user")["login"])

    def repo(self, repo: str) -> dict[str, Any]:
        result: dict[str, Any] = self._json("GET", f"/repos/{repo}")
        return result

    def branches(self, repo: str) -> list[str]:
        return [b["name"] for b in self._paginate(f"/repos/{repo}/branches")]

    def tree(self, repo: str, ref: str) -> list[str]:
        data = self._json("GET", f"/repos/{repo}/git/trees/{quote(ref, safe='')}", params={"recursive": "1"})
        return [entry["path"] for entry in data.get("tree", []) if entry.get("type") == "blob"]

    def forks(self, repo: str, limit: int = 100) -> dict[str, str]:
        """Fork name -> its default branch."""
        found = self._paginate(f"/repos/{repo}/forks", limit=limit)
        return {f["full_name"]: f.get("default_branch") or "HEAD" for f in found}

    def issues(self, repo: str, label: str) -> Iterator[dict[str, Any]]:
        return self._paginate(f"/repos/{repo}/issues", {"state": "all", "labels": label}, limit=10_000)

    def ensure_label(self, repo: str, name: str, color: str, description: str) -> None:
        response = self._request("GET", f"{API}/repos/{repo}/labels/{quote(name, safe='')}")
        if response.status_code == 404:
            self._json(
                "POST",
                f"/repos/{repo}/labels",
                json={"name": name, "color": color, "description": description},
            )

    def create_issue(self, repo: str, title: str, body: str, labels: list[str]) -> str:
        data = self._json(
            "POST", f"/repos/{repo}/issues", json={"title": title, "body": body, "labels": labels}
        )
        return str(data["html_url"])


def _rate_limited(response: requests.Response) -> bool:
    if response.status_code == 429 or "Retry-After" in response.headers:
        return True
    if response.headers.get("X-RateLimit-Remaining") == "0":
        return True
    return "rate limit" in response.text.lower()


def _wait_seconds(response: requests.Response) -> float:
    retry_after = response.headers.get("Retry-After")
    if retry_after and retry_after.isdigit():
        return max(1.0, float(retry_after))
    reset = response.headers.get("X-RateLimit-Reset")
    if reset and reset.isdigit():
        return min(3700.0, max(1.0, int(reset) - time.time() + 1))
    return 60.0
