"""Detect which locales a Transifex write-back changes, for the translation bridge.

The bridge runs in the bot fork after Transifex commits translated catalogs to
its write branch. It compares those catalogs against the upstream branch and
reports, per locale, whether the translator-facing content changed. The
comparison ignores .po header metadata (POT-Creation-Date, PO-Revision-Date,
Last-Translator, ...), which Transifex rewrites on every commit, so only real
translation changes are reported, never header churn.

Locales are discovered by scanning l10n/<locale>/LC_MESSAGES/messages.po in both
trees, so a new language needs no configuration. A separate path-shape guard
rejects any changed path that is not a locale catalog or the source .pot; that
guard is the trust boundary against a misconfigured or compromised Transifex.

Run as a script to print the reconcile plan and enforce the guard::

    python l10n/automation/changed_locales.py \
        --head-root . --base-root .l10n-base --changed-paths changed.txt

It prints {"changed": [...], "converged": [...]} to stdout (a one-line summary to
stderr) and exits 2 if any changed path falls outside the allowlist.
"""

import argparse
import json
import os
import re
import sys
from typing import Dict, List, Optional, Tuple

# A locale catalog lives at l10n/<locale>/LC_MESSAGES/messages.po. The source
# catalog l10n/messages.pot may also change (it is the Transifex source mirror).
_CATALOG_RE = re.compile(r"^l10n/([^/]+)/LC_MESSAGES/messages\.po$")
_SOURCE_POT = "l10n/messages.pot"

# Catalog entry key: (msgctxt, singular msgid).
Key = Tuple[Optional[str], str]


def _catalog_path(root: str, locale: str) -> str:
    return os.path.join(root, "l10n", locale, "LC_MESSAGES", "messages.po")


def discover_locales(*roots: str) -> List[str]:
    """Locale names that have a catalog under l10n/*/LC_MESSAGES/messages.po."""
    found = set()
    for root in roots:
        base = os.path.join(root, "l10n")
        if not os.path.isdir(base):
            continue
        for name in os.listdir(base):
            if os.path.isfile(_catalog_path(root, name)):
                found.add(name)
    return sorted(found)


def _load_translations(path: str) -> Optional[Dict[Key, tuple]]:
    """Load a catalog into {(msgctxt, msgid): (forms, fuzzy)}, or None if absent.

    The header (empty msgid) is skipped, so churn in the header dates never
    registers as a change; obsolete entries are not yielded by catalog iteration.
    Babel is imported lazily so this module imports cleanly where Babel is absent.
    """
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        return None

    from babel.messages.pofile import read_po

    with open(path, "rb") as fh:
        catalog = read_po(fh)

    out: Dict[Key, tuple] = {}
    for message in catalog:
        if not message.id:
            continue
        singular = message.id[0] if isinstance(message.id, (list, tuple)) else message.id
        out[(message.context, singular)] = (_forms(message.string), bool(message.fuzzy))
    return out


def _forms(string) -> tuple:
    # message.string is a str (singular) or a tuple of plural forms.
    if isinstance(string, (list, tuple)):
        return tuple(string)
    return (string or "",)


def changed_locales(head_root: str, base_root: str) -> dict:
    """Split all discovered locales into changed vs converged.

    A locale is changed when its head catalog differs from the base catalog by
    translation content (including a catalog appearing or disappearing); it is
    converged when the two carry identical translations.
    """
    changed: List[str] = []
    converged: List[str] = []
    for locale in discover_locales(head_root, base_root):
        head = _load_translations(_catalog_path(head_root, locale))
        base = _load_translations(_catalog_path(base_root, locale))
        (converged if head == base else changed).append(locale)
    return {"changed": changed, "converged": converged}


def assert_allowlisted(paths) -> List[str]:
    """Return the changed paths that are not a locale catalog or the source .pot.

    Any non-empty return value is a guard violation: the caller must refuse to
    act, because something other than a translation file was touched.
    """
    violations = []
    for path in paths:
        p = path.strip()
        if not p or p == _SOURCE_POT or _CATALOG_RE.match(p):
            continue
        violations.append(p)
    return violations


def _read_lines(path: Optional[str]) -> List[str]:
    if not path:
        return []
    with open(path, encoding="utf-8") as fh:
        return [line.strip() for line in fh if line.strip()]


def _parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Detect changed locales for the translation bridge.")
    p.add_argument("--head-root", required=True, help="tree holding the Transifex-written catalogs")
    p.add_argument("--base-root", required=True, help="tree holding the upstream base catalogs")
    p.add_argument("--changed-paths", help="file of changed paths (git diff --name-only) to guard")
    p.add_argument("--format", choices=["json", "lines"], default="json")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = _parse_args(argv)

    violations = assert_allowlisted(_read_lines(args.changed_paths))
    if violations:
        print("Refusing to act: changed paths outside the translation allowlist:", file=sys.stderr)
        for v in violations:
            print(f"  - {v}", file=sys.stderr)
        return 2

    result = changed_locales(args.head_root, args.base_root)
    if args.format == "lines":
        print("\n".join(result["changed"]))
    else:
        print(json.dumps(result))
    print(f"changed: {len(result['changed'])} "
          f"({', '.join(result['changed']) or '-'}); "
          f"converged: {len(result['converged'])}", file=sys.stderr)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
