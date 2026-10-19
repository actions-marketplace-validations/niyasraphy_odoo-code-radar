"""Remembering what was already reported, so each leak is reported once.

Locally that is a JSON file. With a repo, the issues themselves are the memory: every issue carries
a hidden key, and closed issues count too, so closing one means "handled".
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .github import GitHub
from .models import Finding
from .report import issue_body, title

LABEL = "odoo-code-radar"
PRIORITY_LABELS = {"high": ("leak:high", "d73a4a"), "low": ("leak:low", "fbca04")}
_KEY = re.compile(r"<!-- odoo-code-radar:key=(\S+) -->")


class LocalState:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.reported: dict[str, Any] = {}
        if path.exists():
            try:
                self.reported = json.loads(path.read_text(encoding="utf-8")).get("reported", {})
            except (OSError, ValueError):
                self.reported = {}

    def is_known(self, finding: Finding) -> bool:
        return finding.key in self.reported

    def add(self, finding: Finding, issue_url: str = "") -> None:
        self.reported[finding.key] = {
            "first_seen": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "score": finding.score,
            "issue": issue_url,
        }

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"reported": self.reported}, indent=2), encoding="utf-8")


class IssueReporter:
    def __init__(self, gh: GitHub, repo: str) -> None:
        self.gh = gh
        self.repo = repo
        self.known: set[str] = set()
        for issue in gh.issues(repo, LABEL):
            match = _KEY.search(issue.get("body") or "")
            if match:
                self.known.add(match.group(1))
        self._labels_ready = False

    def is_known(self, finding: Finding) -> bool:
        return finding.key in self.known

    def report(self, finding: Finding) -> str:
        if not self._labels_ready:
            self.gh.ensure_label(self.repo, LABEL, "5319e7", "Found by odoo-code-radar")
            for name, color in PRIORITY_LABELS.values():
                self.gh.ensure_label(self.repo, name, color, "Leak priority from odoo-code-radar")
            self._labels_ready = True
        labels = [LABEL, PRIORITY_LABELS[finding.priority][0], f"confidence:{finding.confidence}"]
        url = self.gh.create_issue(self.repo, title(finding), issue_body(finding), labels)
        self.known.add(finding.key)
        return url
