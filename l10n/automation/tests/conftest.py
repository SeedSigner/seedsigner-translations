"""Make the l10n automation modules importable when these tests run.

The translations repo has no main pytest suite; these tests are standalone. Run:

    python -m pytest l10n/automation/tests
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def write_po(path, entries, *, revision="2020-01-01 00:00+0000"):
    """Write a minimal .po at path. entries: list of {id, str?, plural?, plural_str?, ctx?, fuzzy?}.

    `revision` sets the PO-Revision-Date header so tests can vary header metadata
    independently of translation content.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    header = (
        'msgid ""\nmsgstr ""\n'
        '"Content-Type: text/plain; charset=UTF-8\\n"\n'
        f'"PO-Revision-Date: {revision}\\n"\n\n'
    )
    chunks = [header]
    for e in entries:
        block = ""
        if e.get("fuzzy"):
            block += "#, fuzzy\n"
        if e.get("ctx"):
            block += f'msgctxt "{e["ctx"]}"\n'
        block += f'msgid "{e["id"]}"\n'
        if e.get("plural"):
            block += f'msgid_plural "{e["plural"]}"\n'
            block += f'msgstr[0] "{e.get("str", "")}"\n'
            block += f'msgstr[1] "{e.get("plural_str", "")}"\n'
        else:
            block += f'msgstr "{e.get("str", "")}"\n'
        chunks.append(block + "\n")
    path.write_text("".join(chunks), encoding="utf-8")
    return str(path)
