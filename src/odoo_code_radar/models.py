"""The modules we watch and the copies we find."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .manifest import is_proprietary, normalize_name

CONFIDENCE_LEVELS = {"low": 0, "medium": 50, "high": 80}
ROOT_FOLDER = "(repository root)"


@dataclass
class Module:
    technical_name: str
    names: set[str] = field(default_factory=set)
    license: str = ""
    authors: set[str] = field(default_factory=set)
    websites: set[str] = field(default_factory=set)
    versions: set[str] = field(default_factory=set)
    price: str = ""
    url: str = ""

    @property
    def proprietary(self) -> bool:
        return is_proprietary(self.license)

    @property
    def display_name(self) -> str:
        return sorted(self.names, key=len)[0] if self.names else self.technical_name

    @property
    def normalized_names(self) -> set[str]:
        return {n for n in (normalize_name(name) for name in self.names) if n}

    def merge(self, other: Module) -> None:
        self.names |= other.names
        self.authors |= other.authors
        self.websites |= other.websites
        self.versions |= other.versions
        # A proprietary license on any version wins: that is the one worth protecting.
        if not self.license or (other.proprietary and not self.proprietary):
            self.license = other.license
        self.price = self.price or other.price
        self.url = self.url or other.url

    def to_dict(self) -> dict[str, Any]:
        return {
            "technical_name": self.technical_name,
            "names": sorted(self.names),
            "license": self.license,
            "authors": sorted(self.authors),
            "websites": sorted(self.websites),
            "versions": sorted(self.versions),
            "price": self.price,
            "url": self.url,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Module:
        return cls(
            technical_name=data["technical_name"],
            names=set(data.get("names", [])),
            license=data.get("license", ""),
            authors=set(data.get("authors", [])),
            websites=set(data.get("websites", [])),
            versions=set(data.get("versions", [])),
            price=data.get("price", ""),
            url=data.get("url", ""),
        )


@dataclass
class Finding:
    """One watched module found in one public repository."""

    module: Module
    repo: str
    score: int
    reasons: list[str]
    files: dict[str, str] = field(default_factory=dict)  # module folder -> link at the commit found
    odoo_versions: set[str] = field(default_factory=set)
    forks: dict[str, str] = field(default_factory=dict)  # fork that still has the module -> its branch
    fork_count: int = 0  # all forks, including those without the module
    default_branch: str = ""

    @property
    def key(self) -> str:
        return f"{self.repo}:{self.module.technical_name}"

    @property
    def confidence(self) -> str:
        return "high" if self.score >= 80 else "medium" if self.score >= 50 else "low"

    @property
    def priority(self) -> str:
        return "high" if self.module.proprietary else "low"

    @property
    def repo_url(self) -> str:
        return f"https://github.com/{self.repo}"

    @property
    def whole_repo(self) -> bool:
        """The module sits at the repository root, so the whole repository is the copy."""
        return ROOT_FOLDER in self.files

    @property
    def folders(self) -> list[str]:
        return sorted("" if folder == ROOT_FOLDER else folder for folder in self.files)

    def folder_links(self, repo: str = "", branch: str = "") -> list[str]:
        """Links to the module folders on the current branch: where the files must be removed."""
        repo = repo or self.repo
        branch = branch or self.default_branch or "HEAD"
        return [f"https://github.com/{repo}/tree/{branch}/{folder}" for folder in self.folders if folder]

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "repo": self.repo,
            "repo_url": self.repo_url,
            "technical_name": self.module.technical_name,
            "module_name": self.module.display_name,
            "license": self.module.license,
            "priority": self.priority,
            "confidence": self.confidence,
            "score": self.score,
            "reasons": self.reasons,
            "files": self.files,
            "odoo_versions": sorted(self.odoo_versions),
            "whole_repo": self.whole_repo,
            "default_branch": self.default_branch,
            "forks": sorted(self.forks),
            "fork_count": self.fork_count,
        }
