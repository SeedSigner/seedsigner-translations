# l10n automation: operator setup

Two independent pieces, configured in different places:

- **The translations bridge** (`l10n-translations-bridge.yml`) runs in a
  bot-owned fork; all of its configuration lives on the BOT FORK.
- **The translation review** (`l10n-translation-review.yml` and
  `l10n-translation-review-report.yml`) runs in this repository on every
  translation PR; its configuration lives HERE (and stays empty on forks,
  where the report workflow then no-ops).

## Part 1: the translations bridge

`l10n-translations-bridge.yml` brings Transifex translations into this repository
as one pull request per locale. It runs in a bot-owned fork of this repo, never in
this repo itself: it stays inert here because it activates only when
`L10N_TRANSLATIONS_UPSTREAM` is set and a push lands on the Transifex write branch,
neither of which is true upstream.

All configuration in Part 1 therefore lives on the BOT FORK, never on this
repository. Setting these on the upstream repo would make it try to open pull
requests into itself.

## Topology

- `SeedSigner/seedsigner-translations` (this repo): the upstream the bridge opens
  PRs into. The automation never gains write access to it.
- `<bot>/seedsigner-translations`: a real fork (same fork network, required for
  cross-fork PRs) where the bridge runs. Transifex commits translated catalogs here
  in direct-commit mode, on the write branch.

The source `l10n/messages.pot` is mirrored into the bot fork's default branch by the
main repo's automation; Transifex reads its source from there.

Flow: Transifex writes `l10n/<locale>/LC_MESSAGES/messages.po` to the bot fork's
write branch -> the bridge compares it against this repo's base branch -> for each
locale whose translations changed it opens or updates one PR here; locales that have
converged with upstream have their PR closed.

For testing as an external contributor, stand everything up under your own accounts:
your own fork of this repo plays the upstream, and a bot account's fork plays
`<bot>/seedsigner-translations`.

The bot fork inherits this workflow and `changed_locales.py` from upstream once the
bridge is merged here; you do not install them on the fork by hand. Keep the bot
fork's default branch tracking upstream (an occasional fast-forward is enough) so it
carries the current bridge code and translation base. This sync is hygiene, not a
correctness requirement: the bridge always compares against live upstream and builds
each PR from the upstream base, so a lagging fork still produces correct PRs.

## Repository variables (on the bot fork)

Settings -> Secrets and variables -> Actions -> Variables. All three are required.

| Variable | Example | Notes |
| --- | --- | --- |
| `L10N_TRANSLATIONS_UPSTREAM` | `SeedSigner/seedsigner-translations` | The repo PRs are opened into. Empty means the bridge no-ops. |
| `L10N_TRANSLATIONS_BRANCH` | `dev` | The upstream base branch PRs target. |
| `L10N_TRANSLATIONS_WRITE_BRANCH` | `transifex-writes` | The branch Transifex commits to. Must equal the literal `branches:` filter in the workflow's `on.push` (GitHub Actions cannot read variables in `on:`). |

The bot fork itself is not configured anywhere: the workflow derives it from the
repository it runs in. Locales are not configured either; they are discovered by
scanning `l10n/*/LC_MESSAGES/messages.po`, so a new language needs no edits.

## Repository secrets (on the bot fork)

The bridge authenticates as a GitHub App (no long-lived PATs) and mints short-lived,
least-privilege tokens at runtime. Two logical roles:

- Fork role: `contents: write` on the bot fork; pushes the rolling branches.
- PR role: `pull-requests: write` on the upstream repo; opens the PRs.

| Secret | Value |
| --- | --- |
| `L10N_TR_FORK_CLIENT_ID` | Fork App Client ID |
| `L10N_TR_FORK_PRIVATE_KEY` | Fork App private key (`.pem` contents) |
| `L10N_TR_PR_CLIENT_ID` | PR App Client ID |
| `L10N_TR_PR_PRIVATE_KEY` | PR App private key (`.pem` contents) |

### Production: two Apps

Because no upstream repo may ever be granted `contents: write`, production uses two
separate Apps: a PR App carrying only `Pull requests: Read & write` installed on the
upstream repo, and a Fork App carrying only `Contents: Read & write` (plus
`Workflows: Read & write` if the fork can fall behind upstream) installed on the bot
fork. The upstream App never holds `contents` access at all.

### Testing: one App

For a single-maintainer test you may install one App on both stand-in repos, with
`Contents`, `Pull requests`, `Metadata` (and `Workflows`) read/write, and put its
Client ID and key in all four secrets. The workflow still down-scopes each minted
token (the PR token to pull-requests, the fork token to contents), so behavior
matches production; the only relaxation is that the single test App could write more
than it is asked to.

## Transifex

Configure the official Transifex GitHub integration against the bot fork in
direct-commit mode:

- Source: the repo-root `l10n/messages.pot` (mirrored in by the main repo's
  automation). The checked-in `.tx/config` expresses the source path relative to a
  submodule mountpoint; the GitHub integration roots at the repository, so configure
  its source as the repo-root `l10n/messages.pot`.
- Translations: `l10n/<lang>/LC_MESSAGES/messages.po`, with the `zh-Hans ->
  zh_Hans_CN` language map, committed to the write branch.

### Why the write-branch push trigger is safe

The bridge runs on `push` to the write branch with the bot fork's App secrets in
scope, so its safety depends on only trusted code being able to run in that job.
Two assumptions guarantee this, and both should be preserved:

- The official Transifex app is scoped to `Contents`, `Pull requests`, and
  `Metadata`, with no `Workflows` permission, so GitHub rejects any Transifex push
  that adds or edits a file under `.github/workflows/`. A content-level compromise
  of Transifex therefore cannot plant a workflow that reads the App keys.
- The bot fork has no untrusted collaborators. A collaborator with push plus
  workflow scope is the only actor who could add such a step, and anyone able to
  administer the bot account can already read the secrets directly.

If either assumption changes -- Transifex is granted `Workflows` scope, or the bot
fork gains untrusted collaborators -- the push trigger should be reworked into the
read-only-producer / trusted-consumer split the other workflows use.

## First-time PR CI approval

This repo's `pull_request` workflows (`tests.yml` and the review) run on every
PR. The first PR from the bot fork hits GitHub's first-time-contributor gate; a
maintainer approves it once in the Actions tab, after which runs from that fork
proceed automatically.

## Part 2: the translation review

The review pair runs in this repository. The producer
(`l10n-translation-review.yml`) needs no configuration at all: it has no
secrets, and it resolves the main repo as `<this repo's owner>/seedsigner`,
which points at the production repo here and at the matching fork in a test
topology. It does require the overflow scanner to be present on that repo's
`dev` branch.

The report workflow (`l10n-translation-review-report.yml`) publishes each PR's
review page to a bot fork's `gh-pages` branch and maintains the PR comment. It
no-ops until the variable and secrets below are set, so forks of this repo
stay inert.

### Pages fork (one-time)

The per-PR pages are hosted on the bot fork so that this repository never
carries a `contents: write` credential:

1. On the bot fork (`<bot>/seedsigner-translations`), the report workflow
   creates and maintains the `gh-pages` branch by itself; nothing to create by
   hand.
2. After the first deploy, enable Pages on the bot fork: Settings -> Pages ->
   Deploy from a branch -> `gh-pages` / root. Pages served from a public fork
   are public; that is fine, they contain only rendered screenshots of public
   translations.
3. Each PR's page then appears at
   `https://<bot>.github.io/seedsigner-translations/pr-<n>/`.

### Repository variable (on this repo)

| Variable | Example | Notes |
| --- | --- | --- |
| `L10N_PAGES_FORK` | `<bot>/seedsigner-translations` | The fork whose `gh-pages` hosts the review pages. Empty means the report workflow no-ops. |

### Repository secrets (on this repo)

The page deploy authenticates as a GitHub App and mints a short-lived token
scoped to `contents: write` on the Pages fork only. The PR comment needs no
App at all: it uses the workflow's own default token (`pull-requests: write`).

| Secret | Value |
| --- | --- |
| `L10N_PAGES_CLIENT_ID` | Pages App Client ID |
| `L10N_PAGES_PRIVATE_KEY` | Pages App private key (`.pem` contents) |

In production this is its own App carrying only `Contents: Read & write`,
installed on the bot fork only. For testing you may reuse the bridge's Fork
App (it already has `contents: write` on the bot fork) and put its Client ID
and key in these secrets; the minted token is down-scoped either way.

Note the split: the bridge's secrets live on the bot fork (the bridge runs
there); the review's secrets live here (the report workflow runs here). The
two do not share configuration even when they share an App.
