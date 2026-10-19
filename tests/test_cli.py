from typer.testing import CliRunner

from odoo_code_radar import cli

from .test_scanner import FakeGitHub, code_item

runner = CliRunner()

LEAKED = "{'name': 'Odoo 16 Paid App', 'author': 'Me', 'license': 'OPL-1'}"


def setup_addons(tmp_path):
    module = tmp_path / "addons" / "om_paid"
    module.mkdir(parents=True)
    (module / "__manifest__.py").write_text(
        "{'name': 'Odoo 17 Paid App', 'license': 'OPL-1', 'author': 'Me'}"
    )
    free = tmp_path / "addons" / "om_free"
    free.mkdir()
    (free / "__manifest__.py").write_text("{'name': 'Free', 'license': 'LGPL-3', 'author': 'Me'}")


def fake_github(monkeypatch):
    gh = FakeGitHub(
        code={"path:om_paid": [code_item("leaker/addons", "om_paid/__manifest__.py")]},
        files={("leaker/addons", "om_paid/__manifest__.py"): LEAKED},
    )
    monkeypatch.setattr(cli, "_github", lambda token_var=None: gh)
    return gh


def test_scan_reports_once_and_remembers(tmp_path, monkeypatch):
    setup_addons(tmp_path)
    gh = fake_github(monkeypatch)
    monkeypatch.chdir(tmp_path)

    first = runner.invoke(cli.app, ["scan", "--path", "addons"])
    assert first.exit_code == 0, first.output
    assert "Watching 1 modules (1 open-license modules skipped" in first.output
    assert "1 new unauthorized copy," in first.output
    assert "run no server and never see it" in first.output
    assert not any("om_free" in q for q in gh.queries)

    second = runner.invoke(cli.app, ["scan", "--path", "addons"])
    assert second.exit_code == 0, second.output
    assert "No new unauthorized copies (1 already reported)" in second.output
    assert len(list((tmp_path / "reports").glob("*.md"))) == 2


def test_include_lgpl_watches_open_modules(tmp_path, monkeypatch):
    setup_addons(tmp_path)
    gh = fake_github(monkeypatch)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(cli.app, ["scan", "--path", "addons", "--include-lgpl"])
    assert result.exit_code == 0, result.output
    assert any("om_free" in q for q in gh.queries)


def test_scan_without_sources_explains(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(cli.app, ["scan"])
    assert result.exit_code == 1
    assert "--author, --repo or --path" in result.output


def test_config_with_token_is_refused(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "odoo-code-radar.yml").write_text("author: Me\ntoken: ghp_x\n")
    result = runner.invoke(cli.app, ["modules"])
    assert result.exit_code == 1
    assert "Tokens never go in files" in result.output


def test_modules_lists_watch_status(tmp_path, monkeypatch):
    setup_addons(tmp_path)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(cli.app, ["modules", "--path", "addons"])
    assert result.exit_code == 0, result.output
    assert "1 of 2 modules will be watched" in result.output


def test_scan_refuses_to_open_issues_in_a_public_repo(tmp_path, monkeypatch):
    setup_addons(tmp_path)
    gh = fake_github(monkeypatch)
    gh.repo = lambda repo: {"private": False}
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(cli.app, ["scan", "--path", "addons", "--issues-repo", "me/odooapps"])
    assert result.exit_code == 1
    assert "is public" in result.output
    assert gh.queries == []  # refused before searching
