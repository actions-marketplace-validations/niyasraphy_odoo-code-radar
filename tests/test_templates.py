import pytest
import yaml

from odoo_code_radar import templates


@pytest.mark.parametrize(
    ("schedule", "cron"),
    [
        ("daily", "17 5 * * *"),
        ("weekly", "17 5 * * 1"),
        ("monthly", "17 5 1 * *"),
        ("0 6 * * 3", "0 6 * * 3"),
    ],
)
def test_workflow_schedules(schedule, cron):
    workflow = yaml.safe_load(templates.workflow(schedule))
    assert workflow[True]["schedule"] == [{"cron": cron}]  # YAML reads the `on:` key as True
    step = workflow["jobs"]["scan"]["steps"][-1]
    assert step["with"]["token"] == "${{ secrets.RADAR_TOKEN }}"
    assert workflow["permissions"] == {"contents": "read", "issues": "write"}


def test_bad_schedule_is_refused():
    with pytest.raises(ValueError, match="daily, weekly, monthly"):
        templates.cron_for("sometimes")
