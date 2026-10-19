"""Where the list of watched modules comes from: the Odoo Apps store, a GitHub repo, or a local folder."""

from __future__ import annotations

import html
import os
import re
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import requests

from .github import GitHub
from .manifest import (
    DEFAULT_LICENSE,
    MANIFEST_FILES,
    normalize_website,
    odoo_version,
    parse_manifest,
    split_authors,
)
from .models import Module

STORE = "https://apps.odoo.com"
STORE_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; odoo-code-radar)"}
MAX_STORE_PAGES = 50

Progress = Callable[[str], None]


def _quiet(_: str) -> None:
    pass


# -- Odoo Apps store -------------------------------------------------------------------


@dataclass
class StoreCard:
    version: str
    technical_name: str
    name: str
    price: str


_CARD_LINK = re.compile(r'href="/apps/modules/(\d+\.\d+)/([A-Za-z0-9_]+)"')
_CARD_NAME = re.compile(r'<h5 title="([^"]*)"')
_CARD_PRICE = re.compile(r"loempia_panel_price[^>]*>\s*<b>([^<]*)</b>", re.S)
_PAGE_NAME = re.compile(r'<h1[^>]*itemprop="name"[^>]*>\s*<b>([^<]+)</b>')
_PAGE_AUTHOR = re.compile(r'itemprop="author"[^>]*>\s*<span itemprop="name">([^<]+)</span>')
_PAGE_LICENSE = re.compile(r"<b>License</b></td>\s*<td>([^<]+)</td>")
_PAGE_TECHNICAL = re.compile(r"<b>Technical Name</b></td>\s*<td><code>\s*([A-Za-z0-9_]+)\s*</code>")


def parse_browse_page(page: str) -> list[StoreCard]:
    cards = []
    for chunk in page.split("loempia_app_card")[1:]:
        link = _CARD_LINK.search(chunk)
        if not link:
            continue
        name = _CARD_NAME.search(chunk)
        price = _CARD_PRICE.search(chunk)
        cards.append(
            StoreCard(
                version=link.group(1),
                technical_name=link.group(2),
                name=html.unescape(name.group(1)).strip() if name else "",
                price=html.unescape(price.group(1)).strip() if price else "",
            )
        )
    return cards


def parse_module_page(page: str) -> dict[str, Any]:
    name = _PAGE_NAME.search(page)
    license_ = _PAGE_LICENSE.search(page)
    technical = _PAGE_TECHNICAL.search(page)
    tech = technical.group(1) if technical else ""
    versions = set(re.findall(r"/apps/modules/(\d+\.\d+)/" + re.escape(tech) + r'"', page)) if tech else set()
    return {
        "name": html.unescape(name.group(1)).strip() if name else "",
        "authors": {html.unescape(a).strip() for a in _PAGE_AUTHOR.findall(page)},
        "license": license_.group(1).strip() if license_ else "",
        "technical_name": tech,
        "versions": versions,
    }


def modules_from_store(
    author: str,
    session: requests.Session | None = None,
    progress: Progress = _quiet,
    sleep: Callable[[float], None] = time.sleep,
) -> list[Module]:
    """Every module the store lists for this author, with its license read from the module page."""
    session = session or requests.Session()

    def get(url: str) -> str:
        response = session.get(url, headers=STORE_HEADERS, timeout=30)
        response.raise_for_status()
        sleep(0.3)  # be polite to the store
        return response.text

    cards: dict[str, StoreCard] = {}
    for page_no in range(1, MAX_STORE_PAGES + 1):
        path = "/apps/modules/browse" if page_no == 1 else f"/apps/modules/browse/page/{page_no}"
        page = get(f"{STORE}{path}?author={quote_plus(author)}")
        found = parse_browse_page(page)
        for card in found:
            cards.setdefault(card.technical_name, card)
        progress(f"store page {page_no}: {len(cards)} modules so far")
        if not found or f"/browse/page/{page_no + 1}?" not in page:
            break

    wanted = author.casefold()
    modules = []
    for card in cards.values():
        url = f"{STORE}/apps/modules/{card.version}/{card.technical_name}"
        info = parse_module_page(get(url))
        progress(f"read {card.technical_name}")
        # The store's author filter is fuzzy, so keep only modules this author is really on.
        if wanted not in {a.casefold() for a in info["authors"]}:
            continue
        modules.append(
            Module(
                technical_name=card.technical_name,
                names={n for n in (card.name, info["name"]) if n},
                license=info["license"] or DEFAULT_LICENSE,
                authors=info["authors"],
                versions=info["versions"] | {card.version},
                price=card.price,
                url=url,
            )
        )
    return modules


# -- manifests (GitHub repo or local folder) -------------------------------------------


def module_from_manifest(technical_name: str, manifest: dict[str, Any], url: str = "") -> Module:
    name = manifest.get("name")
    website = manifest.get("website")
    version = odoo_version(manifest.get("version"))
    license_ = manifest.get("license")
    return Module(
        technical_name=technical_name,
        names={name.strip()} if isinstance(name, str) and name.strip() else set(),
        license=license_ if isinstance(license_, str) and license_ else DEFAULT_LICENSE,
        authors=split_authors(manifest.get("author")),
        websites={normalize_website(website)} if isinstance(website, str) and website.strip() else set(),
        versions={version} if version else set(),
        url=url,
    )


def manifest_paths(paths: Iterable[str]) -> list[tuple[str, str]]:
    """(technical name, manifest path) for every module folder in a list of file paths."""
    result = []
    for path in paths:
        parts = path.split("/")
        if len(parts) >= 2 and parts[-1] in MANIFEST_FILES:
            result.append((parts[-2], path))
    return result


def modules_from_repo(
    gh: GitHub, repo: str, branches: list[str] | None = None, progress: Progress = _quiet
) -> list[Module]:
    """Every module in every branch of a (usually private) repo. Only manifests are read."""
    found: dict[str, Module] = {}
    for branch in branches or gh.branches(repo):
        entries = manifest_paths(gh.tree(repo, branch))
        progress(f"{repo}@{branch}: {len(entries)} modules")
        for technical_name, path in entries:
            text = gh.raw(repo, branch, path)
            if text is None:
                continue
            folder = path.rsplit("/", 1)[0]
            module = module_from_manifest(
                technical_name, parse_manifest(text), f"https://github.com/{repo}/tree/{branch}/{folder}"
            )
            if not module.versions and odoo_version(branch):
                module.versions.add(odoo_version(branch))
            _add(found, module)
    return list(found.values())


def modules_from_path(root: str | Path, max_depth: int = 4) -> list[Module]:
    """Every module under a local addons folder."""
    root = Path(root).expanduser()
    found: dict[str, Module] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        depth = len(Path(dirpath).relative_to(root).parts)
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and depth < max_depth]
        manifest = next((f for f in MANIFEST_FILES if f in filenames), None)
        if not manifest:
            continue
        text = (Path(dirpath) / manifest).read_text(encoding="utf-8", errors="replace")
        _add(found, module_from_manifest(Path(dirpath).name, parse_manifest(text), str(dirpath)))
        dirnames[:] = []  # a module's own subfolders hold no further modules
    return list(found.values())


def merge_modules(*groups: Iterable[Module]) -> list[Module]:
    found: dict[str, Module] = {}
    for group in groups:
        for module in group:
            _add(found, module)
    return sorted(found.values(), key=lambda m: m.technical_name)


def _add(found: dict[str, Module], module: Module) -> None:
    if module.technical_name in found:
        found[module.technical_name].merge(module)
    else:
        found[module.technical_name] = module
