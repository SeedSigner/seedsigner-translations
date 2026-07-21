"""
Compare screenshots before and after a change; report the differences.

Produces, in output_dir:

* before/ and after/ copies of every added, removed or changed screenshot,
  keyed by the shared path fragment <locale>/<section>/<ScreenshotName>.png
* manifest.json, a machine-readable summary of the diff (plus any check
  reports passed in) for downstream automation
* index.html, a human-readable report of the same

Expected usage in a GitHub Actions workflow; compare `dev` with the
`$INCOMING_CHANGES_REF` in the associated PR or merge that triggered the CI run:

python src/seedsigner/resources/seedsigner-translations/.github/diff_report/diff_screenshots.py \
    ./artifacts/dev ./artifacts/incoming ./artifacts/diff $INCOMING_CHANGES_REF

The optional --repository / --pr-number / --head-sha / --base-ref args embed
the PR coordinates in the manifest so a trusted follow-up job can bind it to
the triggering run; --placeholder-report / --overflow-report embed those
check results. All are omitted on plain push runs, leaving manifest fields
null.
"""
import argparse
import glob
import hashlib
import json
import os
import pathlib
import shutil
from datetime import datetime, timezone

SCHEMA_VERSION = "1.0"
STREAM = "translation-review"


def list_files_recursively(path: str) -> list[str]:
    """ Return a list of paths to all png files in the directory tree """
    return glob.glob(path + "/**/*.png", recursive=True)


def compute_file_hash(file_path: str) -> str:
    """ Return the file hash using sha256 """
    hash_func = hashlib.new('sha256')

    with open(file_path, 'rb') as file:
        while chunk := file.read(8192):  # Read the file in chunks of 8192 bytes
            hash_func.update(chunk)

    return hash_func.hexdigest()


def get_pathname_fragment(path: str) -> str:
    """ Extract the last 3 parts of the path:
            en/tools_views/ToolsCalcFinalWordDoneView.png

        These paths will be the same in the "before" and "after" directories.
        Fragments always use forward slashes, regardless of OS.
    """
    parts = path.split(os.path.sep)
    if len(parts) < 3:
        raise ValueError(f"Path should have at least 3 parts: {path}")
    return "/".join(parts[-3:])


def get_locale_and_screenshot_name(fragment: str) -> tuple[str, str]:
    """ Parse a path fragment to extract the locale and the screenshot name.

        Assumes we're working with a fragment like:
            en/tools_views/ToolsCalcFinalWordDoneView.png
    """
    parts = fragment.split("/")
    if len(parts) != 3:
        raise ValueError(f"Path should have 3 parts: {fragment}")
    return parts[0], parts[-1].split(".")[0]


def diff_screenshot_trees(before_dir: str, after_dir: str) -> dict:
    """ Hash every png on both sides and bucket the fragments into
        added / removed / changed. """
    before_hashes = {}
    for file in list_files_recursively(before_dir):
        before_hashes[get_pathname_fragment(file)] = compute_file_hash(file)

    added = []
    changed = []
    after_fragments = set()
    for file in list_files_recursively(after_dir):
        fragment = get_pathname_fragment(file)
        after_fragments.add(fragment)
        if fragment not in before_hashes:
            added.append(fragment)
        elif before_hashes[fragment] != compute_file_hash(file):
            changed.append(fragment)

    removed = sorted(set(before_hashes) - after_fragments)

    return {
        "added": sorted(added),
        "removed": removed,
        "changed": sorted(changed),
        "counts": {
            "added": len(added),
            "removed": len(removed),
            "changed": len(changed),
            "total_before": len(before_hashes),
            "total_after": len(after_fragments),
        },
    }


def copy_screenshots(diff: dict, before_dir: str, after_dir: str, output_dir: str):
    """ Copy every flagged screenshot into output_dir/before and
        output_dir/after, preserving the path fragment. """
    output_dir_before = os.path.join(output_dir, "before")
    output_dir_after = os.path.join(output_dir, "after")
    os.makedirs(output_dir_before, exist_ok=True)
    os.makedirs(output_dir_after, exist_ok=True)

    def copy(src_root: str, dst_root: str, fragment: str):
        relpath = fragment.replace("/", os.path.sep)
        os.makedirs(os.path.join(dst_root, os.path.dirname(relpath)), exist_ok=True)
        shutil.copy(os.path.join(src_root, relpath), os.path.join(dst_root, relpath))

    for fragment in diff["removed"]:
        copy(before_dir, output_dir_before, fragment)

    for fragment in diff["added"]:
        copy(after_dir, output_dir_after, fragment)

    for fragment in diff["changed"]:
        copy(before_dir, output_dir_before, fragment)
        copy(after_dir, output_dir_after, fragment)


def load_check_report(path, label: str, notes: list):
    """ Load a check's JSON output for embedding in the manifest. A missing or
        unreadable report is recorded as a note rather than a crash, so the
        manifest still says what it does not know. """
    if not path:
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        notes.append(f"{label} report at {path!r} could not be read: {e}")
        return None


def build_manifest(diff: dict, args: argparse.Namespace, notes: list) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "stream": STREAM,
        "generated_at": datetime.now(timezone.utc)
            .replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "repository": args.repository,
        "pr": {
            "number": args.pr_number,
            "head_sha": args.head_sha,
            "base_ref": args.base_ref,
        },
        "screenshots": diff,
        "checks": {
            "placeholder": load_check_report(args.placeholder_report, "placeholder", notes),
            "overflow": load_check_report(args.overflow_report, "overflow", notes),
        },
        "notes": notes,
    }


def build_html(diff: dict, baseline_branch: str, incoming_changes_ref: str) -> str:
    html_content = "<h1>Screenshots diff report</h1>"
    html_content += f"""<p>Comparing {baseline_branch} to {incoming_changes_ref}</p>"""

    for fragment in diff["removed"]:
        locale, screenshot_name = get_locale_and_screenshot_name(fragment)
        print(f"Screenshot only in before: {locale}: {screenshot_name}")
        html_content += f"<p>{locale}: REMOVED {screenshot_name}</br><img src='before/{fragment}'></p></br></br>"

    for fragment in diff["added"]:
        locale, screenshot_name = get_locale_and_screenshot_name(fragment)
        print(f"Screenshot only in after: {locale}: {screenshot_name}")
        html_content += f"<p>{locale}: ADDED {screenshot_name}</br><img src='after/{fragment}'></p></br></br>"

    for fragment in diff["changed"]:
        locale, screenshot_name = get_locale_and_screenshot_name(fragment)
        print(f"Screenshot different: {locale}: {screenshot_name}")
        html_content += f"<p>{locale}: {screenshot_name}</br><img src='before/{fragment}'>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;<img src='after/{fragment}'></p></br></br>"

    if not diff["added"] and not diff["removed"] and not diff["changed"]:
        print("No differences found")
        html_content += "<h1>No differences found</h1>"

    return html_content


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog=__name__)

    parser.add_argument("before_dir", type=str, help="Directory containing screenshots before the incoming changes")
    parser.add_argument("after_dir", type=str, help="Directory containing screenshots after the incoming changes")
    parser.add_argument("output_dir", type=str, help="Directory to save the screenshots diff report")
    parser.add_argument("incoming_changes_ref", type=str, help="Branch name or commit hash that contains the incoming changes")

    parser.add_argument("--repository", default=None, help="owner/name of the repo the PR targets")
    parser.add_argument("--pr-number", type=int, default=None)
    parser.add_argument("--head-sha", default=None)
    parser.add_argument("--base-ref", default=None)
    parser.add_argument("--placeholder-report", default=None,
                        help="path to the placeholder check's JSON output to embed")
    parser.add_argument("--overflow-report", default=None,
                        help="path to the overflow scan's JSON output to embed")
    parser.add_argument("--note", action="append", default=None,
                        help="note to append to the manifest, e.g. why rendering was skipped; repeatable")

    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)

    # `before_dir` includes the branch name we'll be merging into
    baseline_branch = args.before_dir.split(os.path.sep)[-1]

    diff = diff_screenshot_trees(args.before_dir, args.after_dir)
    copy_screenshots(diff, args.before_dir, args.after_dir, args.output_dir)

    notes = list(args.note or [])
    manifest = build_manifest(diff, args, notes)
    with open(os.path.join(args.output_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
        f.write("\n")

    html_content = build_html(diff, baseline_branch, args.incoming_changes_ref)

    script_dir = pathlib.Path(__file__).parent.resolve()
    with open(os.path.join(script_dir, "index.html"), "r") as f:
        html_output = f.read().replace("{{ content }}", html_content)

    with open(os.path.join(args.output_dir, "index.html"), "w") as f:
        f.write(html_output)

    # Also copy the css file; source: https://github.com/picocss/pico
    shutil.copy(os.path.join(script_dir, "pico.min.css"), os.path.join(args.output_dir, "pico.min.css"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
