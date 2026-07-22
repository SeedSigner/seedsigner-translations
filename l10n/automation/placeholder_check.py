"""Check that translations preserve their source string's format placeholders.

SeedSigner source strings use Python str.format fields ({} and {name}). A
translation that renames a field, or adds one, crashes at runtime when the
code calls .format on it (KeyError/IndexError); one that drops a field
"works" but silently loses the substituted value. Both mean the translation
is broken, so this check is meant to block a translation PR rather than
advise.

For every catalog entry whose msgid contains at least one format field, each
non-empty translated form must carry a compatible signature:

* the number of automatic positional fields ({}) must match, and
* the set of named fields ({name}) must match.

Plural entries compare each msgstr[i] against the singular and the plural
msgid: a form is fine if it matches either, since which grammatical numbers
each form covers varies by language. Entries whose msgid has no format fields
are skipped entirely; braces a translator adds to plain text can never crash
because the code never calls .format on those strings.

Fuzzy entries are checked like any other: they are compiled whenever
--use-fuzzy is in play, so a broken placeholder in a fuzzy entry still
crashes. Issues carry a "fuzzy" flag so consumers can present them separately.

Run as a script to check catalogs and print a JSON report::

    python l10n/automation/placeholder_check.py --root . --locale de

It prints {"issues": [...], "checked_locales": [...], "counts": ...} to stdout
(a one-line summary to stderr) and exits 1 if any issue was found.
"""

import argparse
import json
import os
import string
import sys
from typing import Dict, List, Optional, Tuple

# Placeholder signature: (count of automatic {} fields, set of named fields).
Signature = Tuple[int, frozenset]


def extract_signature(text: str) -> Optional[Signature]:
    """Return the format-field signature of ``text``, or None if it does not
    parse as a format string (e.g. a stray unmatched brace).

    {{ and }} are literal braces and contribute no field. A field with an
    empty name is an automatic positional ({}); anything else (including
    explicit indexes like {0}) counts as named, matched by exact name.
    """
    positional = 0
    named = set()
    try:
        for _literal, field_name, _spec, _conversion in string.Formatter().parse(text):
            if field_name is None:
                continue
            if field_name == "":
                positional += 1
            else:
                named.add(field_name)
    except ValueError:
        return None
    return (positional, frozenset(named))


def _signature_fields(sig: Signature) -> List[str]:
    """Render a signature as a sorted list of field strings, for reporting."""
    positional, named = sig
    return ["{}"] * positional + [f"{{{name}}}" for name in sorted(named)]


def _forms(message) -> List[Tuple[str, str]]:
    """The translated forms of a Babel message as (label, text) pairs."""
    if isinstance(message.string, (list, tuple)):
        return [(f"msgstr[{i}]", form) for i, form in enumerate(message.string)]
    return [("msgstr", message.string or "")]


def check_catalog(path: str, locale: str) -> List[dict]:
    """Check one .po file; returns a list of issue dicts (empty when clean)."""
    from babel.messages.pofile import read_po

    with open(path, "rb") as fh:
        catalog = read_po(fh)

    issues = []
    for message in catalog:
        if not message.id:
            # The header message has an empty id; skip it.
            continue

        if isinstance(message.id, (list, tuple)):
            singular = message.id[0]
            sources = [form for form in message.id if form]
        else:
            singular = message.id
            sources = [message.id]

        # Signatures the source side offers. Entries whose msgid has no format
        # fields are not format strings; skip them.
        source_sigs = [extract_signature(source) for source in sources]
        if any(sig is None for sig in source_sigs):
            # The source itself does not parse; nothing sane to compare against.
            continue
        if all(sig == (0, frozenset()) for sig in source_sigs):
            continue

        for label, form in _forms(message):
            if not form:
                # Untranslated; nothing to check.
                continue
            form_sig = extract_signature(form)
            if form_sig is None:
                issues.append({
                    "locale": locale,
                    "msgctxt": message.context,
                    "msgid": singular,
                    "form": label,
                    "problem": "malformed",
                    "expected": _signature_fields(source_sigs[0]),
                    "found": None,
                    "fuzzy": bool(message.fuzzy),
                })
            elif form_sig not in source_sigs:
                issues.append({
                    "locale": locale,
                    "msgctxt": message.context,
                    "msgid": singular,
                    "form": label,
                    "problem": "mismatch",
                    "expected": _signature_fields(source_sigs[0]),
                    "found": _signature_fields(form_sig),
                    "fuzzy": bool(message.fuzzy),
                })

    return issues


def _catalog_path(root: str, locale: str) -> str:
    return os.path.join(root, "l10n", locale, "LC_MESSAGES", "messages.po")


def discover_locales(root: str) -> List[str]:
    """Locale names that have a catalog under l10n/*/LC_MESSAGES/messages.po."""
    base = os.path.join(root, "l10n")
    if not os.path.isdir(base):
        return []
    return sorted(name for name in os.listdir(base)
                  if os.path.isfile(_catalog_path(root, name)))


def check_locales(root: str, locales: Optional[List[str]] = None) -> Dict:
    """Check the given locales (default: all discovered) under ``root``."""
    if not locales:
        locales = discover_locales(root)

    issues = []
    checked = []
    for locale in locales:
        path = _catalog_path(root, locale)
        if not os.path.isfile(path):
            continue
        issues.extend(check_catalog(path, locale))
        checked.append(locale)

    return {
        "issues": issues,
        "checked_locales": checked,
        "counts": {
            "issues": len(issues),
            "locales_with_issues": len({issue["locale"] for issue in issues}),
        },
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Check that translations preserve format placeholders.")
    parser.add_argument("--root", default=".",
                        help="repo root containing l10n/ (default: cwd)")
    parser.add_argument("--locale", action="append", default=None,
                        help="locale to check; repeatable (default: all)")
    args = parser.parse_args(argv)

    report = check_locales(args.root, args.locale)

    payload = json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True)
    # Write through the binary buffer: translated strings are non-ASCII and the
    # runner's stdout encoding must not matter. The buffer is absent when
    # stdout is substituted (captured in tests); the text layer handles it then.
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is None:
        sys.stdout.write(payload + "\n")
    else:
        buffer.write((payload + "\n").encode("utf-8"))
        buffer.flush()

    counts = report["counts"]
    print(f"placeholder check: {counts['issues']} issue(s) across "
          f"{counts['locales_with_issues']} locale(s), "
          f"{len(report['checked_locales'])} checked", file=sys.stderr)
    return 1 if report["issues"] else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
