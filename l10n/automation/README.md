# l10n translations bridge

Automates the translation half of the localization workflow: bringing translations
from Transifex into this repository as reviewable, per-locale pull requests, without
the manual `tx pull` steps described in the top-level README.

This covers the `.po` (translation) stream. The source `messages.pot` stream is
handled by the main repo's automation, which mirrors the source catalog into the bot
fork for Transifex to read.

## Components

| File | Role |
| --- | --- |
| `changed_locales.py` | Compares the Transifex-written catalogs against the upstream branch and reports which locales changed, ignoring `.po` header churn; also exposes the path-shape guard. |

Workflow in `.github/workflows/`:

| Workflow | Trigger | Role |
| --- | --- | --- |
| `l10n-translations-bridge.yml` | `push` to the Transifex write branch | Runs in the bot fork: guards the change, detects changed locales, opens or updates one rolling PR per locale into upstream, and closes converged ones. Operator setup: `SETUP.md`. |

## How it works

Transifex commits translated catalogs to the bot fork's write branch in direct-commit
mode. On each such push the bridge:

1. **Guards the change.** Only `l10n/<locale>/LC_MESSAGES/messages.po` and
   `l10n/messages.pot` may differ from upstream; any other path aborts the run before
   any token is minted. This is the trust boundary against a misconfigured or
   compromised Transifex integration.
2. **Detects changed locales.** It compares catalog content, not bytes, so the header
   dates Transifex rewrites on every commit never register as a change. Locales are
   discovered by scanning, so new languages need no configuration.
3. **Reconciles per locale.** For each changed locale it builds a rolling branch from
   the upstream base with only that locale's catalog overlaid (a clean single-file
   diff) and opens or updates one PR. Locales whose translations have converged with
   upstream have their rolling PR closed and branch removed.

Trust and isolation:

- Branch writes use a token scoped to `contents: write` on the bot fork only; PRs use
  a separate token scoped to `pull-requests: write` on upstream only. Upstream is
  never granted `contents: write`, and the tokens are minted only when there is work
  to do: a changed locale to publish, or an existing rolling branch to reconcile.
- The bridge triggers only on the write branch and pushes only to
  `automation/translations/<locale>` branches, so it can never retrigger itself.
- Reconciliation is stateless: each run compares the current catalogs against
  upstream, so reruns and out-of-order Transifex commits converge to the same set of
  PRs with no duplicates.

## Running the tests

These tests are standalone (this repo has no main test suite). Run them explicitly:

```bash
python -m pip install Babel
python -m pytest l10n/automation/tests -q
```
