"""Setting up the scheduled scan on GitHub Actions in a private repo the user created.

The one-time setup (adding the workflow, storing the secret) goes through the user's GitHub CLI login,
so the scan token itself can stay read-only.
"""

from __future__ import annotations

import base64
import json
import shutil
import subprocess
import time
from collections.abc import Callable, Sequence
from typing import Any

from .templates import WORKFLOW_PATH

SECRET_NAME = "RADAR_TOKEN"
WORKFLOW_FILE = WORKFLOW_PATH.name

Runner = Callable[..., "subprocess.CompletedProcess[str]"]


class SetupError(RuntimeError):
    pass


def run(cmd: Sequence[str], input: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(cmd), input=input, capture_output=True, text=True, timeout=120)


class GhCli:
    def __init__(self, runner: Runner = run, sleep: Callable[[float], None] = time.sleep) -> None:
        self.runner = runner
        self.sleep = sleep

    def available(self) -> bool:
        return shutil.which("gh") is not None and self.runner(["gh", "auth", "status"]).returncode == 0

    def has_workflow_scope(self) -> bool:
        out = self.runner(["gh", "auth", "status"])
        text = out.stdout + out.stderr
        # Older logins list their scopes; writing workflow files needs "workflow".
        return "Token scopes" not in text or "workflow" in text

    def _api(self, args: list[str], input: str | None = None) -> Any:
        out = self.runner(["gh", "api", *args], input=input)
        if out.returncode != 0:
            raise SetupError((out.stderr or out.stdout).strip())
        return json.loads(out.stdout) if out.stdout.strip() else None

    def repo(self, repo: str) -> dict[str, Any]:
        try:
            data: dict[str, Any] = self._api([f"repos/{repo}"])
        except SetupError as exc:
            raise SetupError(f"Cannot open {repo}: {exc}") from exc
        return data

    def _sha(self, repo: str, path: str) -> str | None:
        try:
            return str(self._api([f"repos/{repo}/contents/{path}"])["sha"])
        except SetupError:
            return None

    def put_file(self, repo: str, path: str, content: str, message: str) -> None:
        body: dict[str, Any] = {"message": message, "content": base64.b64encode(content.encode()).decode()}
        sha = self._sha(repo, path)
        if sha:
            body["sha"] = sha
        try:
            self._api(["-X", "PUT", f"repos/{repo}/contents/{path}", "--input", "-"], input=json.dumps(body))
        except SetupError as exc:
            if "workflow" in str(exc).lower() and path.startswith(".github/"):
                raise SetupError(
                    "Your GitHub CLI login may not write workflow files. Run: gh auth refresh -s workflow"
                ) from exc
            raise

    def delete_file(self, repo: str, path: str, message: str) -> bool:
        sha = self._sha(repo, path)
        if not sha:
            return False
        body = json.dumps({"message": message, "sha": sha})
        self._api(["-X", "DELETE", f"repos/{repo}/contents/{path}", "--input", "-"], input=body)
        return True

    def set_secret(self, repo: str, value: str) -> None:
        # The value goes in through stdin, so it never appears in a process list or shell history.
        out = self.runner(["gh", "secret", "set", SECRET_NAME, "--repo", repo], input=value)
        if out.returncode != 0:
            raise SetupError(f"Could not save the secret: {out.stderr.strip()}")

    def delete_secret(self, repo: str) -> None:
        self.runner(["gh", "secret", "delete", SECRET_NAME, "--repo", repo])

    def run_workflow(self, repo: str, attempts: int = 6) -> bool:
        # GitHub needs a few seconds to notice a new workflow file.
        for _ in range(attempts):
            if self.runner(["gh", "workflow", "run", WORKFLOW_FILE, "--repo", repo]).returncode == 0:
                return True
            self.sleep(5)
        return False

    def last_run(self, repo: str) -> dict[str, Any] | None:
        out = self.runner(
            [
                "gh", "run", "list", "--workflow", WORKFLOW_FILE, "--repo", repo, "-L", "1",
                "--json", "status,conclusion,createdAt,url",
            ]
        )  # fmt: skip
        if out.returncode != 0 or not out.stdout.strip():
            return None
        runs: list[dict[str, Any]] = json.loads(out.stdout)
        return runs[0] if runs else None


def check_private(info: dict[str, Any], repo: str) -> None:
    if not info.get("private"):
        raise SetupError(
            f"{repo} is public. Its issues would show everyone where copies of your apps are. "
            "Make it private (Settings → General → Danger Zone → Change visibility) or use another repo."
        )
