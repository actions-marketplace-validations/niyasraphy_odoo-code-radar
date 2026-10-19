"""Searching GitHub for copies of the watched modules and deciding which hits are real."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

from .github import GitHub, GitHubError, ref_from_item
from .manifest import (
    MANIFEST_FILES,
    normalize_name,
    normalize_website,
    odoo_version,
    parse_manifest,
    search_phrase,
)
from .models import CONFIDENCE_LEVELS, ROOT_FOLDER, Finding, Module

Progress = Callable[[str], None]

# Points for each kind of evidence; 80+ is high confidence, 50+ medium.
FOLDER_POINTS = 40
NAME_POINTS = 40
AUTHOR_POINTS = 30
WEBSITE_POINTS = 10

MIN_PHRASE_LENGTH = 12  # shorter names are too common to search for without an author


def _quiet(_: str) -> None:
    pass


@dataclass
class ScanOptions:
    vendor_author: str = ""
    ignore_owners: set[str] = field(default_factory=set)
    ignore_repos: set[str] = field(default_factory=set)
    min_confidence: str = "medium"
    max_results_per_query: int = 200


def guess_vendor_author(modules: Iterable[Module]) -> str:
    """The author shared by most modules, e.g. the vendor in 'Vendor, Odoo SA'."""
    counts = Counter(a for m in modules for a in m.authors if "odoo s" not in a.casefold())
    return counts.most_common(1)[0][0] if counts else ""


def queries_for(module: Module, vendor_author: str) -> list[tuple[str, str]]:
    """(endpoint, query) pairs that find a module renamed or not, in a subfolder or at a repo root."""
    queries = [("code", f"filename:__manifest__.py path:{module.technical_name}")]
    for phrase in sorted({search_phrase(n) for n in module.names} - {""}):
        if vendor_author:
            queries.append(("code", f'"{vendor_author}" "{phrase}" filename:__manifest__.py'))
        elif len(phrase) >= MIN_PHRASE_LENGTH:
            queries.append(("code", f'"{phrase}" filename:__manifest__.py'))
    queries.append(("repo", f"{module.technical_name} in:name"))
    return queries


def folder_matches(folder: str, technical_name: str) -> bool:
    """'om_hr_payroll', 'om-hr-payroll' and 'om_hr_payroll-17.0' all count as the module's folder."""
    folder = folder.lower().replace("-", "_")
    folder = re.sub(r"_?v?\d+(?:\.\d+)?$", "", folder)
    return folder == technical_name.lower()


def score(module: Module, folder: str, manifest: dict[str, Any], vendor_author: str) -> tuple[int, list[str]]:
    points, reasons = 0, []
    if folder_matches(folder, module.technical_name):
        points += FOLDER_POINTS
        reasons.append(f"folder `{folder}` matches the technical name")
    name = manifest.get("name")
    if isinstance(name, str) and normalize_name(name) in module.normalized_names:
        points += NAME_POINTS
        reasons.append(f"manifest name “{name}” matches")
    author = manifest.get("author")
    if isinstance(author, str) and vendor_author and vendor_author.casefold() in author.casefold():
        points += AUTHOR_POINTS
        reasons.append(f"manifest author “{author}” matches")
    website = manifest.get("website")
    if isinstance(website, str) and module.websites and normalize_website(website) in module.websites:
        points += WEBSITE_POINTS
        reasons.append(f"manifest website {website} matches")
    return points, reasons


def module_location(repo: str, ref: str, manifest_path: str) -> tuple[str, str]:
    """(folder, link) for the module folder holding a manifest; what a takedown should point at."""
    if "/" not in manifest_path:
        return ROOT_FOLDER, f"https://github.com/{repo}"
    folder = manifest_path.rsplit("/", 1)[0]
    return folder, f"https://github.com/{repo}/tree/{quote(ref, safe='')}/{quote(folder)}"


class Scanner:
    def __init__(self, gh: GitHub, options: ScanOptions, progress: Progress = _quiet) -> None:
        self.gh = gh
        self.options = options
        self.progress = progress
        self._manifests: dict[tuple[str, str], dict[str, Any]] = {}
        self.errors: list[str] = []

    def scan(self, modules: list[Module]) -> list[Finding]:
        findings: dict[str, Finding] = {}
        for index, module in enumerate(modules, 1):
            self.progress(f"[{index}/{len(modules)}] {module.technical_name}")
            for finding in self.scan_module(module):
                known = findings.get(finding.key)
                if known is None:
                    findings[finding.key] = finding
                    continue
                known.files.update(finding.files)
                known.odoo_versions |= finding.odoo_versions
                if finding.score > known.score:
                    known.score, known.reasons = finding.score, finding.reasons
        minimum = CONFIDENCE_LEVELS[self.options.min_confidence]
        kept = [f for f in findings.values() if f.score >= minimum]
        return sorted(kept, key=lambda f: (f.priority != "high", -f.score, f.repo))

    def scan_module(self, module: Module) -> list[Finding]:
        findings: dict[str, Finding] = {}
        for endpoint, query in queries_for(module, self.options.vendor_author):
            try:
                if endpoint == "code":
                    hits = [
                        self._code_hit(item)
                        for item in self.gh.search_code(query, self.options.max_results_per_query)
                    ]
                else:
                    hits = [self._repo_hit(item) for item in self.gh.search_repos(query)]
            except GitHubError as exc:
                self.errors.append(f"{module.technical_name}: {exc}")
                continue
            for hit in hits:
                if hit is None or self._ignored(hit["repo"]):
                    continue
                self._consider(module, hit, findings)
        return list(findings.values())

    def _ignored(self, repo: str) -> bool:
        owner = repo.split("/")[0].casefold()
        ignored_owners = {o.casefold() for o in self.options.ignore_owners}
        ignored_repos = {r.casefold() for r in self.options.ignore_repos}
        return owner in ignored_owners or repo.casefold() in ignored_repos

    def _code_hit(self, item: dict[str, Any]) -> dict[str, str] | None:
        path = item.get("path", "")
        if path.rsplit("/", 1)[-1] not in MANIFEST_FILES:
            return None
        repo = item["repository"]["full_name"]
        folder = path.rsplit("/", 2)[-2] if "/" in path else repo.split("/")[1]
        return {
            "repo": repo,
            "path": path,
            "ref": ref_from_item(item),
            "folder": folder,
        }

    def _repo_hit(self, item: dict[str, Any]) -> dict[str, str] | None:
        """A repo named after the module; only counts when the module sits at its root."""
        repo = item["full_name"]
        ref = item.get("default_branch") or "HEAD"
        for name in MANIFEST_FILES:
            if self._manifest(repo, ref, name):
                return {
                    "repo": repo,
                    "path": name,
                    "ref": ref,
                    "folder": repo.split("/")[1],
                }
        return None

    def _manifest(self, repo: str, ref: str, path: str) -> dict[str, Any]:
        key = (repo, f"{ref}:{path}")
        if key not in self._manifests:
            try:
                text = self.gh.raw(repo, ref, path)
            except GitHubError as exc:
                self.errors.append(str(exc))
                text = None
            self._manifests[key] = parse_manifest(text) if text else {}
        return self._manifests[key]

    def _consider(self, module: Module, hit: dict[str, str], findings: dict[str, Finding]) -> None:
        manifest = self._manifest(hit["repo"], hit["ref"], hit["path"])
        if not manifest:
            return
        name = manifest.get("name")
        same_module = folder_matches(hit["folder"], module.technical_name) or (
            isinstance(name, str) and normalize_name(name) in module.normalized_names
        )
        if not same_module:
            return  # e.g. another module by the same author that the name search also returned
        points, reasons = score(module, hit["folder"], manifest, self.options.vendor_author)
        version = odoo_version(manifest.get("version"))
        finding = findings.get(hit["repo"])
        if finding is None:
            finding = findings[hit["repo"]] = Finding(
                module=module, repo=hit["repo"], score=points, reasons=reasons
            )
        elif points > finding.score:
            finding.score, finding.reasons = points, reasons
        finding.files.update([module_location(hit["repo"], hit["ref"], hit["path"])])
        if version:
            finding.odoo_versions.add(version)

    def enrich(self, findings: Iterable[Finding], limit: int = 100) -> None:
        """Add the default branch and the forks that still hold the module.

        Forks often differ from their parent, and a takedown may only name forks that really infringe.
        """
        for finding in findings:
            try:
                info = self.gh.repo(finding.repo)
                finding.default_branch = str(info.get("default_branch") or "HEAD")
                finding.fork_count = int(info.get("forks_count") or 0)
                forks = self.gh.forks(finding.repo, limit=limit) if finding.fork_count else {}
            except GitHubError as exc:
                self.errors.append(str(exc))
                continue
            finding.forks = {
                fork: branch
                for fork, branch in forks.items()
                if self._has_module(fork, branch, finding.folders)
            }

    def _has_module(self, repo: str, branch: str, folders: list[str]) -> bool:
        for folder in folders:
            for name in MANIFEST_FILES:
                path = f"{folder}/{name}" if folder else name
                try:
                    if self.gh.raw(repo, branch, path) is not None:
                        return True
                except GitHubError:
                    continue
        return False
