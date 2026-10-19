import json

import pytest

from odoo_code_radar.config import ConfigError, from_dict, render
from odoo_code_radar.models import Finding, Module
from odoo_code_radar.report import dmca_draft, issue_body, title, write_report
from odoo_code_radar.state import IssueReporter, LocalState


def make_finding(repo="leaker/addons", license_="OPL-1"):
    module = Module(
        "om_paid",
        names={"Odoo 17 Paid App"},
        license=license_,
        url="https://apps.odoo.com/apps/modules/17.0/om_paid",
    )
    return Finding(
        module=module,
        repo=repo,
        score=110,
        reasons=["folder matches"],
        files={"om_paid": f"https://github.com/{repo}/tree/abc/om_paid"},
        forks=["a/fork"],
        fork_count=2,
    )


def test_dmca_draft_names_the_work_the_copy_and_forks():
    draft = dmca_draft(make_finding())
    assert "https://apps.odoo.com/apps/modules/17.0/om_paid" in draft
    assert "https://github.com/leaker/addons/tree/abc/om_paid" in draft
    assert "https://github.com/a/fork" in draft
    assert "1 more forks" in draft
    assert "OPL-1 license, which does not allow" in draft
    assert "penalty of perjury" in draft
    assert "I have read and understand GitHub's Guide" in draft
    assert "GitHub user: https://github.com/leaker" in draft


def test_dmca_draft_flags_open_licenses_for_a_human_to_explain():
    assert "[EXPLAIN WHY" in dmca_draft(make_finding(license_="LGPL-3"))


def test_issue_body_carries_the_key():
    finding = make_finding()
    assert title(finding) == "[OPL-1] om_paid found in leaker/addons"
    assert "<!-- odoo-code-radar:key=leaker/addons:om_paid -->" in issue_body(finding)


def test_local_state_round_trip(tmp_path):
    path = tmp_path / "state" / "reported.json"
    state = LocalState(path)
    finding = make_finding()
    assert not state.is_known(finding)
    state.add(finding)
    state.save()
    assert LocalState(path).is_known(finding)


def test_write_report(tmp_path):
    md, js = write_report([make_finding()], [make_finding("old/repo")], tmp_path)
    assert "1 new" in md.read_text()
    assert json.loads(js.read_text())["known"][0]["repo"] == "old/repo"


class FakeIssues:
    def __init__(self, existing):
        self.existing = existing
        self.created = []
        self.labels = []

    def issues(self, repo, label):
        return iter(self.existing)

    def ensure_label(self, repo, name, color, description):
        self.labels.append(name)

    def create_issue(self, repo, title, body, labels):
        self.created.append((repo, title, labels))
        return "https://github.com/me/private/issues/1"


def test_issue_reporter_remembers_closed_issues_and_opens_new_ones():
    gh = FakeIssues([{"body": "<!-- odoo-code-radar:key=old/repo:om_paid -->", "state": "closed"}])
    reporter = IssueReporter(gh, "me/private")
    assert reporter.is_known(make_finding("old/repo"))
    new = make_finding()
    assert not reporter.is_known(new)
    assert reporter.report(new) == "https://github.com/me/private/issues/1"
    assert reporter.is_known(new)
    repo, _, labels = gh.created[0]
    assert repo == "me/private"
    assert labels == ["odoo-code-radar", "leak:high", "confidence:high"]


def test_config_from_dict_and_issue_target():
    cfg = from_dict(
        {
            "author": "Odoo Mates",
            "sources": [{"repo": "me/paid", "branches": [17.0, "18.0"]}, {"path": "~/addons"}],
            "include_lgpl": True,
        }
    )
    assert cfg.repos[0].branches == ["17.0", "18.0"]
    assert cfg.paths == ["~/addons"]
    assert cfg.target_issues_repo == "me/paid"
    cfg.issues = False
    assert cfg.target_issues_repo == ""
    assert from_dict({"author": "x"}).target_issues_repo == ""


@pytest.mark.parametrize("key", ["token", "GITHUB_TOKEN", "password"])
def test_config_refuses_secrets(key):
    with pytest.raises(ConfigError, match="Tokens never go in files"):
        from_dict({"author": "x", key: "ghp_secret"})


def test_rendered_config_loads_back():
    import yaml

    cfg = from_dict({"author": "Odoo: Mates", "sources": [{"repo": "me/paid", "branches": ["17.0"]}]})
    again = from_dict(yaml.safe_load(render(cfg)))
    assert again.author == "Odoo: Mates"
    assert again.repos[0].repo == "me/paid"
    assert again.repos[0].branches == ["17.0"]
