"""The `odoo-code-radar` command."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests
import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from . import __version__, notify, templates, tokens
from . import config as config_mod
from . import schedule as schedule_mod
from .config import Config, ConfigError, RepoSource
from .ghsetup import GhCli, SetupError, check_private
from .github import GitHub, GitHubError, find_token
from .models import Finding, Module
from .report import title, write_report
from .scanner import Scanner, ScanOptions, guess_vendor_author
from .sources import merge_modules, modules_from_path, modules_from_repo, modules_from_store
from .state import IssueReporter, LocalState

app = typer.Typer(
    help="Protect your paid Odoo apps and intellectual property: find copies in public GitHub repositories.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()
err = Console(stderr=True)

STORE_CACHE_HOURS = 24
ISSUES_TOKEN_VAR = "ODOO_CODE_RADAR_ISSUES_TOKEN"
TOKEN_NOTE = (
    "Your token stays on this machine: it is used only by this program and sent only to GitHub. "
    "It is saved only if you schedule scans, to a file only you can read. "
    "The authors of odoo-code-radar run no server and never see it."
)


def _version(value: bool) -> None:
    if value:
        console.print(f"odoo-code-radar {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False, "--version", callback=_version, is_eager=True, help="Show the version."
    ),
) -> None:
    pass


# -- shared helpers ------------------------------------------------------------------


def _fail(message: str) -> typer.Exit:
    err.print(f"[red]✗[/red] {message}")
    return typer.Exit(1)


def _build_config(
    config_path: Optional[Path],
    author: Optional[str],
    repos: Optional[list[str]],
    branches: Optional[list[str]],
    paths: Optional[list[str]],
    include_lgpl: Optional[bool],
    min_confidence: Optional[str] = None,
    issues: Optional[bool] = None,
    issues_repo: Optional[str] = None,
    report_dir: Optional[Path] = None,
) -> Config:
    try:
        cfg = config_mod.load(config_path)
    except ConfigError as exc:
        raise _fail(str(exc)) from exc
    if author:
        cfg.author = author
    if repos:
        cfg.repos = [RepoSource(r, list(branches or [])) for r in repos]
    if paths:
        cfg.paths = list(paths)
    if include_lgpl is not None:
        cfg.include_lgpl = include_lgpl
    if min_confidence:
        cfg.min_confidence = min_confidence
    if issues is not None:
        cfg.issues = issues
    if issues_repo:
        cfg.issues_repo = issues_repo
    if report_dir:
        cfg.report_dir = str(report_dir)
    try:
        cfg.validate()
    except ConfigError as exc:
        raise _fail(str(exc)) from exc
    return cfg


def _github(token_var: str | None = None) -> GitHub:
    token = os.environ.get(token_var) if token_var else None
    try:
        token = token or find_token()
    except tokens.TokenFileError as exc:
        raise _fail(str(exc)) from exc
    if not token:
        raise _fail(
            "A GitHub token is needed, because GitHub only allows code search when logged in.\n"
            "  Set GITHUB_TOKEN (or ODOO_CODE_RADAR_TOKEN), log in with `gh auth login`,\n"
            "  or save one for scheduled scans with `odoo-code-radar schedule weekly`.\n"
            "  A fine-grained token with no extra permissions is enough for --author;\n"
            "  for --repo give it read access to Contents and read/write access to Issues on that repo.\n"
            f"  {TOKEN_NOTE}"
        )
    return GitHub(token)


def _require_private(gh: GitHub, repo: str) -> None:
    """Issues list where your apps leaked, so they only ever go to a private repo."""
    try:
        info = gh.repo(repo)
    except GitHubError as exc:
        raise _fail(f"Cannot open {repo} for issues: {exc}") from exc
    if not info.get("private"):
        raise _fail(
            f"{repo} is public, so its issues would show everyone where your apps leaked.\n"
            "  Make it private, set issues_repo to a private repo, or use --no-issues."
        )


def _store_modules(cfg: Config, refresh: bool, progress: Callable[[str], None]) -> list[Module]:
    cache = Path(cfg.state_dir) / f"store-{cfg.author.casefold().replace(' ', '_')}.json"
    if not refresh and cache.exists() and time.time() - cache.stat().st_mtime < STORE_CACHE_HOURS * 3600:
        try:
            return [Module.from_dict(m) for m in json.loads(cache.read_text(encoding="utf-8"))]
        except (OSError, ValueError, KeyError):
            pass
    modules = modules_from_store(cfg.author, progress=progress)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps([m.to_dict() for m in modules], indent=2), encoding="utf-8")
    return modules


def _collect(cfg: Config, gh: GitHub | None, refresh: bool) -> list[Module]:
    groups: list[list[Module]] = []
    with console.status("Collecting your modules…") as status:

        def progress(message: str) -> None:
            status.update(f"Collecting your modules… {escape(message)}")

        try:
            if cfg.author:
                groups.append(_store_modules(cfg, refresh, progress))
            for source in cfg.repos:
                assert gh is not None
                groups.append(modules_from_repo(gh, source.repo, source.branches or None, progress))
            for path in cfg.paths:
                if not Path(path).expanduser().is_dir():
                    raise _fail(f"{path} is not a folder")
                groups.append(modules_from_path(path))
        except requests.RequestException as exc:
            raise _fail(f"Could not read the Odoo Apps store: {exc}") from exc
        except GitHubError as exc:
            raise _fail(str(exc)) from exc
    excluded = set(cfg.exclude_modules)
    return [m for m in merge_modules(*groups) if m.technical_name not in excluded]


def _watched(cfg: Config, modules: list[Module]) -> list[Module]:
    return [m for m in modules if m.proprietary or cfg.include_lgpl]


def _modules_table(cfg: Config, modules: list[Module]) -> Table:
    table = Table(show_lines=False, header_style="bold")
    for column in ("Technical name", "Name", "License", "Versions", "Watched"):
        table.add_column(column)
    for m in modules:
        watched = m.proprietary or cfg.include_lgpl
        table.add_row(
            m.technical_name,
            escape(m.display_name),
            m.license,
            ", ".join(sorted(m.versions, key=lambda v: float(v))) if m.versions else "",
            "[green]yes[/green]" if watched else "[dim]no (open license)[/dim]",
        )
    return table


# -- commands ------------------------------------------------------------------------

CONFIG_OPT = typer.Option(
    None, "--config", "-c", help="Config file (default: ./odoo-code-radar.yml if present)."
)
AUTHOR_OPT = typer.Option(None, "--author", "-a", help="Your author name on apps.odoo.com.")
REPO_OPT = typer.Option(None, "--repo", "-r", help="Your module repo, owner/name. Repeatable.")
BRANCH_OPT = typer.Option(None, "--branch", "-b", help="Branches to read (default: all). Repeatable.")
PATH_OPT = typer.Option(None, "--path", "-p", help="A local addons folder. Repeatable.")
LGPL_OPT = typer.Option(
    None, "--include-lgpl/--no-lgpl", help="Also watch LGPL-3 and other open-source modules."
)
REFRESH_OPT = typer.Option(
    False, "--refresh", help="Read the Odoo Apps store again instead of the 24h cache."
)


@app.command()
def init(
    path: Path = typer.Argument(Path(config_mod.DEFAULT_CONFIG), help="Where to write the config."),
) -> None:
    """Create an odoo-code-radar.yml by answering a few questions."""
    if path.exists() and not typer.confirm(f"{path} exists. Overwrite it?", default=False):
        raise typer.Exit()
    console.print("Your modules can come from the Odoo Apps store (by author name), from your own GitHub")
    console.print("repo (more accurate, and leaks become issues there), or both.\n")
    cfg = Config()
    cfg.author = typer.prompt(
        "Author name on apps.odoo.com (empty to skip)", default="", show_default=False
    ).strip()
    repo = typer.prompt(
        "Your module repo, owner/name (empty to skip)", default="", show_default=False
    ).strip()
    if repo:
        branches = typer.prompt(
            "Branches to read, comma separated (empty for all)", default="", show_default=False
        )
        cfg.repos = [RepoSource(repo, [b.strip() for b in branches.split(",") if b.strip()])]
        cfg.ignore_owners = [repo.split("/")[0]]
    if not (cfg.author or cfg.repos):
        raise _fail("Give at least an author name or a repo.")
    cfg.include_lgpl = typer.confirm("Also watch LGPL-3 modules? (they may legally be shared)", default=False)
    owners = typer.prompt(
        "Your GitHub accounts to never report, comma separated",
        default=", ".join(cfg.ignore_owners),
        show_default=bool(cfg.ignore_owners),
    )
    cfg.ignore_owners = [o.strip() for o in owners.split(",") if o.strip()]
    path.write_text(config_mod.render(cfg), encoding="utf-8")
    console.print(
        f"\n[green]✓[/green] Saved {path}. Next: [bold]odoo-code-radar modules[/bold] to check the list,"
    )
    console.print("  then [bold]odoo-code-radar scan[/bold].")
    console.print(
        "To run it automatically: [bold]odoo-code-radar schedule weekly[/bold] (on this machine)"
        " or [bold]odoo-code-radar schedule weekly --github[/bold] (on GitHub, no server)."
    )


@app.command()
def modules(
    config_path: Optional[Path] = CONFIG_OPT,
    author: Optional[str] = AUTHOR_OPT,
    repo: Optional[list[str]] = REPO_OPT,
    branch: Optional[list[str]] = BRANCH_OPT,
    path: Optional[list[str]] = PATH_OPT,
    include_lgpl: Optional[bool] = LGPL_OPT,
    refresh: bool = REFRESH_OPT,
) -> None:
    """List the modules that would be watched, without searching GitHub."""
    cfg = _build_config(config_path, author, repo, branch, path, include_lgpl)
    gh = _github() if cfg.repos else None
    found = _collect(cfg, gh, refresh)
    console.print(_modules_table(cfg, found))
    console.print(f"{len(_watched(cfg, found))} of {len(found)} modules will be watched.")


@app.command()
def scan(
    config_path: Optional[Path] = CONFIG_OPT,
    author: Optional[str] = AUTHOR_OPT,
    repo: Optional[list[str]] = REPO_OPT,
    branch: Optional[list[str]] = BRANCH_OPT,
    path: Optional[list[str]] = PATH_OPT,
    include_lgpl: Optional[bool] = LGPL_OPT,
    min_confidence: Optional[str] = typer.Option(
        None, "--min-confidence", help="low, medium (default) or high."
    ),
    issues: Optional[bool] = typer.Option(
        None, "--issues/--no-issues", help="Open an issue for each new leak."
    ),
    issues_repo: Optional[str] = typer.Option(
        None, "--issues-repo", help="Where issues go (default: first --repo)."
    ),
    report_dir: Optional[Path] = typer.Option(None, "--report-dir", help="Where reports are written."),
    refresh: bool = REFRESH_OPT,
    notify_desktop: bool = typer.Option(
        False, "--notify", help="Desktop notification when new leaks are found (scheduled scans use it)."
    ),
) -> None:
    """Search GitHub for copies of your modules and report the new ones."""
    cfg = _build_config(
        config_path, author, repo, branch, path, include_lgpl, min_confidence, issues, issues_repo, report_dir
    )
    gh = _github()
    console.print(f"[dim]{TOKEN_NOTE}[/dim]")
    target = cfg.target_issues_repo
    issues_gh = _github(ISSUES_TOKEN_VAR) if target else None
    if issues_gh:
        _require_private(issues_gh, target)  # checked before the long search, not after
    found = _collect(cfg, gh, refresh)
    watched = _watched(cfg, found)
    skipped = len(found) - len(watched)
    console.print(
        f"Watching [bold]{len(watched)}[/bold] modules"
        + (f" ({skipped} open-license modules skipped, see --include-lgpl)" if skipped else "")
    )
    if not watched:
        raise _fail("Nothing to watch. Check the author name or repo with `odoo-code-radar modules`.")

    options = ScanOptions(
        vendor_author=cfg.author or guess_vendor_author(found),
        ignore_owners=set(cfg.ignore_owners) | {s.repo.split("/")[0] for s in cfg.repos},
        ignore_repos=set(cfg.ignore_repos) | {s.repo for s in cfg.repos},
        min_confidence=cfg.min_confidence,
    )
    minutes = max(1, round(len(watched) * 2.5 * 6.5 / 60))
    console.print(
        f"Searching GitHub. Code search allows 10 queries a minute, so this takes about {minutes} min."
    )
    with console.status("Searching…") as status:
        scanner = Scanner(gh, options, progress=lambda m: status.update(f"Searching… {escape(m)}"))
        findings = scanner.scan(watched)

    try:
        reporter = IssueReporter(issues_gh, target) if issues_gh else None
    except GitHubError as exc:
        raise _fail(f"Cannot read issues in {target}: {exc}") from exc
    local = LocalState(Path(cfg.state_dir) / "reported.json")
    is_known = reporter.is_known if reporter else local.is_known
    new = [f for f in findings if not is_known(f)]
    known = [f for f in findings if is_known(f)]
    scanner.enrich(new)

    for finding in new:
        issue_url = ""
        if reporter:
            try:
                issue_url = reporter.report(finding)
            except GitHubError as exc:
                err.print(f"[red]✗[/red] Could not open an issue for {finding.key}: {exc}")
        local.add(finding, issue_url)
    local.save()

    md_path, _ = write_report(new, known, Path(cfg.report_dir))
    _print_findings(new, known, reporter is not None)
    console.print(f"Report: {md_path}")
    last_run = {
        "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "new": len(new),
        "known": len(known),
        "report": str(md_path.resolve()),
        "issues_repo": target,
        "github_errors": len(scanner.errors),
    }
    Path(cfg.state_dir, "last-run.json").write_text(json.dumps(last_run, indent=2), encoding="utf-8")
    if notify_desktop and new:
        where = f"Issues opened in {target}." if reporter else f"See {md_path.resolve()}"
        notify.desktop("odoo-code-radar", f"{len(new)} new copy(ies) of your Odoo apps found. {where}")
    for message in scanner.errors[:10]:
        err.print(f"[yellow]![/yellow] {escape(message)}")
    if len(scanner.errors) > 10:
        err.print(f"[yellow]![/yellow] … and {len(scanner.errors) - 10} more GitHub errors")


def _print_findings(new: list[Finding], known: list[Finding], issues: bool) -> None:
    if not new:
        console.print(f"[green]✓[/green] No new leaks ({len(known)} already reported).")
        return
    table = Table(header_style="bold")
    for column in ("", "Module", "License", "Repository", "Confidence", "Forks"):
        table.add_column(column)
    for f in new:
        table.add_row(
            "🔴" if f.priority == "high" else "🟡",
            f.module.technical_name,
            f.module.license,
            f.repo_url,
            f"{f.confidence} ({f.score})",
            str(f.fork_count),
        )
    console.print(table)
    where = "Issues opened, GitHub will email you." if issues else "DMCA drafts are in the report."
    console.print(f"[bold]{len(new)} new leak(s)[/bold], {len(known)} already reported. {where}")
    for f in new:
        console.print(f"  • {escape(title(f))}")


# -- schedule ------------------------------------------------------------------------


@app.command()
def schedule(
    when: str = typer.Argument(..., help="daily, weekly or monthly; or status, or remove."),
    github: bool = typer.Option(
        False, "--github", help="Run on GitHub Actions in a private repo you created, instead of here."
    ),
    at: Optional[str] = typer.Option(
        None, "--at", help="Time of day, HH:MM (this machine's time; UTC with --github)."
    ),
    directory: Path = typer.Option(
        Path("."), "--dir", "-d", help="The folder with your odoo-code-radar.yml (default: here)."
    ),
    repo: Optional[str] = typer.Option(None, "--repo", help="With --github: the private repo, owner/name."),
) -> None:
    """Run the scan automatically: daily, weekly or monthly."""
    directory = directory.expanduser().resolve()
    if when == "status":
        _schedule_status(directory)
    elif when == "remove":
        _schedule_remove(directory)
    elif when in schedule_mod.FREQUENCIES:
        try:
            time_of_day = schedule_mod.parse_time(at) if at else None
        except schedule_mod.ScheduleError as exc:
            raise _fail(str(exc)) from exc
        cfg, config_path = _schedule_config(directory)
        if github:
            _schedule_github(directory, cfg, config_path, when, time_of_day, repo)
        else:
            _schedule_local(directory, cfg, config_path, when, time_of_day or "06:00")
    else:
        raise _fail("Use: schedule daily | weekly | monthly | status | remove")


def _schedule_config(directory: Path) -> tuple[Config, Path]:
    config_path = directory / config_mod.DEFAULT_CONFIG
    if not config_path.exists():
        raise _fail(f"No {config_mod.DEFAULT_CONFIG} in {directory}. Create one with `odoo-code-radar init`.")
    try:
        cfg = config_mod.load(config_path)
        cfg.validate()
    except ConfigError as exc:
        raise _fail(str(exc)) from exc
    return cfg, config_path


def _ask_token(purpose: str) -> str:
    """The scan token: the saved one if the user wants it, otherwise typed in hidden and checked."""
    try:
        saved = tokens.load()
    except tokens.TokenFileError as exc:
        raise _fail(str(exc)) from exc
    if saved and typer.confirm(f"Use the token saved in {tokens.token_path()}?", default=True):
        token = saved
    else:
        console.print(f"Paste your GitHub token ({purpose}). It is not shown while you type.")
        token = typer.prompt("Token", hide_input=True).strip()
        if not tokens.looks_like_token(token):
            raise _fail("That does not look like a GitHub token.")
    try:
        login = GitHub(token).user()
    except GitHubError as exc:
        raise _fail(f"GitHub did not accept the token: {exc}") from exc
    console.print(f"[green]✓[/green] Token works (GitHub user {login})")
    return token


def _check_repo_access(gh: GitHub, cfg: Config) -> None:
    for source in cfg.repos:
        try:
            gh.repo(source.repo)
        except GitHubError as exc:
            raise _fail(f"The token cannot read {source.repo}: {exc}") from exc


def _schedule_local(directory: Path, cfg: Config, config_path: Path, frequency: str, at: str) -> None:
    token = _ask_token("it is saved only on this machine, readable only by you")
    gh = GitHub(token)
    _check_repo_access(gh, cfg)

    target = cfg.target_issues_repo
    if not target and cfg.issues:
        console.print(
            "\nWhere should results go when it runs on its own?\n"
            "  1. Issues in a private GitHub repo: GitHub emails you (the token needs Issues access there)\n"
            "  2. Only files on this machine: reports/ plus a desktop notification"
        )
        if typer.prompt("Choose", default="1", show_choices=False).strip() == "1":
            target = typer.prompt("Private repo for the issues (owner/name)").strip()
            if target.count("/") != 1:
                raise _fail("Write the repo as owner/name.")
            _require_private(gh, target)
            with config_path.open("a", encoding="utf-8") as handle:
                handle.write("\n# Added by `odoo-code-radar schedule`: where new leaks become issues.\n")
                handle.write(f"issues_repo: {target}\n")
    elif target:
        _require_private(gh, target)

    saved_to = tokens.save(token)
    job = schedule_mod.Job(frequency=frequency, at=at, directory=str(directory), config=str(config_path))
    try:
        notes = schedule_mod.install(job)
    except schedule_mod.ScheduleError as exc:
        raise _fail(str(exc)) from exc

    console.print(f"[green]✓[/green] Token saved to {saved_to} (only you can read it)")
    console.print(f"[green]✓[/green] Scan scheduled {job.describe()} ({job.backend})")
    for note in notes:
        console.print(f"  {note}")
    if target:
        console.print(f"New leaks become issues in [bold]{target}[/bold], and GitHub emails you.")
    else:
        console.print(f"New leaks go to {directory / cfg.report_dir}, with a desktop notification.")
    console.print(f"Log: {job.log}")
    console.print(
        "Check it: [bold]odoo-code-radar schedule status[/bold]. Stop it: [bold]schedule remove[/bold]."
    )


def _github_cron(frequency: str, at: str | None) -> str:
    if not at:
        return templates.SCHEDULES[frequency][0]
    hour, minute = (int(part) for part in at.split(":"))
    days = {"daily": "* * *", "weekly": "* * 1", "monthly": "1 * *"}[frequency]
    return f"{minute} {hour} {days}"


def _schedule_github(
    directory: Path, cfg: Config, config_path: Path, frequency: str, at: str | None, repo: str | None
) -> None:
    if cfg.paths:
        raise _fail("GitHub cannot read local folders. Use `author` or `sources: - repo:` in the config.")
    cron = _github_cron(frequency, at)
    gh_cli = GhCli()
    if not gh_cli.available():
        _github_manual_steps(directory, cron, repo)
        return

    if not repo:
        console.print(
            "Create an empty [bold]private[/bold] repo for the scan results: https://github.com/new"
        )
        repo = typer.prompt("Repo name (owner/name)").strip()
    if repo.count("/") != 1:
        raise _fail("Write the repo as owner/name.")
    try:
        check_private(gh_cli.repo(repo), repo)
    except SetupError as exc:
        raise _fail(str(exc)) from exc
    console.print(f"[green]✓[/green] {repo} exists and is private")
    if not gh_cli.has_workflow_scope():
        raise _fail("Your GitHub CLI login cannot add workflow files yet. Run: gh auth refresh -s workflow")

    token = _ask_token(
        "stored as the encrypted RADAR_TOKEN secret in that repo; read access is enough, "
        "issues are opened with the workflow's own token"
    )
    _check_repo_access(GitHub(token), cfg)
    try:
        gh_cli.put_file(
            repo, str(templates.WORKFLOW_PATH), templates.workflow(cron), "Add odoo-code-radar scan"
        )
        gh_cli.put_file(
            repo,
            config_mod.DEFAULT_CONFIG,
            config_path.read_text(encoding="utf-8"),
            "Add odoo-code-radar settings",
        )
        console.print("[green]✓[/green] Added the workflow and your settings")
        gh_cli.set_secret(repo, token)
        console.print("[green]✓[/green] Saved the token as the RADAR_TOKEN secret")
    except SetupError as exc:
        raise _fail(str(exc)) from exc
    started = gh_cli.run_workflow(repo)
    schedule_mod.save_record(
        directory,
        {
            "backend": "github",
            "repo": repo,
            "frequency": frequency,
            "cron": cron,
            "directory": str(directory),
            "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        },
    )
    console.print(f'[green]✓[/green] Scheduled on GitHub: cron "{cron}" (UTC)')
    console.print(
        "  First scan started." if started else "  Start the first scan from the repo's Actions tab."
    )
    console.print(f"  Runs: https://github.com/{repo}/actions")
    console.print(
        f"New leaks become issues in [bold]{repo}[/bold], and GitHub emails you. Nothing runs here."
    )


def _github_manual_steps(directory: Path, cron: str, repo: str | None) -> None:
    workflow = directory / templates.WORKFLOW_PATH
    workflow.parent.mkdir(parents=True, exist_ok=True)
    workflow.write_text(templates.workflow(cron), encoding="utf-8")
    where = repo or "you/your-private-repo"
    console.print(f"[green]✓[/green] Wrote {workflow}")
    console.print(
        f"""The GitHub CLI (gh) is not installed or not logged in, so finish these steps yourself:
  1. Create an empty [bold]private[/bold] repo: https://github.com/new
  2. Push this folder to it (the workflow and {config_mod.DEFAULT_CONFIG}).
  3. Add your token as the secret RADAR_TOKEN: https://github.com/{where}/settings/secrets/actions/new
  4. Start the first scan: https://github.com/{where}/actions
Or install gh (https://cli.github.com), run `gh auth login`, and run this command again."""
    )


def _schedule_status(directory: Path) -> None:
    record = schedule_mod.load_record(directory)
    if not record:
        console.print(f"No schedule set up in {directory}. Start one with `odoo-code-radar schedule weekly`.")
        return
    if record["backend"] == "github":
        repo = record["repo"]
        console.print(f'Runs on GitHub in [bold]{repo}[/bold], cron "{record["cron"]}" (UTC)')
        last = GhCli().last_run(repo) if GhCli().available() else None
        if last:
            outcome = last.get("conclusion") or last.get("status")
            console.print(f"Last run: {last.get('createdAt')} ({outcome}) {last.get('url')}")
        console.print(f"Runs and issues: https://github.com/{repo}/actions, https://github.com/{repo}/issues")
        return
    job = schedule_mod.Job(record["frequency"], record["at"], record["directory"], record["config"])
    console.print(f"Runs {job.describe()} on this machine ({record['backend']})")
    upcoming = schedule_mod.next_run(record)
    if upcoming:
        console.print(f"Next run: {upcoming}")
    last_path = directory / ".odoo-code-radar" / "last-run.json"
    if last_path.exists():
        last = json.loads(last_path.read_text(encoding="utf-8"))
        console.print(
            f"Last scan: {last['finished_at']}, {last['new']} new, {last['known']} already reported"
            + (f", issues in {last['issues_repo']}" if last.get("issues_repo") else "")
        )
        console.print(f"Last report: {last['report']}")
    else:
        console.print("No scan has finished yet.")
    if not tokens.token_path().exists():
        console.print("[yellow]![/yellow] The saved token is missing; run `odoo-code-radar schedule` again.")
    if job.log.exists():
        tail = job.log.read_text(encoding="utf-8", errors="replace").strip().splitlines()[-5:]
        console.print(f"Log ({job.log}), last lines:")
        for line in tail:
            console.print(f"  [dim]{escape(line)}[/dim]")


def _schedule_remove(directory: Path) -> None:
    record = schedule_mod.load_record(directory)
    if not record:
        console.print(f"No schedule set up in {directory}.")
        return
    if record["backend"] == "github":
        repo = record["repo"]
        if not typer.confirm(f"Remove the workflow and the RADAR_TOKEN secret from {repo}?", default=True):
            raise typer.Exit()
        gh_cli = GhCli()
        try:
            gh_cli.delete_file(repo, str(templates.WORKFLOW_PATH), "Remove odoo-code-radar scan")
            gh_cli.delete_secret(repo)
        except SetupError as exc:
            raise _fail(str(exc)) from exc
        schedule_mod.record_path(directory).unlink(missing_ok=True)
        console.print(f"[green]✓[/green] Removed from {repo}. Existing issues stay.")
        return
    schedule_mod.remove(record)
    console.print("[green]✓[/green] Schedule removed from this machine.")
    if tokens.token_path().exists() and typer.confirm(
        "Also delete the saved token? (other schedules on this machine use it too)", default=False
    ):
        tokens.delete()
        console.print("[green]✓[/green] Saved token deleted.")


def run() -> None:
    app()
