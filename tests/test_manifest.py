from odoo_code_radar.manifest import (
    is_proprietary,
    normalize_name,
    normalize_website,
    odoo_version,
    parse_manifest,
    search_phrase,
)


def test_parse_manifest_reads_literals_without_running_code():
    text = """
# -*- coding: utf-8 -*-
{
    'name': 'Odoo 18 HR Payroll',
    'version': '18.0.1.2.0',
    'license': 'OPL-1',
    'author': 'Odoo Mates, Odoo SA',
    'depends': ['hr'],
    'computed': __import__('os').system('echo pwned'),
}
"""
    manifest = parse_manifest(text)
    assert manifest["name"] == "Odoo 18 HR Payroll"
    assert manifest["license"] == "OPL-1"
    assert manifest["depends"] == ["hr"]
    assert "computed" not in manifest


def test_parse_manifest_handles_garbage():
    assert parse_manifest("this is not python {") == {}
    assert parse_manifest("x = 1") == {}
    assert parse_manifest("{" * 10 + "}" * 10) in ({}, {})


def test_parse_manifest_refuses_huge_files():
    assert parse_manifest("{'name': '" + "x" * 300_000 + "'}") == {}


def test_names_match_across_odoo_versions():
    assert normalize_name("Odoo 18 HR Payroll") == normalize_name("Odoo 20 HR Payroll") == "hr payroll"
    assert normalize_name("Dynamic Accounting Reports - PDF, Excel") == "dynamic accounting reports pdf excel"
    assert normalize_name("Odoo 16 Dynamic Accounting Reports - PDF, Excel") == normalize_name(
        "Dynamic Accounting Reports - PDF, Excel"
    )


def test_search_phrase_drops_version_and_search_syntax():
    assert search_phrase("Odoo 18 HR Payroll") == "HR Payroll"
    assert search_phrase('Fiscal Year & "Lock" Date') == "Fiscal Year Lock Date"


def test_odoo_version():
    assert odoo_version("18.0.1.2.0") == "18.0"
    assert odoo_version("1.0") == ""
    assert odoo_version("1.0.3") == ""
    assert odoo_version("17.0") == "17.0"
    assert odoo_version("saas-17.2") == ""
    assert odoo_version(None) == ""


def test_website_and_license_helpers():
    assert normalize_website("https://www.odoomates.tech/shop") == "odoomates.tech"
    assert is_proprietary("OPL-1")
    assert is_proprietary("Other proprietary")
    assert not is_proprietary("LGPL-3")
