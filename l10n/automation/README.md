# l10n automation

Automates the translation half of the localization workflow, in two parts:

- **The translations bridge** brings translations from Transifex into this
  repository as reviewable, per-locale pull requests, without the manual
  `tx pull` steps described in the top-level README.
- **The translation review** checks every translation PR (placeholder
  integrity, text overflow) and publishes what it changes visually: a per-PR
  review page of before/after screenshots plus one sticky status comment.

This covers the `.po` (translation) stream. The source `messages.pot` stream is
handled by the main repo's automation, which mirrors the source catalog into the bot
fork for Transifex to read.

## Components

| File | Role |
| --- | --- |
| `changed_locales.py` | Compares the Transifex-written catalogs against the upstream branch and reports which locales changed, ignoring `.po` header churn; also exposes the path-shape guard. |
| `placeholder_check.py` | Blocking check: every translated form must preserve its source string's `str.format` placeholders. |
| `schema/translation-review-manifest.schema.json` | Contract for the data passed from the untrusted review job to the trusted report job. |
| `validate_review_manifest.py` | Validates a review manifest against the schema and trust anchors before the trusted job acts. |
| `build_review_page.py` | Builds the static per-PR review page from a validated manifest, validating every artifact file it touches. |
| `render_review_comment.py` | Renders the sticky status comment markdown (escapes all untrusted text). |

Workflows in `.github/workflows/`:

| Workflow | Trigger | Role |
| --- | --- | --- |
| `l10n-translations-bridge.yml` | `push` to the Transifex write branch | Runs in the bot fork: guards the change, detects changed locales, opens or updates one rolling PR per locale into upstream, and closes converged ones. Operator setup: `SETUP.md`. |
| `l10n-translation-review.yml` | `pull_request` touching `l10n/**` | Read-only, no secrets. Runs the checks, renders English plus the changed locales at PR base and head with the main repo's screenshot generator (head with the overflow scanner), uploads the diff + manifest artifact. |
| `l10n-translation-review-report.yml` | `workflow_run` (after the review), `pull_request_target` (closed) | Trusted, write. Runs default-branch code, validates the manifest and every artifact file, deploys the per-PR page to the bot fork's `gh-pages`, maintains one status comment, and removes the page when the PR closes. |

## How the bridge works

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

## How the review works

Every PR touching `l10n/**` (from the bridge or a human) gets two runs:

1. `l10n-translation-review.yml` runs in the PR context with a read-only token
   and no secrets, so it can safely execute PR content. It detects which locale
   catalogs the PR changes, runs the checks, renders English plus only those
   locales at the PR base and head with the main repo's screenshot generator,
   and uploads one artifact: the before/after PNGs of every changed screen,
   the overflow composites, and a schema-bound `manifest.json`.
2. `l10n-translation-review-report.yml` runs from default-branch code with
   write access. It never executes PR code and treats the artifact as
   untrusted data: the manifest must pass the JSON Schema and its trust
   anchors (`repository`, `pr.head_sha` against the triggering run), the
   PR-number-to-head-SHA binding is reconfirmed against the live PR, and only
   files the manifest lists are used, each re-checked against a path
   allowlist, PNG magic bytes and a size cap. It then deploys the static
   review page to the bot fork's `gh-pages` under `/pr-<n>/` (a token scoped
   to the fork; this repo never carries `contents: write`) and upserts one
   status comment. When the PR closes, the page directory is removed.

The checks:

- **Placeholder integrity (blocking).** Every translated form must preserve
  its source string's `str.format` fields: same count of positional `{}`
  fields, same set of named `{name}` fields (plural forms may match either the
  singular or the plural source). A renamed or added field crashes at runtime;
  a dropped one silently loses the substituted value. The review run fails
  when this check finds issues, and skips rendering entirely (the broken
  placeholder would crash the renderer), so the comment carries the failure
  detail instead of a render traceback.
- **Text overflow (advisory).** The main repo's overflow scanner inspects the
  rendered screens' component geometry and flags text extending past the
  240px canvas or colliding with buttons, with annotated English-vs-translated
  composites on the review page. Advisory because overflow is a visual
  judgment call with known false positives (untranslated literals, screens
  that already overflow in English).

## Running the tests

These tests are standalone (this repo has no main test suite). Run them explicitly:

```bash
python -m pip install Babel jsonschema
python -m pytest l10n/automation/tests -q
```
