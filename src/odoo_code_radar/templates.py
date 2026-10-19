"""The GitHub Actions workflow that ships with the package; `schedule --github` puts it in a repo."""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path

SCHEDULES = {
    "daily": ("17 5 * * *", "every day at 05:17 UTC"),
    "weekly": ("17 5 * * 1", "every Monday at 05:17 UTC"),
    "monthly": ("17 5 1 * *", "on the 1st of every month at 05:17 UTC"),
}
WORKFLOW_PATH = Path(".github/workflows/odoo-code-radar.yml")


def read(name: str) -> str:
    return (files("odoo_code_radar") / "templates" / name).read_text(encoding="utf-8")


def cron_for(schedule: str) -> tuple[str, str]:
    """'weekly' -> its cron line and a description; a five-field cron line is used as given."""
    if schedule in SCHEDULES:
        return SCHEDULES[schedule]
    if len(schedule.split()) == 5:
        return schedule, "custom schedule, in UTC"
    raise ValueError(f"Use daily, weekly, monthly or a cron line like '0 6 * * 1', not {schedule!r}")


def workflow(schedule: str = "daily") -> str:
    cron, when = cron_for(schedule)
    return read("workflow.yml").replace("__CRON__", cron).replace("__WHEN__", when)
