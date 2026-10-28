"""Assemble the static review page for a translation PR.

Runs in the trusted report job on a schema-validated manifest, but the
artifact files next to that manifest were produced by untrusted PR code, so
nothing from the artifact is trusted by name or content:

* only files the manifest lists are touched at all; nothing is globbed;
* every path is re-checked against the fragment allowlist and confined to the
  artifact directory (no symlinks, no traversal);
* every file must carry the PNG magic bytes and respect a size cap;
* every piece of text rendered into the page is HTML-escaped.

A listed file that is missing or invalid rejects the whole artifact: the
producer writes the manifest and the files together, so any mismatch means a
bug or tampering, and serving a partial page would hide that.

The output directory is self-contained (one index.html plus the copied PNGs,
inline CSS, no scripts) and is deployed as-is under /pr-<n>/ on the review
Pages site.

Usage::

    python l10n/automation/build_review_page.py \
        --manifest incoming/manifest.json --artifact-dir incoming --out page
"""

import argparse
import html
import json
import os
import re
import shutil
import sys

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
MAX_PNG_BYTES = 5 * 1024 * 1024

# Mirrors the manifest schema's fragment pattern; re-checked here so this
# script does not silently depend on the schema validation having run.
_FRAGMENT_RE = re.compile(
    r"^[A-Za-z][A-Za-z0-9_]{0,19}/[a-z0-9_]{1,60}/[A-Za-z0-9_.-]{1,120}\.png$")
_REPORT_RE = re.compile(
    r"^reports/[A-Za-z][A-Za-z0-9_]{0,19}/[A-Za-z0-9_.-]{1,120}\.png$")

_CSS = """
body { font-family: system-ui, sans-serif; margin: 2rem auto; max-width: 70rem;
       padding: 0 1rem; background: #111; color: #ddd; }
h1, h2, h3 { color: #fff; }
a { color: #f90; }
table { border-collapse: collapse; margin: 1rem 0; }
td, th { border: 1px solid #444; padding: 0.4rem 0.7rem; text-align: left; }
code { background: #222; padding: 0.1rem 0.3rem; border-radius: 3px; }
.pass { color: #6c6; } .fail { color: #e66; } .advisory { color: #ec3; }
figure { display: inline-block; margin: 0.6rem; text-align: center; vertical-align: top; }
figcaption { font-size: 0.8rem; color: #aaa; max-width: 500px;
             overflow-wrap: break-word; }
img { image-rendering: pixelated; border: 1px solid #444; max-width: 100%; }
.pair img { width: 240px; }
.note { color: #999; font-size: 0.9rem; }
"""


class ArtifactError(Exception):
    """A manifest-listed file is missing or fails validation."""


def _validated_source(artifact_dir: str, relpath: str, pattern: re.Pattern) -> str:
    """Resolve a manifest-listed relative path inside the artifact dir,
    enforcing the allowlist, containment, regular-file, magic and size rules.
    """
    if not pattern.fullmatch(relpath):
        raise ArtifactError(f"path {relpath!r} does not match the allowlist")

    root = os.path.realpath(artifact_dir)
    path = os.path.realpath(os.path.join(root, relpath.replace("/", os.path.sep)))
    if os.path.commonpath([root, path]) != root:
        raise ArtifactError(f"path {relpath!r} escapes the artifact directory")

    if os.path.islink(os.path.join(root, relpath.replace("/", os.path.sep))):
        raise ArtifactError(f"{relpath!r} is a symlink")
    if not os.path.isfile(path):
        raise ArtifactError(f"manifest lists {relpath!r} but it is missing")

    size = os.path.getsize(path)
    if size > MAX_PNG_BYTES:
        raise ArtifactError(f"{relpath!r} is {size} bytes; cap is {MAX_PNG_BYTES}")

    with open(path, "rb") as fh:
        if fh.read(len(PNG_MAGIC)) != PNG_MAGIC:
            raise ArtifactError(f"{relpath!r} is not a PNG")

    return path


def collect_files(manifest: dict, artifact_dir: str) -> dict:
    """Map every file the page needs (relpath -> validated source path).

    Diff-listed screenshots are mandatory; an overflow composite is optional
    because the scanner only writes one when the translated screenshot exists.
    """
    files = {}

    screenshots = manifest["screenshots"]
    for fragment in screenshots["removed"]:
        rel = f"before/{fragment}"
        files[rel] = _validated_source(artifact_dir, rel, re.compile(r"^before/" + _FRAGMENT_RE.pattern[1:]))
    for fragment in screenshots["added"]:
        rel = f"after/{fragment}"
        files[rel] = _validated_source(artifact_dir, rel, re.compile(r"^after/" + _FRAGMENT_RE.pattern[1:]))
    for fragment in screenshots["changed"]:
        for side in ("before", "after"):
            rel = f"{side}/{fragment}"
            files[rel] = _validated_source(artifact_dir, rel, re.compile(f"^{side}/" + _FRAGMENT_RE.pattern[1:]))

    overflow = (manifest.get("checks") or {}).get("overflow") or {}
    for locale, events in overflow.items():
        for event in events:
            rel = f"reports/{locale}/{event['screen_name']}_overflow.png"
            if rel in files:
                continue
            # A composite is optional: the scanner only writes one when the
            # translated screenshot exists. But if present it must validate.
            if not os.path.lexists(os.path.join(artifact_dir, rel.replace("/", os.path.sep))):
                continue
            files[rel] = _validated_source(artifact_dir, rel, _REPORT_RE)

    return files


def _esc(value) -> str:
    return html.escape(str(value), quote=True)


def _placeholder_section(placeholder) -> list:
    lines = ["<h2>Placeholder integrity (blocking)</h2>"]
    if placeholder is None:
        lines.append('<p class="note">Not run for this PR.</p>')
        return lines

    issues = placeholder["issues"]
    checked = ", ".join(placeholder["checked_locales"]) or "none"
    if not issues:
        lines.append(f'<p class="pass">PASS: no placeholder issues '
                     f'(locales checked: {_esc(checked)}).</p>')
        return lines

    lines.append(f'<p class="fail">FAIL: {len(issues)} issue(s) '
                 f'(locales checked: {_esc(checked)}). A wrong placeholder '
                 f'crashes or silently breaks the rendered text.</p>')
    lines.append("<table><tr><th>Locale</th><th>Source string</th><th>Form</th>"
                 "<th>Expected</th><th>Found</th></tr>")
    for issue in issues[:50]:
        found = "(does not parse)" if issue["found"] is None else " ".join(issue["found"])
        fuzzy = " (fuzzy)" if issue.get("fuzzy") else ""
        lines.append(
            f"<tr><td>{_esc(issue['locale'])}</td>"
            f"<td><code>{_esc(issue['msgid'])}</code></td>"
            f"<td>{_esc(issue['form'])}{_esc(fuzzy)}</td>"
            f"<td><code>{_esc(' '.join(issue['expected']))}</code></td>"
            f"<td><code>{_esc(found)}</code></td></tr>")
    lines.append("</table>")
    if len(issues) > 50:
        lines.append(f'<p class="note">...and {len(issues) - 50} more.</p>')
    return lines


def _overflow_section(overflow, files: dict) -> list:
    lines = ["<h2>Text overflow (advisory)</h2>"]
    if overflow is None:
        lines.append('<p class="note">Not run for this PR.</p>')
        return lines

    total = sum(len(events) for events in overflow.values())
    if total == 0:
        lines.append('<p class="pass">No overflow detected in the scanned locales.</p>')
        return lines

    lines.append(f'<p class="advisory">{total} flagged component(s). Overflow is a '
                 f'visual judgment call and has known false positives (untranslated '
                 f'literals, screens that already overflow in English).</p>')
    for locale in sorted(overflow):
        events = overflow[locale]
        if not events:
            continue
        lines.append(f"<h3>{_esc(locale)}</h3>")
        for event in events:
            composite = f"reports/{locale}/{event['screen_name']}_overflow.png"
            lines.append("<figure>")
            if composite in files:
                lines.append(f'<img src="{_esc(composite)}" alt="{_esc(event["screen_name"])} overflow composite">')
            lines.append(
                f"<figcaption>[{_esc(event['event_type'])}] "
                f"{_esc(event['screen_name'])}: {_esc(event['overflow_px'])}px"
                + (f"<br><code>{_esc(event['msgstr'])}</code>" if event.get("msgstr") else "")
                + "</figcaption></figure>")
    return lines


def _screenshots_section(screenshots: dict) -> list:
    counts = screenshots["counts"]
    lines = ["<h2>Screenshot changes</h2>"]
    lines.append(
        f"<p>{counts['changed']} changed, {counts['added']} added, "
        f"{counts['removed']} removed (out of {counts['total_after']} rendered).</p>")

    if not (screenshots["changed"] or screenshots["added"] or screenshots["removed"]):
        lines.append('<p class="pass">No visual changes.</p>')
        return lines

    if screenshots["changed"]:
        lines.append("<h3>Changed (before / after)</h3>")
        for fragment in screenshots["changed"]:
            lines.append(
                f'<figure class="pair">'
                f'<img src="{_esc("before/" + fragment)}" alt="before">'
                f'<img src="{_esc("after/" + fragment)}" alt="after">'
                f"<figcaption>{_esc(fragment)}</figcaption></figure>")

    if screenshots["added"]:
        lines.append("<h3>Added</h3>")
        for fragment in screenshots["added"]:
            lines.append(
                f'<figure class="pair"><img src="{_esc("after/" + fragment)}" alt="added">'
                f"<figcaption>{_esc(fragment)}</figcaption></figure>")

    if screenshots["removed"]:
        lines.append("<h3>Removed</h3>")
        for fragment in screenshots["removed"]:
            lines.append(
                f'<figure class="pair"><img src="{_esc("before/" + fragment)}" alt="removed">'
                f"<figcaption>{_esc(fragment)}</figcaption></figure>")

    return lines


def build_html(manifest: dict, files: dict) -> str:
    pr = manifest["pr"]
    lines = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>Translation review: PR #{_esc(pr['number'])}</title>",
        f"<style>{_CSS}</style>",
        "</head><body>",
        f"<h1>Translation review: PR #{_esc(pr['number'])}</h1>",
        f"<p>{_esc(manifest['repository'])} &middot; base <code>{_esc(pr['base_ref'])}</code> "
        f"&middot; head <code>{_esc(pr['head_sha'][:10])}</code> "
        f"&middot; generated {_esc(manifest['generated_at'])}</p>",
    ]

    checks = manifest["checks"]
    lines += _placeholder_section(checks["placeholder"])
    lines += _overflow_section(checks["overflow"], files)
    lines += _screenshots_section(manifest["screenshots"])

    for note in manifest.get("notes", []):
        lines.append(f'<p class="note">Note: {_esc(note)}</p>')

    lines.append('<p class="note">Static review page generated by the l10n '
                 'automation; images only, no scripts.</p>')
    lines.append("</body></html>")
    return "\n".join(lines) + "\n"


def build_page(manifest_path: str, artifact_dir: str, out_dir: str) -> int:
    with open(manifest_path, encoding="utf-8") as fh:
        manifest = json.load(fh)

    try:
        files = collect_files(manifest, artifact_dir)
    except ArtifactError as exc:
        print(f"Artifact rejected: {exc}", file=sys.stderr)
        return 1

    os.makedirs(out_dir, exist_ok=True)
    for rel, source in sorted(files.items()):
        dest = os.path.join(out_dir, rel.replace("/", os.path.sep))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copyfile(source, dest)

    with open(os.path.join(out_dir, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(build_html(manifest, files))

    print(f"Review page built: {len(files)} image(s) + index.html in {out_dir}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Build the static translation-review page.")
    p.add_argument("--manifest", required=True)
    p.add_argument("--artifact-dir", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args(argv)
    return build_page(args.manifest, args.artifact_dir, args.out)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
