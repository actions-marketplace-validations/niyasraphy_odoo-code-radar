from odoo_code_radar.models import Module
from odoo_code_radar.scanner import (
    Scanner,
    ScanOptions,
    folder_matches,
    guess_vendor_author,
    module_location,
    queries_for,
    score,
)

PAID = Module(
    "om_dynamic_reports",
    names={"Odoo 16 Dynamic Accounting Reports - PDF, Excel"},
    license="OPL-1",
    authors={"Odoo Mates", "Odoo SA"},
)

LEAKED = "{'name': 'Dynamic Accounting Reports - PDF, Excel', 'author': 'Odoo Mates', 'version': '12.0.1.0'}"
OTHER = "{'name': 'Something Else', 'author': 'Odoo Mates'}"


def code_item(repo, path, ref="abc123"):
    return {
        "path": path,
        "repository": {"full_name": repo},
        "url": f"https://api.github.com/repos/{repo}/contents/{path}?ref={ref}",
    }


class FakeGitHub:
    def __init__(self, code=None, repos=None, files=None):
        self.code = code or {}
        self.repos = repos or {}
        self.files = files or {}
        self.queries = []

    def search_code(self, query, max_results=200):
        self.queries.append(query)
        return [item for key, items in self.code.items() if key in query for item in items]

    def search_repos(self, query, max_results=30):
        self.queries.append(query)
        return self.repos.get(query, [])

    def raw(self, repo, ref, path):
        return self.files.get((repo, path))

    def forks(self, repo, limit=100):
        return {"someone/fork": "main", "other/emptied": "dev"}

    def repo(self, repo):
        return {"forks_count": 3, "default_branch": "main"}


def test_queries_cover_folder_name_author_and_repo_name():
    queries = queries_for(PAID, "Odoo Mates")
    assert ("code", "filename:__manifest__.py path:om_dynamic_reports") in queries
    assert (
        "code",
        '"Odoo Mates" "Dynamic Accounting Reports - PDF, Excel" filename:__manifest__.py',
    ) in queries
    assert ("repo", "om_dynamic_reports in:name") in queries


def test_short_names_are_not_searched_without_an_author():
    module = Module("om_x", names={"Odoo 17 Sales"}, license="OPL-1")
    assert [q for kind, q in queries_for(module, "") if "Sales" in q] == []


def test_folder_matches_common_renames():
    assert folder_matches("om_dynamic_reports", "om_dynamic_reports")
    assert folder_matches("om-dynamic-reports", "om_dynamic_reports")
    assert folder_matches("om_dynamic_reports-17.0", "om_dynamic_reports")
    assert not folder_matches("om_dynamic_reports_extra", "om_dynamic_reports")


def test_score_adds_up_evidence():
    manifest = {"name": "Dynamic Accounting Reports - PDF, Excel", "author": "Odoo Mates"}
    points, reasons = score(PAID, "om_dynamic_reports", manifest, "Odoo Mates")
    assert points == 110
    assert len(reasons) == 3
    assert score(PAID, "renamed", manifest, "Odoo Mates")[0] == 70
    assert score(PAID, "om_dynamic_reports", {"name": "x"}, "Odoo Mates")[0] == 40


def test_guess_vendor_author_ignores_odoo_sa():
    modules = [
        Module("a", authors={"Odoo Mates", "Odoo SA"}),
        Module("b", authors={"Odoo Mates", "Odoo S.A."}),
    ]
    assert guess_vendor_author(modules) == "Odoo Mates"


def test_module_location_points_at_the_folder():
    assert module_location("a/b", "abc", "addons/om_x/__manifest__.py") == (
        "addons/om_x",
        "https://github.com/a/b/tree/abc/addons/om_x",
    )
    assert module_location("a/b", "main", "__manifest__.py") == (
        "(repository root)",
        "https://github.com/a/b",
    )


def test_scan_finds_copies_and_skips_own_and_unrelated_repos():
    gh = FakeGitHub(
        code={
            "path:om_dynamic_reports": [
                code_item("leaker/addons", "custom/om_dynamic_reports/__manifest__.py"),
                code_item("odoomates/odooapps", "om_dynamic_reports/__manifest__.py"),
            ],
            '"Odoo Mates"': [
                code_item("leaker/addons", "custom/om_dynamic_reports/__manifest__.py"),
                code_item("other/repo", "om_other/__manifest__.py"),
            ],
        },
        repos={
            "om_dynamic_reports in:name": [{"full_name": "solo/om_dynamic_reports", "default_branch": "main"}]
        },
        files={
            ("leaker/addons", "custom/om_dynamic_reports/__manifest__.py"): LEAKED,
            ("odoomates/odooapps", "om_dynamic_reports/__manifest__.py"): LEAKED,
            ("other/repo", "om_other/__manifest__.py"): OTHER,
            ("solo/om_dynamic_reports", "__manifest__.py"): LEAKED,
            ("someone/fork", "custom/om_dynamic_reports/__manifest__.py"): LEAKED,
            ("someone/fork", "__manifest__.py"): LEAKED,
        },
    )
    scanner = Scanner(gh, ScanOptions(vendor_author="Odoo Mates", ignore_owners={"OdooMates"}))
    findings = scanner.scan([PAID])
    assert {f.repo: f.confidence for f in findings} == {
        "leaker/addons": "high",
        "solo/om_dynamic_reports": "high",
    }
    leak = next(f for f in findings if f.repo == "leaker/addons")
    assert leak.files == {
        "custom/om_dynamic_reports": "https://github.com/leaker/addons/tree/abc123/custom/om_dynamic_reports"
    }
    assert leak.odoo_versions == {"12.0"}
    assert leak.priority == "high"

    scanner.enrich(findings)
    # Only forks that still hold the module count; "other/emptied" no longer does.
    assert leak.forks == {"someone/fork": "main"} and leak.fork_count == 3
    assert leak.default_branch == "main"
    assert not leak.whole_repo
    assert leak.folder_links() == ["https://github.com/leaker/addons/tree/main/custom/om_dynamic_reports"]
    solo = next(f for f in findings if f.repo == "solo/om_dynamic_reports")
    assert solo.whole_repo and solo.folder_links() == []


def test_scan_respects_min_confidence():
    gh = FakeGitHub(
        code={"path:om_dynamic_reports": [code_item("x/y", "om_dynamic_reports/__manifest__.py")]},
        files={("x/y", "om_dynamic_reports/__manifest__.py"): "{'name': 'Renamed', 'author': 'Someone'}"},
    )
    assert Scanner(gh, ScanOptions(vendor_author="Odoo Mates")).scan([PAID]) == []
    low = Scanner(gh, ScanOptions(vendor_author="Odoo Mates", min_confidence="low")).scan([PAID])
    assert [f.score for f in low] == [40]
