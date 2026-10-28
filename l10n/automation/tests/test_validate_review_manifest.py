"""Tests for the translation-review manifest validation (schema + trust anchors)."""

import json
import os
import pathlib
import sys

import pytest

pytest.importorskip("jsonschema")

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import validate_review_manifest  # noqa: E402

SCHEMA = os.path.join(os.path.dirname(__file__), "..", "schema",
                      "translation-review-manifest.schema.json")
HEAD = "a" * 40
REPO = "owner/repo"

EMPTY_DIFF = {
    "added": [], "removed": [], "changed": [],
    "counts": {"added": 0, "removed": 0, "changed": 0,
               "total_before": 0, "total_after": 0},
}


def valid_manifest(**over):
    m = {
        "schema_version": "1.0",
        "stream": "translation-review",
        "generated_at": "2026-07-21T00:00:00Z",
        "repository": REPO,
        "pr": {"number": 7, "head_sha": HEAD, "base_ref": "dev"},
        "screenshots": dict(EMPTY_DIFF),
        "checks": {"placeholder": None, "overflow": None},
        "notes": [],
    }
    m.update(over)
    return m


def run(tmp_path, manifest, *, head=HEAD, repo=REPO):
    p = tmp_path / "manifest.json"
    p.write_text(json.dumps(manifest), encoding="utf-8")
    return validate_review_manifest.validate(str(p), SCHEMA, head, repo)


def test_valid_manifest_has_no_errors(tmp_path):
    assert run(tmp_path, valid_manifest()) == []


def test_populated_manifest_validates(tmp_path):
    m = valid_manifest(
        screenshots={
            "added": ["no/seed_views/NewView.png"],
            "removed": [],
            "changed": ["zh_Hans_CN/psbt_views/SomeView.png"],
            "counts": {"added": 1, "removed": 0, "changed": 1,
                       "total_before": 150, "total_after": 151},
        },
        checks={
            "placeholder": {
                "issues": [{"locale": "no", "msgctxt": None, "msgid": "x {y}",
                            "form": "msgstr", "problem": "mismatch",
                            "expected": ["{y}"], "found": ["{}"], "fuzzy": False}],
                "checked_locales": ["no"],
                "counts": {"issues": 1, "locales_with_issues": 1},
            },
            "overflow": {
                "no": [{"event_type": "bounds", "screen_name": "SomeView",
                        "locale": "no", "component_text": "t", "overflow_px": 9,
                        "component_type": "TextArea", "screen_y": 100,
                        "effective_height": 150, "msgid": "m", "msgstr": "s"}],
            },
        })
    assert run(tmp_path, m) == []


def test_wrong_repository_rejected(tmp_path):
    errors = run(tmp_path, valid_manifest(), repo="someone/else")
    assert any("repository" in e for e in errors)


def test_wrong_head_sha_rejected(tmp_path):
    errors = run(tmp_path, valid_manifest(), head="b" * 40)
    assert any("head_sha" in e for e in errors)


def test_null_pr_fields_rejected(tmp_path):
    # Push-run manifests carry nulls; the consumer only acts on PR manifests,
    # and the schema must refuse anything without real PR coordinates.
    m = valid_manifest(pr={"number": None, "head_sha": None, "base_ref": None})
    errors = run(tmp_path, m, head="None")
    assert any(e.startswith("schema:") for e in errors)


def test_traversal_fragment_rejected(tmp_path):
    # The fragment allowlist is what makes manifest-listed names safe to use
    # as file paths downstream.
    for nasty in ["../../etc/passwd.png", "de/../x/y.png", "de/a/e.html",
                  "de/a/x.png/", "/abs/a/x.png"]:
        m = valid_manifest(screenshots=dict(EMPTY_DIFF, added=[nasty]))
        errors = run(tmp_path, m)
        assert any(e.startswith("schema:") for e in errors), nasty


def test_unknown_top_level_field_rejected(tmp_path):
    errors = run(tmp_path, valid_manifest(extra="nope"))
    assert any(e.startswith("schema:") for e in errors)


def test_bad_overflow_locale_key_rejected(tmp_path):
    m = valid_manifest(checks={"placeholder": None, "overflow": {"../..": []}})
    errors = run(tmp_path, m)
    assert any(e.startswith("schema:") for e in errors)


def test_wrong_stream_rejected(tmp_path):
    errors = run(tmp_path, valid_manifest(stream="messages-pot"))
    assert any(e.startswith("schema:") for e in errors)


def test_missing_manifest_is_a_clean_error(tmp_path):
    errors = validate_review_manifest.validate(
        str(tmp_path / "nope.json"), SCHEMA, HEAD, REPO)
    assert any(e.startswith("manifest: cannot read") for e in errors)


def test_malformed_manifest_is_a_clean_error(tmp_path):
    p = tmp_path / "manifest.json"
    p.write_text("{ not json", encoding="utf-8")
    errors = validate_review_manifest.validate(str(p), SCHEMA, HEAD, REPO)
    assert any("is not valid JSON" in e for e in errors)


def test_non_object_manifest_is_rejected(tmp_path):
    # Valid JSON, but not an object: must never validate clean.
    for payload in ("null", "[]", '"nope"'):
        p = tmp_path / "manifest.json"
        p.write_text(payload, encoding="utf-8")
        errors = validate_review_manifest.validate(str(p), SCHEMA, HEAD, REPO)
        assert f"manifest: {str(p)!r} is not a JSON object" in errors
