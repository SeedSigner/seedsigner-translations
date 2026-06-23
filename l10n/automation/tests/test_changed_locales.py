"""Tests for the translation-bridge locale-change detector and path guard.

Run standalone (not part of any main suite):

    python -m pytest l10n/automation/tests -q
"""

import json

import pytest

# Parsing real .po files needs Babel; skip cleanly where it is absent.
pytest.importorskip("babel")

import changed_locales  # noqa: E402
from conftest import write_po  # noqa: E402


def _po(root, locale):
    return root / "l10n" / locale / "LC_MESSAGES" / "messages.po"


def test_header_only_change_is_converged(tmp_path):
    head, base = tmp_path / "head", tmp_path / "base"
    write_po(_po(base, "de"), [{"id": "Hello", "str": "Hallo"}], revision="2020-01-01 00:00+0000")
    write_po(_po(head, "de"), [{"id": "Hello", "str": "Hallo"}], revision="2026-06-23 12:00+0000")
    assert changed_locales.changed_locales(str(head), str(base)) == {"changed": [], "converged": ["de"]}


def test_msgstr_change_is_changed(tmp_path):
    head, base = tmp_path / "head", tmp_path / "base"
    write_po(_po(base, "de"), [{"id": "Hello", "str": "Hallo"}])
    write_po(_po(head, "de"), [{"id": "Hello", "str": "Servus"}])
    result = changed_locales.changed_locales(str(head), str(base))
    assert result == {"changed": ["de"], "converged": []}


def test_new_locale_is_changed(tmp_path):
    head, base = tmp_path / "head", tmp_path / "base"
    write_po(_po(base, "de"), [{"id": "Hello", "str": "Hallo"}])
    write_po(_po(head, "de"), [{"id": "Hello", "str": "Hallo"}])
    write_po(_po(head, "fr"), [{"id": "Hello", "str": "Bonjour"}])
    result = changed_locales.changed_locales(str(head), str(base))
    assert result == {"changed": ["fr"], "converged": ["de"]}


def test_removed_locale_is_changed(tmp_path):
    head, base = tmp_path / "head", tmp_path / "base"
    write_po(_po(base, "de"), [{"id": "Hello", "str": "Hallo"}])
    write_po(_po(head, "fr"), [{"id": "Hello", "str": "Bonjour"}])
    result = changed_locales.changed_locales(str(head), str(base))
    assert set(result["changed"]) == {"de", "fr"}
    assert result["converged"] == []


def test_fuzzy_toggle_is_changed(tmp_path):
    head, base = tmp_path / "head", tmp_path / "base"
    write_po(_po(base, "de"), [{"id": "Hello", "str": "Hallo"}])
    write_po(_po(head, "de"), [{"id": "Hello", "str": "Hallo", "fuzzy": True}])
    assert changed_locales.changed_locales(str(head), str(base))["changed"] == ["de"]


def test_allowlist_accepts_any_locale_and_source():
    assert changed_locales.assert_allowlisted([
        "l10n/de/LC_MESSAGES/messages.po",
        "l10n/zh_Hans_CN/LC_MESSAGES/messages.po",
        "l10n/xx/LC_MESSAGES/messages.po",
        "l10n/messages.pot",
    ]) == []


def test_allowlist_flags_non_translation_paths():
    violations = changed_locales.assert_allowlisted([
        "setup.py",
        ".github/workflows/evil.yml",
        "fonts/x.ttf",
        "l10n/de/LC_MESSAGES/messages.mo",
    ])
    assert set(violations) == {
        "setup.py", ".github/workflows/evil.yml", "fonts/x.ttf",
        "l10n/de/LC_MESSAGES/messages.mo",
    }


def test_cli_json_output(tmp_path, capsys):
    head, base = tmp_path / "head", tmp_path / "base"
    write_po(_po(base, "de"), [{"id": "Hello", "str": "Hallo"}])
    write_po(_po(head, "de"), [{"id": "Hello", "str": "Servus"}])
    changed = tmp_path / "changed.txt"
    changed.write_text("l10n/de/LC_MESSAGES/messages.po\n", encoding="utf-8")
    rc = changed_locales.main(["--head-root", str(head), "--base-root", str(base),
                               "--changed-paths", str(changed)])
    assert rc == 0
    assert json.loads(capsys.readouterr().out) == {"changed": ["de"], "converged": []}


def test_cli_guard_violation_exits_2(tmp_path):
    head, base = tmp_path / "head", tmp_path / "base"
    write_po(_po(base, "de"), [{"id": "Hello", "str": "Hallo"}])
    write_po(_po(head, "de"), [{"id": "Hello", "str": "Hallo"}])
    changed = tmp_path / "changed.txt"
    changed.write_text(".github/workflows/evil.yml\n", encoding="utf-8")
    rc = changed_locales.main(["--head-root", str(head), "--base-root", str(base),
                               "--changed-paths", str(changed)])
    assert rc == 2
