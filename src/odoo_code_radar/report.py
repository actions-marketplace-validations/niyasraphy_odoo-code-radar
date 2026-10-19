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


def dmca_draft(finding: Finding) -> str:
    module = finding.module
    files = "\n".join(f"- {url}" for url in finding.files.values()) or f"- {finding.repo_url}"
    forks = "\n".join(f"- https://github.com/{fork}" for fork in finding.forks)
    if finding.fork_count > len(finding.forks):
        forks += f"\n- … {finding.fork_count - len(finding.forks)} more forks, see {finding.repo_url}/forks"
    original = module.url or "[LINK TO YOUR MODULE ON APPS.ODOO.COM]"
    license_note = (
        f"The module is sold under the {module.license} license, which does not allow the buyer to "
        "publish or redistribute it."
        if module.proprietary
        else f"The module is licensed under {module.license}. [EXPLAIN WHY THIS COPY STILL INFRINGES]"
    )
    owner = finding.repo.split("/")[0]
    return f"""I have read and understand GitHub's Guide to Filing a DMCA Notice.

**1. Copyrighted work**
I am the copyright owner (or authorized to act for the owner) of the Odoo module
“{module.display_name}” (technical name `{module.technical_name}`), published at:
{original}

{license_note}

**2. Infringing material**
The following folders in {finding.repo_url} are unauthorized copies of that module:
{files}

[THE WHOLE REPOSITORY INFRINGES / ONLY THE FOLDERS LISTED ABOVE INFRINGE]

**3. Forks**
{forks or "No forks at the time of this report."}
{"I have reason to believe all forks listed above infringe for the same reason." if forks else ""}

**4. How the user can fix it**
Remove the module folder(s) listed above from the repository.

**Infringer**
GitHub user: https://github.com/{owner}

**5. Contact information**
Name: [YOUR FULL LEGAL NAME]
Company: [COMPANY]
Address: [ADDRESS]
Email: [EMAIL]
Phone: [PHONE]

**6. Statements**
I have a good faith belief that use of the copyrighted materials described above on the infringing
web pages is not authorized by the copyright owner, or its agent, or the law. I have taken fair use
into consideration.

I swear, under penalty of perjury, that the information in this notification is accurate and that I
am the copyright owner, or am authorized to act on behalf of the owner, of an exclusive right that is
allegedly infringed.

Signature: [YOUR FULL LEGAL NAME]
"""


def finding_markdown(finding: Finding, heading: str = "###") -> str:
    module = finding.module
    files = "\n".join(f"- [{folder}]({url})" for folder, url in sorted(finding.files.items()))
    reasons = "\n".join(f"- {reason}" for reason in finding.reasons)
    versions = ", ".join(sorted(finding.odoo_versions)) or "unknown"
    icon = "🔴" if finding.priority == "high" else "🟡"
    return f"""{heading} {icon} {module.display_name} → [{finding.repo}]({finding.repo_url})

| | |
|---|---|
| Module | `{module.technical_name}` ({module.license}{", " + module.price if module.price else ""}) |
| Repository | {finding.repo_url} |
| Odoo versions found | {versions} |
| Forks | {finding.fork_count} |
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

{dmca_draft(finding)}
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
                f"<details><summary>DMCA notice draft</summary>\n\n{dmca_draft(finding)}\n</details>\n"
            )
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
