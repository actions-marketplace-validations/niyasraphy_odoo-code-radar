from pathlib import Path

from odoo_code_radar.sources import (
    manifest_paths,
    merge_modules,
    modules_from_path,
    modules_from_store,
    parse_browse_page,
    parse_module_page,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_browse_page():
    cards = parse_browse_page((FIXTURES / "store_browse.html").read_text())
    assert [(c.technical_name, c.version, c.name, c.price) for c in cards] == [
        ("om_hr_payroll", "20.0", "Odoo 20 HR Payroll", "FREE"),
        ("om_dynamic_reports", "16.0", "Odoo 16 Dynamic Accounting Reports - PDF, Excel", "$ 49.00"),
    ]


def test_parse_module_page():
    info = parse_module_page((FIXTURES / "store_module.html").read_text())
    assert info["name"] == "Odoo 16 Dynamic Accounting Reports - PDF, Excel"
    assert info["authors"] == {"Odoo Mates", "Odoo S.A."}
    assert info["license"] == "OPL-1"
    assert info["technical_name"] == "om_dynamic_reports"
    assert info["versions"] == {"14.0", "15.0", "16.0"}


class FakeResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


class FakeStore:
    """Serves the fixtures; the second module's page names another author."""

    def __init__(self):
        self.urls = []

    def get(self, url, headers=None, timeout=None):
        self.urls.append((url, headers))
        if "browse" in url:
            return FakeResponse((FIXTURES / "store_browse.html").read_text())
        page = (FIXTURES / "store_module.html").read_text()
        if "om_hr_payroll" in url:
            page = page.replace("Odoo Mates", "Someone Else")
        return FakeResponse(page)


def test_modules_from_store_keeps_only_the_authors_modules_and_sends_no_token():
    store = FakeStore()
    modules = modules_from_store("odoo mates", session=store, sleep=lambda _: None)
    assert [m.technical_name for m in modules] == ["om_dynamic_reports"]
    module = modules[0]
    assert module.license == "OPL-1"
    assert module.proprietary
    assert module.url == "https://apps.odoo.com/apps/modules/16.0/om_dynamic_reports"
    assert all("Authorization" not in (headers or {}) for _, headers in store.urls)


def test_manifest_paths():
    assert manifest_paths(["a/__manifest__.py", "b/views/x.xml", "__manifest__.py", "c/__openerp__.py"]) == [
        ("a", "a/__manifest__.py"),
        ("c", "c/__openerp__.py"),
    ]


def test_modules_from_path(tmp_path):
    module = tmp_path / "addons" / "om_paid"
    module.mkdir(parents=True)
    (module / "__manifest__.py").write_text(
        "{'name': 'Odoo 17 Paid', 'license': 'OPL-1', 'author': 'Me, Odoo SA', "
        "'website': 'https://me.example', 'version': '17.0.1.0'}"
    )
    (module / "static").mkdir()
    (tmp_path / "addons" / "om_free").mkdir()
    (tmp_path / "addons" / "om_free" / "__manifest__.py").write_text("{'name': 'Free'}")

    found = {m.technical_name: m for m in modules_from_path(tmp_path)}
    assert set(found) == {"om_paid", "om_free"}
    assert found["om_paid"].license == "OPL-1"
    assert found["om_paid"].authors == {"Me", "Odoo SA"}
    assert found["om_paid"].websites == {"me.example"}
    assert found["om_paid"].versions == {"17.0"}
    assert found["om_free"].license == "LGPL-3"  # Odoo's default


def test_merge_modules_keeps_names_of_every_version_and_the_proprietary_license(tmp_path):
    from odoo_code_radar.models import Module

    merged = merge_modules(
        [Module("om_x", {"Odoo 16 X"}, "LGPL-3", versions={"16.0"})],
        [Module("om_x", {"Odoo 17 X"}, "OPL-1", versions={"17.0"})],
    )
    assert len(merged) == 1
    assert merged[0].names == {"Odoo 16 X", "Odoo 17 X"}
    assert merged[0].license == "OPL-1"
    assert merged[0].versions == {"16.0", "17.0"}
