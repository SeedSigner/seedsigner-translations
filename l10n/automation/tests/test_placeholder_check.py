"""Tests for the format-placeholder integrity check."""

import json

import pytest

pytest.importorskip("babel")

import placeholder_check  # noqa: E402
from conftest import write_po  # noqa: E402


def check(tmp_path, entries, locale="de"):
    write_po(tmp_path / "l10n" / locale / "LC_MESSAGES" / "messages.po", entries)
    return placeholder_check.check_locales(str(tmp_path), [locale])


def test_clean_catalog_has_no_issues(tmp_path):
    report = check(tmp_path, [
        {"id": "Hello", "str": "Hallo"},
        {"id": "Enter {name}", "str": "{name} eingeben"},
        {"id": "{} of {}", "str": "{} von {}"},
    ])
    assert report["issues"] == []
    assert report["checked_locales"] == ["de"]
    assert report["counts"] == {"issues": 0, "locales_with_issues": 0}


def test_named_field_replaced_by_positional_is_flagged(tmp_path):
    # The real-world case this check exists for: a translation swapping the
    # named {mnemonic_length} field for a bare {} crashes .format at runtime.
    report = check(tmp_path, [{
        "id": "Enter your {mnemonic_length}-word BIP-39 mnemonic.",
        "str": "Angi ditt {}-ords BIP-39 mnemonic.",
    }], locale="no")

    assert len(report["issues"]) == 1
    issue = report["issues"][0]
    assert issue["problem"] == "mismatch"
    assert issue["expected"] == ["{mnemonic_length}"]
    assert issue["found"] == ["{}"]
    assert issue["locale"] == "no"


def test_dropped_positional_field_is_flagged(tmp_path):
    report = check(tmp_path, [{"id": "{} of {}", "str": "{} von allen"}])
    assert len(report["issues"]) == 1
    assert report["issues"][0]["expected"] == ["{}", "{}"]
    assert report["issues"][0]["found"] == ["{}"]


def test_renamed_field_is_flagged(tmp_path):
    report = check(tmp_path, [{"id": "Enter {name}", "str": "{nom} eingeben"}])
    assert len(report["issues"]) == 1
    assert report["issues"][0]["found"] == ["{nom}"]


def test_untranslated_entry_is_skipped(tmp_path):
    report = check(tmp_path, [{"id": "Enter {name}", "str": ""}])
    assert report["issues"] == []


def test_msgid_without_fields_is_not_a_format_string(tmp_path):
    # Braces a translator adds to plain text can never crash: the code never
    # calls .format on strings whose source has no fields. Even an unmatched
    # brace is fine here.
    report = check(tmp_path, [
        {"id": "Press OK", "str": "Druecke {OK}"},
        {"id": "Amount", "str": "Betrag {"},
    ])
    assert report["issues"] == []


def test_malformed_translation_of_format_string_is_flagged(tmp_path):
    report = check(tmp_path, [{"id": "Enter {name}", "str": "{name eingeben"}])
    assert len(report["issues"]) == 1
    assert report["issues"][0]["problem"] == "malformed"
    assert report["issues"][0]["found"] is None


def test_literal_braces_do_not_count_as_fields(tmp_path):
    report = check(tmp_path, [{"id": "Enter {name}", "str": "{{x}} {name}"}])
    assert report["issues"] == []


def test_plural_form_may_match_singular_or_plural_signature(tmp_path):
    # "one word" (no field) / "{} words": each translated form may follow
    # either source signature, since which grammatical numbers a form covers
    # varies by language.
    report = check(tmp_path, [{
        "id": "one word", "plural": "{} words",
        "str": "ein Wort", "plural_str": "{} Woerter",
    }])
    assert report["issues"] == []


def test_plural_form_matching_neither_signature_is_flagged(tmp_path):
    report = check(tmp_path, [{
        "id": "one word", "plural": "{} words",
        "str": "ein Wort", "plural_str": "{} von {} Woertern",
    }])
    assert len(report["issues"]) == 1
    assert report["issues"][0]["form"] == "msgstr[1]"


def test_fuzzy_issue_is_flagged_and_marked(tmp_path):
    # Fuzzy entries still compile under --use-fuzzy, so they are checked; the
    # flag lets consumers present them separately.
    report = check(tmp_path, [
        {"id": "Enter {name}", "str": "{} eingeben", "fuzzy": True},
    ])
    assert len(report["issues"]) == 1
    assert report["issues"][0]["fuzzy"] is True


def test_msgctxt_is_reported(tmp_path):
    report = check(tmp_path, [
        {"id": "Enter {name}", "str": "{} eingeben", "ctx": "menu"},
    ])
    assert report["issues"][0]["msgctxt"] == "menu"


def test_all_locales_discovered_when_none_specified(tmp_path):
    write_po(tmp_path / "l10n" / "de" / "LC_MESSAGES" / "messages.po",
             [{"id": "Enter {name}", "str": "{} eingeben"}])
    write_po(tmp_path / "l10n" / "ja" / "LC_MESSAGES" / "messages.po",
             [{"id": "Enter {name}", "str": "{name}"}])

    report = placeholder_check.check_locales(str(tmp_path))
    assert report["checked_locales"] == ["de", "ja"]
    assert report["counts"] == {"issues": 1, "locales_with_issues": 1}


def test_missing_locale_is_ignored(tmp_path):
    write_po(tmp_path / "l10n" / "de" / "LC_MESSAGES" / "messages.po",
             [{"id": "Hello", "str": "Hallo"}])
    report = placeholder_check.check_locales(str(tmp_path), ["de", "xx"])
    assert report["checked_locales"] == ["de"]


def test_cli_exit_codes_and_json(tmp_path, capsysbinary):
    write_po(tmp_path / "l10n" / "de" / "LC_MESSAGES" / "messages.po",
             [{"id": "Enter {name}", "str": "{} eingeben"}])

    rc = placeholder_check.main(["--root", str(tmp_path), "--locale", "de"])
    out = capsysbinary.readouterr().out.decode("utf-8")

    assert rc == 1
    report = json.loads(out)
    assert report["counts"]["issues"] == 1

    # Clean run exits 0
    write_po(tmp_path / "l10n" / "de" / "LC_MESSAGES" / "messages.po",
             [{"id": "Enter {name}", "str": "{name} eingeben"}])
    assert placeholder_check.main(["--root", str(tmp_path)]) == 0


def test_extract_signature():
    f = placeholder_check.extract_signature
    assert f("plain") == (0, frozenset())
    assert f("{} and {}") == (2, frozenset())
    assert f("{a} and {b}") == (0, frozenset({"a", "b"}))
    assert f("{} and {a}") == (1, frozenset({"a"}))
    assert f("{{literal}}") == (0, frozenset())
    assert f("{0} and {0}") == (0, frozenset({"0"}))
    assert f("broken {") is None
