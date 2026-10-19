"""Turning findings into a local report, issue bodies and DMCA drafts."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from . import REPO_URL, __version__
from .models import Finding

DMCA_FORM = "https://github.com/contact/dmca-takedown"
DMCA_GUIDE = "https://docs.github.com/en/site-policy/content-removal-policies/guide-to-submitting-a-dmca-takedown-notice"
KEY_MARKER = "<!-- odoo-code-radar:key={key} -->"


def title(finding: Finding) -> str:
    return f"[{finding.module.license}] {finding.module.technical_name} found in {finding.repo}"


OPL_QUOTE = (
    'OPL-1 lets buyers use and modify the software, but says they "may not publish, distribute, '
    'sublicense, and/or sell copies of the Software or modified copies of the Software."'
)


def _license_note(findings: list[Finding]) -> str:
    licenses = sorted({f.module.license for f in findings})
    if all(f.module.proprietary for f in findings):
        names = ", ".join(licenses)
        note = f"They are sold under the {names} license, which does not allow buyers to publish them."
        return note + (f" {OPL_QUOTE}" if licenses == ["OPL-1"] else "")
    return f"They are licensed under {', '.join(licenses)}. [EXPLAIN WHY THESE COPIES STILL INFRINGE]"


def dmca_draft(findings: list[Finding]) -> str:
    """One notice for one or more leaks, in the order of GitHub's takedown form."""
    modules = {f.module.technical_name: f.module for f in findings}
    works = "\n".join(
        f"- {m.display_name} (technical name {m.technical_name}): "
        f"{m.url or '[LINK TO THE MODULE ON APPS.ODOO.COM]'}"
        for m in modules.values()
    )
    whole = [f.repo_url for f in findings if f.whole_repo]
    folders = [link for f in findings for link in f.folder_links()]
    fork_repos = sorted({fork for f in findings for fork in f.forks})
    fork_folders = [
        link
        for f in findings
        for fork, branch in sorted(f.forks.items())
        for link in f.folder_links(fork, branch)
    ]
    fork_whole = sorted({fork for f in findings if f.whole_repo for fork in f.forks})
    users = sorted({f.repo.split("/")[0] for f in findings} | {fork.split("/")[0] for fork in fork_repos})

    sections = [
        "I have read and understand GitHub's Guide to Filing a DMCA Notice.",
        "**Copyrighted work**\n"
        "I am the copyright owner (or authorized to act for the owner) of these Odoo modules, sold on the "
        f"official Odoo Apps Store:\n{works}\n\n{_license_note(findings)}",
    ]
    if whole:
        sections.append("**Entire repositories** (each contains only the copied module)\n" + "\n".join(whole))
    if folders or fork_folders:
        sections.append(
            "**Specific files** (all files inside each folder infringe; the rest of each repository is "
            "not affected)\n" + "\n".join(folders + fork_folders)
        )
    if fork_repos:
        partial = " The forks of entire repositories above infringe entirely." if fork_whole else ""
        sections.append(
            "**Forks** (repository URLs only, one per line, as the form asks; each one was checked and "
            "still contains the copied module)\n"
            + "\n".join(f"https://github.com/{f}" for f in fork_repos)
            + f"\n\nIn each fork, only the copied module folder listed above infringes.{partial}"
        )
    else:
        sections.append("**Forks**\nNo forks contain the copied module.")
    if all(f.module.proprietary for f in findings):
        sections.append("**Open source license?**\nNo. The modules are under a proprietary license.")
    sections += [
        "**How to fix it**\nRemove the listed folders (and the entire repositories listed above), "
        "including in the forks.",
        "**Alleged infringers (GitHub users)**\n" + ", ".join(users),
        "**Contact information**\nName: [YOUR FULL LEGAL NAME]\nCompany: [COMPANY]\n"
        "Address: [STREET, CITY, POSTCODE, COUNTRY]\nEmail: [EMAIL]\nPhone: [PHONE WITH COUNTRY CODE]",
        "**Statements**\nI have a good faith belief that use of the copyrighted materials described above "
        "on the infringing web pages is not authorized by the copyright owner, or its agent, or the law. "
        "I have taken fair use into consideration.\n\n"
        "I swear, under penalty of perjury, that the information in this notification is accurate and "
        "that I am the copyright owner, or am authorized to act on behalf of the owner, of an exclusive "
        "right that is allegedly infringed.\n\nSignature: [YOUR FULL LEGAL NAME]",
    ]
    return "\n\n".join(sections) + "\n"


def finding_markdown(finding: Finding, heading: str = "###") -> str:
    module = finding.module
    files = "\n".join(f"- [{folder}]({url})" for folder, url in sorted(finding.files.items()))
    reasons = "\n".join(f"- {reason}" for reason in finding.reasons)
    versions = ", ".join(sorted(finding.odoo_versions)) or "unknown"
    icon = "🔴" if finding.priority == "high" else "🟡"
    forks = (
        f"{finding.fork_count} ({len(finding.forks)} still contain the module)" if finding.fork_count else "0"
    )
    return f"""{heading} {icon} {module.display_name} → [{finding.repo}]({finding.repo_url})

| | |
|---|---|
| Module | `{module.technical_name}` ({module.license}{", " + module.price if module.price else ""}) |
| Repository | {finding.repo_url} |
| Odoo versions found | {versions} |
| Scope | {"whole repository" if finding.whole_repo else "only the module folder"} |
| Forks | {forks} |
| Priority | {finding.priority} |
| Confidence | {finding.confidence} ({finding.score} points) |

**Why it matched**
{reasons}

**Module folders**
{files}
"""


def issue_body(finding: Finding) -> str:
    action = (
        f"1. Check the module folders above.\n"
        f"2. Optionally ask the repository owner to remove them; many leaks are accidental.\n"
        f"3. Otherwise file a takedown at {DMCA_FORM} using the draft below "
        f"([GitHub's guide]({DMCA_GUIDE})).\n"
        f"4. Close this issue once it is handled. odoo-code-radar will not report this repository "
        f"for this module again."
    )
    return f"""{finding_markdown(finding, heading="##")}
**What to do**
{action}

<details><summary>DMCA notice draft (fill in the parts in brackets)</summary>

{dmca_draft([finding])}
</details>

---
<sub>Reported by [odoo-code-radar]({REPO_URL}) {__version__}</sub>
{KEY_MARKER.format(key=finding.key)}
"""


def write_report(new: list[Finding], known: list[Finding], report_dir: Path) -> tuple[Path, Path]:
    report_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y-%m-%d-%H%M%S")
    base, n = f"odoo-code-radar-{stamp}", 1
    while (report_dir / f"{base}.md").exists():  # two runs in the same second
        n += 1
        base = f"odoo-code-radar-{stamp}-{n}"
    md_path = report_dir / f"{base}.md"
    json_path = report_dir / f"{base}.json"

    sections = [f"# odoo-code-radar report, {now:%Y-%m-%d %H:%M} UTC", ""]
    sections.append(f"**{len(new)} new** and {len(known)} already reported.\n")
    if new:
        sections.append("## New\n")
        for finding in new:
            sections.append(finding_markdown(finding))
        sections.append(
            "## DMCA notice draft for all new leaks\n\n"
            f"Check every link before filing, fill in the brackets, then paste it into {DMCA_FORM} "
            "or email it to copyright@github.com.\n"
        )
        sections.append(dmca_draft(new))
    if known:
        sections.append("## Already reported\n")
        sections.extend(f"- {title(f)} ({f.confidence})" for f in known)
    md_path.write_text("\n".join(sections) + "\n", encoding="utf-8")

    json_path.write_text(
        json.dumps(
            {
                "generated_at": now.isoformat(),
                "version": __version__,
                "new": [f.to_dict() for f in new],
                "known": [f.to_dict() for f in known],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return md_path, json_path
