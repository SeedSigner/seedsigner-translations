"""Tests for the sticky review-comment renderer."""

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import render_review_comment  # noqa: E402


def base_manifest(**over):
    m = {
        "schema_version": "1.0",
        "stream": "translation-review",
        "generated_at": "2026-07-21T00:00:00Z",
        "repository": "owner/repo",
        "pr": {"number": 7, "head_sha": "a" * 40, "base_ref": "dev"},
        "screenshots": {
            "added": [], "removed": [], "changed": [],
            "counts": {"added": 0, "removed": 0, "changed": 0,
                       "total_before": 0, "total_after": 0},
        },
        "checks": {"placeholder": None, "overflow": None},
        "notes": [],
    }
    m.update(over)
    return m


def placeholder_report(issues):
    return {
        "issues": issues,
        "checked_locales": sorted({i["locale"] for i in issues}) or ["de"],
        "counts": {"issues": len(issues),
                   "locales_with_issues": len({i["locale"] for i in issues})},
    }


def issue(**over):
    base = {"locale": "no", "msgctxt": None, "msgid": "Enter {name}",
            "form": "msgstr", "problem": "mismatch",
            "expected": ["{name}"], "found": ["{}"], "fuzzy": False}
    base.update(over)
    return base


def test_marker_and_counts():
    body = render_review_comment.render(base_manifest())
    assert render_review_comment.COMMENT_MARKER in body
    assert "0 changed, 0 added, 0 removed" in body
    assert "not run" in body


def test_placeholder_pass_and_overflow_clean():
    m = base_manifest(checks={"placeholder": placeholder_report([]),
                              "overflow": {"de": []}})
    body = render_review_comment.render(m)
    assert "Placeholder integrity: **PASS**" in body
    assert "Text overflow: none detected" in body


def test_placeholder_failure_lists_issues():
    m = base_manifest(checks={"placeholder": placeholder_report([issue()]),
                              "overflow": None})
    body = render_review_comment.render(m)
    assert "**FAIL** (1 issue(s))" in body
    assert "`no` `Enter {name}` (msgstr): expected `{name}`, found `{}`" in body


def test_placeholder_failure_list_is_capped():
    issues = [issue(msgid=f"String {i} with {{x}}") for i in range(15)]
    m = base_manifest(checks={"placeholder": placeholder_report(issues),
                              "overflow": None})
    body = render_review_comment.render(m)
    assert "...and 5 more" in body


def test_overflow_summary_per_locale():
    event = {"event_type": "bounds", "screen_name": "SomeView", "locale": "de",
             "component_text": "t", "overflow_px": 9, "component_type": "TextArea",
             "screen_y": 100, "effective_height": 150, "msgid": "m", "msgstr": "s"}
    m = base_manifest(checks={"placeholder": None,
                              "overflow": {"de": [event], "ja": [event, event]}})
    body = render_review_comment.render(m)
    assert "3 flagged component(s) (de: 1, ja: 2)" in body
    assert "advisory" in body


def test_page_url_link_included_only_when_given():
    m = base_manifest()
    body = render_review_comment.render(m, page_url="https://bot.github.io/x/pr-7/")
    assert "[Open the visual review page](https://bot.github.io/x/pr-7/)" in body

    assert "Open the visual review page" not in render_review_comment.render(m)


def test_untrusted_text_cannot_break_out():
    nasty = "evil`\n\n## pwned heading\n- nope"
    m = base_manifest(checks={
        "placeholder": placeholder_report([issue(msgid=nasty)]),
        "overflow": None,
    }, notes=[nasty])
    body = render_review_comment.render(m)
    for line in body.splitlines():
        assert not line.startswith("## pwned")
    assert "evil'" in body  # backticks stripped from code spans


def test_cli_writes_output(tmp_path, capsysbinary):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(base_manifest()), encoding="utf-8")
    out = tmp_path / "comment.md"

    rc = render_review_comment.main([
        "--manifest", str(manifest_path), "--page-url", "https://x/pr-7/",
        "--out", str(out)])
    assert rc == 0
    assert "https://x/pr-7/" in out.read_text(encoding="utf-8")

    rc = render_review_comment.main(["--manifest", str(manifest_path), "--out", "-"])
    assert rc == 0
    assert render_review_comment.COMMENT_MARKER.encode() in capsysbinary.readouterr().out
