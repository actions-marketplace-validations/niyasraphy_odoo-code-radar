import json
import plistlib
import stat
import subprocess
import sys

import pytest
from typer.testing import CliRunner

from odoo_code_radar import cli, ghsetup, schedule, tokens
from odoo_code_radar.ghsetup import GhCli, SetupError, check_private

runner = CliRunner()
TOKEN = "github_pat_" + "x" * 40


class FakeRun:
    """Records commands; answers from a {first words: (code, stdout)} table."""

    def __init__(self, answers=None):
        self.answers = answers or {}
        self.calls = []

    def __call__(self, cmd, input=None):
        self.calls.append((list(cmd), input))
        for prefix, (code, out) in self.answers.items():
            if " ".join(cmd).startswith(prefix):
                return subprocess.CompletedProcess(cmd, code, out, "")
        return subprocess.CompletedProcess(cmd, 0, "", "")


@pytest.fixture(autouse=True)
def config_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    for var in ("GITHUB_TOKEN", "GH_TOKEN", "ODOO_CODE_RADAR_TOKEN"):
        monkeypatch.delenv(var, raising=False)


# -- token file ---------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_saved_token_is_private():
    path = tokens.save(TOKEN)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert tokens.load() == TOKEN


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_token_readable_by_others_is_refused():
    path = tokens.save(TOKEN)
    path.chmod(0o644)
    with pytest.raises(tokens.TokenFileError, match="chmod 600"):
        tokens.load()


def test_find_token_uses_saved_file(monkeypatch):
    from odoo_code_radar import github

    monkeypatch.setattr(github.shutil, "which", lambda _: None)
    assert github.find_token() is None
    tokens.save(TOKEN)
    assert github.find_token() == TOKEN
    assert tokens.delete() and github.find_token() is None


# -- local schedulers ---------------------------------------------------------------------------


def make_job(tmp_path, frequency="weekly"):
    folder = tmp_path / "my radar"
    folder.mkdir(exist_ok=True)
    return schedule.Job(frequency, "06:30", str(folder), str(folder / "odoo-code-radar.yml"))


def test_systemd_units(tmp_path):
    job = make_job(tmp_path)
    service, timer = schedule.systemd_units(job)
    assert "OnCalendar=Mon *-*-* 06:30:00" in timer
    assert "Persistent=true" in timer
    assert '"-m" "odoo_code_radar" "scan"' in service
    assert '"--notify"' in service
    assert f"WorkingDirectory={job.directory}\n" in service
    assert "token" not in service.lower()


def test_install_and_remove_systemd(tmp_path):
    job = make_job(tmp_path, "monthly")
    job.backend = "systemd"
    run = FakeRun({"loginctl": (0, "Linger=no\n"), "systemctl --user is-active": (0, "active\n")})
    notes = schedule.install(job, runner=run, home=tmp_path)
    units = tmp_path / ".config/systemd/user"
    assert (units / f"{job.name}.timer").read_text().count("*-*-01 06:30:00") == 1
    assert ["systemctl", "--user", "enable", "--now", f"{job.name}.timer"] in [c for c, _ in run.calls]
    assert any("enable-linger" in note for note in notes)

    record = schedule.load_record(tmp_path / "my radar")
    assert record["backend"] == "systemd" and record["name"] == job.name
    schedule.remove(record, runner=run, home=tmp_path)
    assert not (units / f"{job.name}.timer").exists()
    assert schedule.load_record(tmp_path / "my radar") is None


def test_systemd_timer_that_did_not_start_is_an_error(tmp_path):
    job = make_job(tmp_path)
    job.backend = "systemd"
    run = FakeRun({"systemctl --user is-active": (3, "inactive\n")})
    with pytest.raises(schedule.ScheduleError, match="did not start"):
        schedule.install(job, runner=run, home=tmp_path)


def test_install_cron_replaces_only_its_own_line(tmp_path):
    job = make_job(tmp_path, "daily")
    job.backend = "cron"
    existing = f"0 1 * * * backup.sh\n5 5 * * * old {schedule.CRON_MARKER}{job.name}\n"
    run = FakeRun({"crontab -l": (0, existing)})
    schedule.install(job, runner=run, home=tmp_path)
    written = next(i for c, i in run.calls if c == ["crontab", "-"])
    assert "backup.sh" in written
    assert "old" not in written
    assert written.count(schedule.CRON_MARKER) == 1
    assert written.splitlines()[-1].startswith("30 6 * * * cd ")


def test_launchd_plist(tmp_path):
    plist = plistlib.loads(schedule.launchd_plist(make_job(tmp_path)))
    assert plist["StartCalendarInterval"] == {"Hour": 6, "Minute": 30, "Weekday": 1}
    assert plist["ProgramArguments"][-1] == "--notify"


def test_parse_time():
    assert schedule.parse_time("6:05") == "06:05"
    with pytest.raises(schedule.ScheduleError):
        schedule.parse_time("25:00")


# -- GitHub setup ---------------------------------------------------------------------------------


def test_check_private():
    check_private({"private": True}, "me/radar")
    with pytest.raises(SetupError, match="is public"):
        check_private({"private": False}, "me/odooapps")


def test_gh_put_file_and_secret_go_through_stdin():
    run = FakeRun({"gh api repos/me/radar/contents/": (1, "")})
    gh = GhCli(runner=run, sleep=lambda _: None)
    run.answers = {"gh api repos/me/radar/contents/x.yml": (1, ""), "gh api -X PUT": (0, "{}")}
    gh.put_file("me/radar", "x.yml", "hello", "Add")
    put = next((c, i) for c, i in run.calls if "PUT" in c)
    assert json.loads(put[1])["content"] == "aGVsbG8="
    gh.set_secret("me/radar", TOKEN)
    secret = next((c, i) for c, i in run.calls if c[:3] == ["gh", "secret", "set"])
    assert TOKEN not in secret[0] and secret[1] == TOKEN


def test_gh_workflow_scope_detection():
    with_scope = FakeRun({"gh auth status": (0, "Token scopes: 'gist', 'repo', 'workflow'")})
    without = FakeRun({"gh auth status": (0, "Token scopes: 'gist', 'repo'")})
    assert GhCli(runner=with_scope).has_workflow_scope()
    assert not GhCli(runner=without).has_workflow_scope()


# -- the schedule command -----------------------------------------------------------------------


class FakeGitHub:
    def __init__(self, token="t", **_):
        self.private = {"me/private-apps": True, "me/radar": True, "me/public": False}

    def user(self):
        return "me"

    def repo(self, repo):
        return {"private": self.private.get(repo, True)}


def radar_dir(tmp_path, body="author: Me\n"):
    folder = tmp_path / "radar"
    folder.mkdir()
    (folder / "odoo-code-radar.yml").write_text(body)
    return folder


def test_schedule_needs_a_config(tmp_path):
    result = runner.invoke(cli.app, ["schedule", "weekly", "--dir", str(tmp_path)])
    assert result.exit_code == 1
    assert "odoo-code-radar init" in result.output


def test_schedule_local_author_mode_with_private_issue_repo(tmp_path, monkeypatch):
    folder = radar_dir(tmp_path)
    monkeypatch.setattr(cli, "GitHub", FakeGitHub)
    installed = []
    monkeypatch.setattr(cli.schedule_mod, "install", lambda job: installed.append(job) or ["note"])
    result = runner.invoke(
        cli.app, ["schedule", "weekly", "--dir", str(folder)], input=f"{TOKEN}\n1\nme/radar\n"
    )
    assert result.exit_code == 0, result.output
    assert TOKEN not in result.output
    assert "Token works (GitHub user me)" in result.output
    assert "issues in me/radar" in result.output
    assert "issues_repo: me/radar" in (folder / "odoo-code-radar.yml").read_text()
    assert tokens.load() == TOKEN
    assert installed[0].frequency == "weekly" and installed[0].at == "06:00"


def test_schedule_local_refuses_public_issue_repo(tmp_path, monkeypatch):
    folder = radar_dir(tmp_path, "sources:\n  - repo: me/public\n")
    monkeypatch.setattr(cli, "GitHub", FakeGitHub)
    monkeypatch.setattr(cli.schedule_mod, "install", lambda job: [])
    result = runner.invoke(cli.app, ["schedule", "daily", "--dir", str(folder)], input=f"{TOKEN}\n")
    assert result.exit_code == 1
    assert "is public" in result.output
    assert tokens.load() is None  # nothing saved when setup fails


def test_schedule_github(tmp_path, monkeypatch):
    folder = radar_dir(tmp_path)
    monkeypatch.setattr(cli, "GitHub", FakeGitHub)
    calls = []

    class FakeGh:
        def available(self):
            return True

        def repo(self, repo):
            return {"private": True}

        def has_workflow_scope(self):
            return True

        def put_file(self, repo, path, content, message):
            calls.append(("put", repo, path, content))

        def set_secret(self, repo, value):
            calls.append(("secret", repo, value))

        def run_workflow(self, repo):
            return True

    monkeypatch.setattr(cli, "GhCli", FakeGh)
    result = runner.invoke(
        cli.app,
        ["schedule", "monthly", "--github", "--at", "07:15", "--dir", str(folder), "--repo", "me/radar"],
        input=f"{TOKEN}\n",
    )
    assert result.exit_code == 0, result.output
    workflow = next(c for c in calls if c[0] == "put" and c[2].startswith(".github"))
    assert '"15 7 1 * *"' in workflow[3]
    assert ("secret", "me/radar", TOKEN) in calls
    assert schedule.load_record(folder)["repo"] == "me/radar"
    assert tokens.load() is None  # --github keeps nothing on this machine


def test_schedule_github_without_gh_gives_manual_steps(tmp_path, monkeypatch):
    folder = radar_dir(tmp_path)
    monkeypatch.setattr(cli.GhCli, "available", lambda self: False)
    result = runner.invoke(cli.app, ["schedule", "weekly", "--github", "--dir", str(folder)])
    assert result.exit_code == 0, result.output
    assert (folder / ".github/workflows/odoo-code-radar.yml").exists()
    assert "RADAR_TOKEN" in result.output


def test_schedule_status_without_schedule(tmp_path):
    result = runner.invoke(cli.app, ["schedule", "status", "--dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "No schedule" in result.output


def test_ghsetup_module_has_no_token_in_argv():
    with open(ghsetup.__file__) as source:
        assert "--body" not in source.read()
