"""The odoo-code-radar.yml config file, with command-line options layered on top."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .models import CONFIDENCE_LEVELS

DEFAULT_CONFIG = "odoo-code-radar.yml"


class ConfigError(ValueError):
    pass


@dataclass
class RepoSource:
    repo: str
    branches: list[str] = field(default_factory=list)  # empty means every branch


@dataclass
class Config:
    author: str = ""
    repos: list[RepoSource] = field(default_factory=list)
    paths: list[str] = field(default_factory=list)
    include_lgpl: bool = False
    min_confidence: str = "medium"
    ignore_owners: list[str] = field(default_factory=list)
    ignore_repos: list[str] = field(default_factory=list)
    exclude_modules: list[str] = field(default_factory=list)
    issues: bool = True
    issues_repo: str = ""
    report_dir: str = "reports"
    state_dir: str = ".odoo-code-radar"

    @property
    def target_issues_repo(self) -> str:
        """Issues go to the configured repo, or else the first module repo. No repo, no issues."""
        if not self.issues:
            return ""
        return self.issues_repo or (self.repos[0].repo if self.repos else "")

    def validate(self) -> None:
        if not (self.author or self.repos or self.paths):
            raise ConfigError("Tell odoo-code-radar which modules to watch: --author, --repo or --path.")
        if self.min_confidence not in CONFIDENCE_LEVELS:
            raise ConfigError(f"min_confidence must be one of: {', '.join(CONFIDENCE_LEVELS)}")
        for source in self.repos:
            if source.repo.count("/") != 1:
                raise ConfigError(f"Repositories are written owner/name, got {source.repo!r}")


def load(path: Path | None) -> Config:
    """Read the config file; a missing default file just means 'use the defaults'."""
    if path is None:
        path = Path(DEFAULT_CONFIG)
        if not path.exists():
            return Config()
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except OSError as exc:
        raise ConfigError(f"Cannot read {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path} is not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path} should hold settings like 'author: Your Name'")
    return from_dict(data)


SECRET_KEYS = {"token", "github_token", "gh_token", "password", "secret"}


def from_dict(data: dict[str, Any]) -> Config:
    secrets = SECRET_KEYS & {str(k).casefold() for k in data}
    if secrets:
        raise ConfigError(
            f"Remove '{sorted(secrets)[0]}' from the config file. Tokens never go in files that may be "
            "committed: set GITHUB_TOKEN in your environment (or a GitHub Actions secret) instead."
        )
    config = Config()
    repos, paths = [], []
    for source in data.get("sources") or []:
        if isinstance(source, dict) and source.get("repo"):
            branches = source.get("branches") or []
            repos.append(RepoSource(str(source["repo"]), [str(b) for b in branches]))
        elif isinstance(source, dict) and source.get("path"):
            paths.append(str(source["path"]))
        else:
            raise ConfigError(f"Each source needs a 'repo' or a 'path', got {source!r}")
    config.repos, config.paths = repos, paths
    for name in ("author", "min_confidence", "issues_repo", "report_dir", "state_dir"):
        if data.get(name) is not None:
            setattr(config, name, str(data[name]))
    for name in ("include_lgpl", "issues"):
        if data.get(name) is not None:
            setattr(config, name, bool(data[name]))
    for name in ("ignore_owners", "ignore_repos", "exclude_modules"):
        if data.get(name) is not None:
            setattr(config, name, [str(v) for v in data[name]])
    return config


def render(config: Config) -> str:
    """A commented config file for `odoo-code-radar init`."""
    lines = ["# odoo-code-radar settings. Docs: https://github.com/niyasraphy/odoo-code-radar", ""]
    if config.author:
        lines += [
            "# Your author name on apps.odoo.com. Your modules are read from the store.",
            f"author: {yaml.safe_dump(config.author).strip().removesuffix('...').strip()}",
            "",
        ]
    lines.append("# Your own module repos (needs a token that can read them) or local addons folders.")
    lines.append("# New leaks become issues in the first repo (or issues_repo).")
    if config.repos or config.paths:
        lines.append("sources:")
        for source in config.repos:
            lines.append(f"  - repo: {source.repo}")
            if source.branches:
                lines.append(f"    branches: [{', '.join(repr(b) for b in source.branches)}]")
        lines += [f"  - path: {p}" for p in config.paths]
    else:
        lines += [
            "# sources:",
            "#   - repo: you/odoo-apps",
            '#     branches: ["17.0", "18.0"]',
            "#   - path: ~/addons",
        ]
    lines += [
        "",
        "# OPL-1 and other proprietary modules are always watched.",
        "# LGPL-3 and other open-source modules may legally be shared, so they are off by default.",
        f"include_lgpl: {str(config.include_lgpl).lower()}",
        "",
        "# low, medium or high",
        f"min_confidence: {config.min_confidence}",
        "",
        "# Your own GitHub accounts: never reported.",
        f"ignore_owners: [{', '.join(config.ignore_owners)}]",
        "",
        "# Specific repositories to never report (owner/name), e.g. a customer you allowed.",
        "ignore_repos: []",
        "",
        "# Technical names to skip.",
        "exclude_modules: []",
        "",
    ]
    return "\n".join(lines)
