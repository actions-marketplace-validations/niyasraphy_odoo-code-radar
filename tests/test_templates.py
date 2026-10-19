import pytest
import yaml

from odoo_code_radar import templates
from odoo_code_radar.config import from_dict


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


def test_template_repo_matches_the_package():
    from pathlib import Path

    root = Path(__file__).parent.parent / "template"
    assert (root / ".github/workflows/odoo-code-radar.yml").read_text() == templates.workflow("weekly")
    assert from_dict(yaml.safe_load((root / "odoo-code-radar.yml").read_text()) or {}).author == ""


def test_workflow_reads_author_from_settings():
    workflow = yaml.safe_load(templates.workflow("weekly"))
    assert workflow["jobs"]["scan"]["steps"][-1]["with"]["author"] == "${{ vars.RADAR_AUTHOR }}"


def test_action_metadata_fits_the_marketplace():
    from pathlib import Path

    action = yaml.safe_load((Path(__file__).parent.parent / "action.yml").read_text())
    assert len(action["description"]) <= 125
    assert action["branding"] == {"icon": "radio", "color": "purple"}
