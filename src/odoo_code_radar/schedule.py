"""Running the scan on a schedule on this machine, with whatever scheduler the OS has.

Linux: a systemd user timer (catches up after the machine was off), or cron where systemd is missing.
macOS: a launchd agent. Windows: a Task Scheduler task. The scheduler entry holds only the command;
the token is read from the saved token file when the scan starts.
"""

from __future__ import annotations

import getpass
import hashlib
import json
import plistlib
import shlex
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

FREQUENCIES = ("daily", "weekly", "monthly")
CRON_MARKER = "# odoo-code-radar:"


class ScheduleError(RuntimeError):
    pass


Runner = Callable[..., "subprocess.CompletedProcess[str]"]


def run(cmd: Sequence[str], input: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(cmd), input=input, capture_output=True, text=True, timeout=60)


@dataclass
class Job:
    frequency: str
    at: str  # HH:MM, local time
    directory: str
    config: str
    backend: str = ""
    created: str = ""

    @property
    def name(self) -> str:
        digest = hashlib.sha1(self.directory.encode()).hexdigest()[:8]
        return f"odoo-code-radar-{digest}"

    @property
    def state_dir(self) -> Path:
        return Path(self.directory) / ".odoo-code-radar"

    @property
    def log(self) -> Path:
        return self.state_dir / "schedule.log"

    @property
    def hour(self) -> int:
        return int(self.at.split(":")[0])

    @property
    def minute(self) -> int:
        return int(self.at.split(":")[1])

    def command(self) -> list[str]:
        return [sys.executable, "-m", "odoo_code_radar", "scan", "--config", self.config, "--notify"]

    def describe(self) -> str:
        when = {"daily": "every day", "weekly": "every Monday", "monthly": "on the 1st of every month"}
        return f"{when[self.frequency]} at {self.at}"


def parse_time(value: str) -> str:
    try:
        parsed = datetime.strptime(value.strip(), "%H:%M")
    except ValueError as exc:
        raise ScheduleError(f"Use a 24-hour time like 06:00, not {value!r}") from exc
    return parsed.strftime("%H:%M")


def detect_backend(runner: Runner = run) -> str:
    if sys.platform == "darwin":
        return "launchd"
    if sys.platform == "win32":
        return "schtasks"
    if shutil.which("systemctl") and runner(["systemctl", "--user", "show-environment"]).returncode == 0:
        return "systemd"
    if shutil.which("crontab"):
        return "cron"
    raise ScheduleError("No scheduler found on this machine (looked for systemd and cron).")


# -- the record of what was installed -----------------------------------------------------


def record_path(directory: Path) -> Path:
    return directory / ".odoo-code-radar" / "schedule.json"


def load_record(directory: Path) -> dict[str, str] | None:
    path = record_path(directory)
    if not path.exists():
        return None
    try:
        data: dict[str, str] = json.loads(path.read_text(encoding="utf-8"))
        return data
    except (OSError, ValueError):
        return None


def save_record(directory: Path, data: dict[str, str]) -> None:
    path = record_path(directory)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


# -- install / remove ------------------------------------------------------------------------


def install(job: Job, runner: Runner = run, home: Path | None = None) -> list[str]:
    """Install the job; returns notes worth showing the user."""
    home = home or Path.home()
    job.state_dir.mkdir(parents=True, exist_ok=True)
    job.backend = job.backend or detect_backend(runner)
    job.created = datetime.now(timezone.utc).isoformat(timespec="seconds")
    notes = {"systemd": _install_systemd, "cron": _install_cron, "launchd": _install_launchd}.get(
        job.backend, _install_schtasks
    )(job, runner, home)
    save_record(Path(job.directory), {**asdict(job), "name": job.name})
    return notes


def remove(record: dict[str, str], runner: Runner = run, home: Path | None = None) -> None:
    home = home or Path.home()
    name, backend = record["name"], record["backend"]
    if backend == "systemd":
        runner(["systemctl", "--user", "disable", "--now", f"{name}.timer"])
        for suffix in ("service", "timer"):
            (_systemd_dir(home) / f"{name}.{suffix}").unlink(missing_ok=True)
        runner(["systemctl", "--user", "daemon-reload"])
    elif backend == "cron":
        lines = [line for line in _crontab(runner) if not line.endswith(CRON_MARKER + name)]
        _write_crontab(lines, runner)
    elif backend == "launchd":
        plist = _launchd_path(home, name)
        runner(["launchctl", "unload", "-w", str(plist)])
        plist.unlink(missing_ok=True)
    else:
        runner(["schtasks", "/Delete", "/F", "/TN", name])
        (Path(record["directory"]) / ".odoo-code-radar" / "run-scan.cmd").unlink(missing_ok=True)
    record_path(Path(record["directory"])).unlink(missing_ok=True)


def next_run(record: dict[str, str], runner: Runner = run) -> str:
    """When the scheduler will run next, where it can tell us."""
    name, backend = record["name"], record["backend"]
    if backend == "systemd":
        out = runner(
            ["systemctl", "--user", "show", f"{name}.timer", "-p", "NextElapseUSecRealtime", "--value"]
        )
        return out.stdout.strip() if out.returncode == 0 else ""
    if backend == "schtasks":
        out = runner(["schtasks", "/Query", "/TN", name, "/FO", "LIST"])
        for line in out.stdout.splitlines():
            if line.lower().startswith("next run time"):
                return line.split(":", 1)[1].strip()
    return ""


# -- systemd ----------------------------------------------------------------------------------


def _systemd_dir(home: Path) -> Path:
    return home / ".config" / "systemd" / "user"


def _systemd_quote(arg: str) -> str:
    return '"' + arg.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%") + '"'


def systemd_units(job: Job) -> tuple[str, str]:
    calendar = {
        "daily": f"*-*-* {job.at}:00",
        "weekly": f"Mon *-*-* {job.at}:00",
        "monthly": f"*-*-01 {job.at}:00",
    }[job.frequency]
    log = str(job.log).replace("%", "%%")
    service = f"""[Unit]
Description=odoo-code-radar scan in {job.directory}

[Service]
Type=oneshot
WorkingDirectory={job.directory.replace("%", "%%")}
ExecStart={" ".join(_systemd_quote(a) for a in job.command())}
StandardOutput=append:{log}
StandardError=append:{log}
"""
    timer = f"""[Unit]
Description=Run odoo-code-radar {job.describe()}

[Timer]
OnCalendar={calendar}
Persistent=true
RandomizedDelaySec=10min

[Install]
WantedBy=timers.target
"""
    return service, timer


def _install_systemd(job: Job, runner: Runner, home: Path) -> list[str]:
    service, timer = systemd_units(job)
    unit_dir = _systemd_dir(home)
    unit_dir.mkdir(parents=True, exist_ok=True)
    (unit_dir / f"{job.name}.service").write_text(service, encoding="utf-8")
    (unit_dir / f"{job.name}.timer").write_text(timer, encoding="utf-8")
    for cmd in (
        ["systemctl", "--user", "daemon-reload"],
        ["systemctl", "--user", "enable", "--now", f"{job.name}.timer"],
    ):
        out = runner(cmd)
        if out.returncode != 0:
            raise ScheduleError(f"{' '.join(cmd)} failed: {out.stderr.strip()}")
    active = runner(["systemctl", "--user", "is-active", f"{job.name}.timer"])
    if active.stdout.strip() != "active":
        raise ScheduleError(
            f"The timer did not start. See: journalctl --user -u {job.name}.timer -u {job.name}.service"
        )
    notes = ["If the machine is off at that time, the scan runs as soon as it is back on."]
    linger = runner(["loginctl", "show-user", getpass.getuser(), "-p", "Linger"])
    if "Linger=no" in linger.stdout:
        notes.append(
            "On a server, also run [bold]sudo loginctl enable-linger $USER[/bold] so scans run while you "
            "are logged out."
        )
    return notes


# -- cron -------------------------------------------------------------------------------------


def cron_line(job: Job) -> str:
    days = {"daily": "* * *", "weekly": "* * 1", "monthly": "1 * *"}[job.frequency]
    command = " ".join(shlex.quote(a) for a in job.command())
    return (
        f"{job.minute} {job.hour} {days} cd {shlex.quote(job.directory)} && {command} "
        f">> {shlex.quote(str(job.log))} 2>&1 {CRON_MARKER}{job.name}"
    )


def _crontab(runner: Runner) -> list[str]:
    out = runner(["crontab", "-l"])
    return out.stdout.splitlines() if out.returncode == 0 else []


def _write_crontab(lines: list[str], runner: Runner) -> None:
    out = runner(["crontab", "-"], input="\n".join(lines) + "\n")
    if out.returncode != 0:
        raise ScheduleError(f"Could not update the crontab: {out.stderr.strip()}")


def _install_cron(job: Job, runner: Runner, home: Path) -> list[str]:
    lines = [line for line in _crontab(runner) if not line.endswith(CRON_MARKER + job.name)]
    _write_crontab([*lines, cron_line(job)], runner)
    return ["cron skips a run if the machine is off at that time."]


# -- launchd (macOS) ------------------------------------------------------------------------


def _launchd_path(home: Path, name: str) -> Path:
    return home / "Library" / "LaunchAgents" / f"com.{name}.plist"


def launchd_plist(job: Job) -> bytes:
    interval: dict[str, int] = {"Hour": job.hour, "Minute": job.minute}
    if job.frequency == "weekly":
        interval["Weekday"] = 1
    elif job.frequency == "monthly":
        interval["Day"] = 1
    return plistlib.dumps(
        {
            "Label": f"com.{job.name}",
            "ProgramArguments": job.command(),
            "WorkingDirectory": job.directory,
            "StartCalendarInterval": interval,
            "StandardOutPath": str(job.log),
            "StandardErrorPath": str(job.log),
        }
    )


def _install_launchd(job: Job, runner: Runner, home: Path) -> list[str]:
    plist = _launchd_path(home, job.name)
    plist.parent.mkdir(parents=True, exist_ok=True)
    runner(["launchctl", "unload", "-w", str(plist)])
    plist.write_bytes(launchd_plist(job))
    out = runner(["launchctl", "load", "-w", str(plist)])
    if out.returncode != 0:
        raise ScheduleError(f"launchctl load failed: {out.stderr.strip()}")
    return ["If the Mac is asleep at that time, the scan runs when it wakes."]


# -- Task Scheduler (Windows) -----------------------------------------------------------------


def _install_schtasks(job: Job, runner: Runner, home: Path) -> list[str]:
    # A small wrapper keeps the task's command short (Task Scheduler limits it) and adds logging.
    wrapper = job.state_dir / "run-scan.cmd"
    command = " ".join(f'"{a}"' for a in job.command())
    wrapper.write_text(
        f'@echo off\r\ncd /d "{job.directory}"\r\n{command} >> "{job.log}" 2>&1\r\n', encoding="utf-8"
    )
    schedule = {
        "daily": ["/SC", "DAILY"],
        "weekly": ["/SC", "WEEKLY", "/D", "MON"],
        "monthly": ["/SC", "MONTHLY", "/D", "1"],
    }
    cmd = [
        "schtasks",
        "/Create",
        "/F",
        "/TN",
        job.name,
        *schedule[job.frequency],
        "/ST",
        job.at,
        "/TR",
        f'"{wrapper}"',
    ]
    out = runner(cmd)
    if out.returncode != 0:
        raise ScheduleError(f"schtasks failed: {out.stderr.strip() or out.stdout.strip()}")
    return ["The PC must be on at that time; Task Scheduler skips missed runs."]
