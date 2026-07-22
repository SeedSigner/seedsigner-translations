"""Tests for the screenshot diff / review-manifest producer."""

import json
import os
import pathlib
import sys

# The script lives with the workflow assets, not in l10n/automation.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / ".github" / "diff_report"))

import diff_screenshots  # noqa: E402


def write_tree(root, files):
    """files: {fragment: content} written under root."""
    for fragment, content in files.items():
        path = root / fragment.replace("/", os.path.sep)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return str(root)


def test_pathname_fragment_uses_forward_slashes(tmp_path):
    path = os.path.sep.join(["artifacts", "dev", "de", "psbt_views", "SomeView.png"])
    assert diff_screenshots.get_pathname_fragment(path) == "de/psbt_views/SomeView.png"


def test_locale_and_screenshot_name():
    assert diff_screenshots.get_locale_and_screenshot_name("de/psbt_views/SomeView.png") == \
        ("de", "SomeView")


def test_diff_buckets_added_removed_changed(tmp_path):
    before = write_tree(tmp_path / "dev", {
        "de/a/Same.png": b"same",
        "de/a/Changed.png": b"old",
        "de/a/Removed.png": b"gone",
    })
    after = write_tree(tmp_path / "incoming", {
        "de/a/Same.png": b"same",
        "de/a/Changed.png": b"new",
        "de/a/Added.png": b"fresh",
    })

    diff = diff_screenshots.diff_screenshot_trees(before, after)

    assert diff["added"] == ["de/a/Added.png"]
    assert diff["removed"] == ["de/a/Removed.png"]
    assert diff["changed"] == ["de/a/Changed.png"]
    assert diff["counts"] == {"added": 1, "removed": 1, "changed": 1,
                              "total_before": 3, "total_after": 3}


def test_diff_lists_are_sorted_for_determinism(tmp_path):
    before = write_tree(tmp_path / "dev", {})
    after = write_tree(tmp_path / "incoming", {
        "ja/b/Zeta.png": b"z", "de/a/Alpha.png": b"a", "de/z/Mid.png": b"m",
    })

    diff = diff_screenshots.diff_screenshot_trees(before, after)
    assert diff["added"] == ["de/a/Alpha.png", "de/z/Mid.png", "ja/b/Zeta.png"]


def test_copy_screenshots_places_before_and_after(tmp_path):
    before = write_tree(tmp_path / "dev", {"de/a/Changed.png": b"old",
                                           "de/a/Removed.png": b"gone"})
    after = write_tree(tmp_path / "incoming", {"de/a/Changed.png": b"new",
                                               "de/a/Added.png": b"fresh"})
    out = tmp_path / "diff"

    diff = diff_screenshots.diff_screenshot_trees(before, after)
    diff_screenshots.copy_screenshots(diff, before, after, str(out))

    assert (out / "before" / "de" / "a" / "Changed.png").read_bytes() == b"old"
    assert (out / "after" / "de" / "a" / "Changed.png").read_bytes() == b"new"
    assert (out / "before" / "de" / "a" / "Removed.png").exists()
    assert (out / "after" / "de" / "a" / "Added.png").exists()
    # Unchanged screenshots are not copied at all
    assert not (out / "before" / "de" / "a" / "Added.png").exists()


def test_cli_writes_manifest_and_html(tmp_path):
    before = write_tree(tmp_path / "dev", {"de/a/Changed.png": b"old"})
    after = write_tree(tmp_path / "incoming", {"de/a/Changed.png": b"new"})
    out = tmp_path / "diff"
    out.mkdir()

    placeholder_report = tmp_path / "placeholder.json"
    placeholder_report.write_text(json.dumps({"issues": [], "counts": {"issues": 0}}),
                                  encoding="utf-8")

    rc = diff_screenshots.main([
        before, after, str(out), "my-branch",
        "--repository", "owner/repo", "--pr-number", "12",
        "--head-sha", "cafe123", "--base-ref", "dev",
        "--placeholder-report", str(placeholder_report),
    ])
    assert rc == 0

    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "1.0"
    assert manifest["stream"] == "translation-review"
    assert manifest["repository"] == "owner/repo"
    assert manifest["pr"] == {"number": 12, "head_sha": "cafe123", "base_ref": "dev"}
    assert manifest["screenshots"]["changed"] == ["de/a/Changed.png"]
    assert manifest["checks"]["placeholder"] == {"issues": [], "counts": {"issues": 0}}
    assert manifest["checks"]["overflow"] is None
    assert manifest["notes"] == []

    assert "de/a/Changed.png" in (out / "index.html").read_text(encoding="utf-8")
    assert (out / "pico.min.css").exists()


def test_cli_without_pr_args_leaves_manifest_fields_null(tmp_path):
    before = write_tree(tmp_path / "dev", {"de/a/Same.png": b"same"})
    after = write_tree(tmp_path / "incoming", {"de/a/Same.png": b"same"})
    out = tmp_path / "diff"
    out.mkdir()

    assert diff_screenshots.main([before, after, str(out), "my-branch"]) == 0

    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["repository"] is None
    assert manifest["pr"] == {"number": None, "head_sha": None, "base_ref": None}
    assert manifest["screenshots"]["counts"]["changed"] == 0


def test_unreadable_check_report_becomes_a_note(tmp_path):
    before = write_tree(tmp_path / "dev", {})
    after = write_tree(tmp_path / "incoming", {})
    out = tmp_path / "diff"
    out.mkdir()

    corrupt = tmp_path / "overflow.json"
    corrupt.write_text("{ not json", encoding="utf-8")

    assert diff_screenshots.main([
        before, after, str(out), "ref", "--overflow-report", str(corrupt),
    ]) == 0

    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["checks"]["overflow"] is None
    assert len(manifest["notes"]) == 1
    assert "could not be read" in manifest["notes"][0]


def test_notes_flag_lands_in_manifest(tmp_path):
    before = write_tree(tmp_path / "dev", {})
    after = write_tree(tmp_path / "incoming", {})
    out = tmp_path / "diff"
    out.mkdir()

    assert diff_screenshots.main([
        before, after, str(out), "ref",
        "--note", "Rendering skipped: fix the placeholder issues first.",
    ]) == 0

    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["notes"] == ["Rendering skipped: fix the placeholder issues first."]
