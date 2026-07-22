"""Tests for the review-page builder (artifact file validation + static HTML)."""

import json
import os
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import build_review_page  # noqa: E402

PNG = build_review_page.PNG_MAGIC + b"fakepixels"
HEAD = "a" * 40


def base_manifest(**over):
    m = {
        "schema_version": "1.0",
        "stream": "translation-review",
        "generated_at": "2026-07-21T00:00:00Z",
        "repository": "owner/repo",
        "pr": {"number": 7, "head_sha": HEAD, "base_ref": "dev"},
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


def write_artifact(tmp_path, manifest, files):
    incoming = tmp_path / "incoming"
    incoming.mkdir(exist_ok=True)
    (incoming / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    for rel, content in files.items():
        path = incoming / rel.replace("/", os.path.sep)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return incoming


def build(tmp_path, manifest, files):
    incoming = write_artifact(tmp_path, manifest, files)
    out = tmp_path / "page"
    rc = build_review_page.build_page(str(incoming / "manifest.json"), str(incoming), str(out))
    return rc, out


def changed_manifest(fragment="de/psbt_views/SomeView.png"):
    return base_manifest(screenshots={
        "added": [], "removed": [], "changed": [fragment],
        "counts": {"added": 0, "removed": 0, "changed": 1,
                   "total_before": 1, "total_after": 1},
    })


def test_happy_path_builds_page_with_copies(tmp_path):
    fragment = "de/psbt_views/SomeView.png"
    rc, out = build(tmp_path, changed_manifest(fragment), {
        f"before/{fragment}": PNG, f"after/{fragment}": PNG + b"2",
    })

    assert rc == 0
    assert (out / "before" / "de" / "psbt_views" / "SomeView.png").exists()
    assert (out / "after" / "de" / "psbt_views" / "SomeView.png").exists()
    html = (out / "index.html").read_text(encoding="utf-8")
    assert "Translation review: PR #7" in html
    assert f'src="before/{fragment}"' in html
    assert "<script" not in html.lower().replace("</script", "")


def test_missing_listed_file_rejects_artifact(tmp_path):
    rc, out = build(tmp_path, changed_manifest(), {
        "before/de/psbt_views/SomeView.png": PNG,
        # after/ copy missing
    })
    assert rc == 1
    assert not (out / "index.html").exists()


def test_non_png_content_rejects_artifact(tmp_path):
    fragment = "de/psbt_views/SomeView.png"
    rc, _out = build(tmp_path, changed_manifest(fragment), {
        f"before/{fragment}": PNG,
        f"after/{fragment}": b"<html>not a png</html>",
    })
    assert rc == 1


def test_oversize_file_rejects_artifact(tmp_path, monkeypatch):
    monkeypatch.setattr(build_review_page, "MAX_PNG_BYTES", 100)
    fragment = "de/psbt_views/SomeView.png"
    rc, _out = build(tmp_path, changed_manifest(fragment), {
        f"before/{fragment}": PNG,
        f"after/{fragment}": PNG + b"x" * 200,
    })
    assert rc == 1


def test_symlink_rejects_artifact(tmp_path):
    fragment = "de/psbt_views/SomeView.png"
    incoming = write_artifact(tmp_path, changed_manifest(fragment), {
        f"before/{fragment}": PNG,
    })
    target = tmp_path / "outside.png"
    target.write_bytes(PNG)
    link = incoming / "after" / "de" / "psbt_views" / "SomeView.png"
    link.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(target, link)

    rc = build_review_page.build_page(
        str(incoming / "manifest.json"), str(incoming), str(tmp_path / "page"))
    assert rc == 1


def test_bad_fragment_rejected_by_allowlist(tmp_path):
    # Defense in depth: even if schema validation were skipped, the builder
    # itself refuses fragments outside the allowlist.
    manifest = changed_manifest("de/../../evil.png")
    with pytest.raises(build_review_page.ArtifactError):
        build_review_page.collect_files(manifest, str(tmp_path))


def test_untrusted_text_is_escaped_into_the_page(tmp_path):
    nasty = '<script>alert(1)</script><img src=x onerror=alert(1)>'
    manifest = base_manifest(checks={
        "placeholder": {
            "issues": [{"locale": "de", "msgctxt": None, "msgid": nasty,
                        "form": "msgstr", "problem": "mismatch",
                        "expected": ["{x}"], "found": [nasty], "fuzzy": False}],
            "checked_locales": ["de"],
            "counts": {"issues": 1, "locales_with_issues": 1},
        },
        "overflow": None,
    }, notes=[nasty])

    rc, out = build(tmp_path, manifest, {})
    assert rc == 0
    html = (out / "index.html").read_text(encoding="utf-8")
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_optional_composite_missing_is_fine_but_invalid_composite_rejects(tmp_path):
    overflow = {"de": [{"event_type": "bounds", "screen_name": "SomeView",
                        "locale": "de", "component_text": "t", "overflow_px": 9,
                        "component_type": "TextArea", "screen_y": 100,
                        "effective_height": 150, "msgid": "m", "msgstr": "s"}]}
    manifest = base_manifest(checks={"placeholder": None, "overflow": overflow})

    # Composite absent: page still builds, without the image
    rc, out = build(tmp_path, manifest, {})
    assert rc == 0
    assert "reports/de/SomeView_overflow.png" not in \
        (out / "index.html").read_text(encoding="utf-8")

    # Composite present: copied and referenced
    rc, out = build(tmp_path, manifest, {"reports/de/SomeView_overflow.png": PNG})
    assert rc == 0
    assert (out / "reports" / "de" / "SomeView_overflow.png").exists()
    assert "reports/de/SomeView_overflow.png" in \
        (out / "index.html").read_text(encoding="utf-8")

    # Composite present but not a PNG: the whole artifact is rejected
    rc, _out = build(tmp_path, manifest, {"reports/de/SomeView_overflow.png": b"nope"})
    assert rc == 1


def test_clean_manifest_builds_no_changes_page(tmp_path):
    rc, out = build(tmp_path, base_manifest(), {})
    assert rc == 0
    html = (out / "index.html").read_text(encoding="utf-8")
    assert "No visual changes" in html
