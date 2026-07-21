"""Render the sticky translation-review PR comment from a validated manifest.

Runs in the trusted report job from default-branch code, but the manifest it
consumes was produced by untrusted PR code, so every source or translated
string is shown inside inline code spans with backticks stripped and newlines
flattened, and never as raw markdown.

The comment is one persistent status block per PR: blocking placeholder
result, advisory overflow result, screenshot-diff counts, and the link to the
visual review page when one was deployed.
"""

import argparse
import html
import json
import sys
from typing import List

COMMENT_MARKER = "<!-- l10n-automation:comment=translation-review -->"

_MAX_TEXT_CHARS = 120
_MAX_LIST_ROWS = 10


def _clean(text) -> str:
    """Make untrusted text safe for an inline code span: flatten newlines,
    strip backticks, bound the length."""
    flat = str(text).replace("\r", " ").replace("\n", " ").replace("`", "'")
    if len(flat) > _MAX_TEXT_CHARS:
        flat = flat[:_MAX_TEXT_CHARS] + "..."
    return flat


def _placeholder_lines(placeholder) -> List[str]:
    if placeholder is None:
        return ["- Placeholder integrity: not run"]

    issues = placeholder["issues"]
    if not issues:
        return ["- Placeholder integrity: **PASS**"]

    lines = [f"- Placeholder integrity: **FAIL** ({len(issues)} issue(s)) - "
             f"a wrong placeholder crashes or silently breaks the rendered text"]
    for issue in issues[:_MAX_LIST_ROWS]:
        found = "does not parse" if issue["found"] is None else " ".join(issue["found"])
        expected = " ".join(issue["expected"])
        lines.append(
            f"  - `{issue['locale']}` `{_clean(issue['msgid'])}` "
            f"({issue['form']}): expected `{_clean(expected)}`, found `{_clean(found)}`")
    if len(issues) > _MAX_LIST_ROWS:
        lines.append(f"  - ...and {len(issues) - _MAX_LIST_ROWS} more (see the review page)")
    return lines


def _overflow_lines(overflow) -> List[str]:
    if overflow is None:
        return ["- Text overflow: not run"]

    total = sum(len(events) for events in overflow.values())
    if total == 0:
        return ["- Text overflow: none detected"]

    per_locale = ", ".join(
        f"{locale}: {len(events)}" for locale, events in sorted(overflow.items()) if events)
    return [f"- Text overflow (advisory): {total} flagged component(s) ({per_locale}) - "
            f"composites on the review page; known false positives exist"]


def render(manifest: dict, page_url: str = "") -> str:
    checks = manifest["checks"]
    counts = manifest["screenshots"]["counts"]

    lines = [COMMENT_MARKER, "## Translation review", ""]
    lines += _placeholder_lines(checks["placeholder"])
    lines += _overflow_lines(checks["overflow"])
    lines.append(
        f"- Screenshots: {counts['changed']} changed, {counts['added']} added, "
        f"{counts['removed']} removed")

    if page_url:
        lines += ["", f"**[Open the visual review page]({page_url})** "
                      f"(before/after screenshots and overflow composites)"]

    for note in manifest.get("notes", []):
        lines += ["", f"> **Note:** {html.escape(_clean(note))}"]

    lines += [
        "",
        "<sub>The placeholder check is blocking; overflow and screenshot "
        "changes are informational. This comment is updated in place on "
        "every push.</sub>",
    ]
    return "\n".join(lines).rstrip() + "\n"


def write_text(text: str, out: str) -> None:
    """Write UTF-8 text to ``out``, or to stdout when ``out`` is ``-``.

    The body embeds translated strings verbatim, so writing to stdout goes
    through its binary buffer: a runner whose stdout encoding is ASCII would
    otherwise raise UnicodeEncodeError on the first non-ASCII string. The
    buffer is absent when stdout is substituted (captured in tests), in which
    case the text layer already handles the encoding.
    """
    if out != "-":
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(text)
        return

    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is None:
        sys.stdout.write(text)
    else:
        buffer.write(text.encode("utf-8"))
        buffer.flush()


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Render the review comment from a manifest.")
    p.add_argument("--manifest", required=True)
    p.add_argument("--page-url", default="")
    p.add_argument("--out", default="-")
    args = p.parse_args(argv)

    with open(args.manifest, encoding="utf-8") as fh:
        manifest = json.load(fh)

    write_text(render(manifest, page_url=args.page_url), args.out)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
