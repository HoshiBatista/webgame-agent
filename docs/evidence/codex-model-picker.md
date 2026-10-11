# Codex model picker — 2026-10-12

Generation runners query the same configured Codex executable and local account
used for game generation. A short-lived stdio app-server session sends only
`initialize`, `initialized` and paginated `model/list` messages, following the
[official app-server protocol](https://learn.chatgpt.com/docs/app-server#list-models-modellist).
No thread or inference turn is created. Credentials remain inside Codex.

The runner reports model IDs, display names and the catalog default flag through
its existing capabilities channel. The studio displays choices from connected,
non-revoked generation runners in both creation and revision settings. The
automatic option names the runner's explicit `--model` default where known;
the catalog's recommended default does not override that setting. Unknown saved
model names remain editable instead of being silently replaced.

Discovery is bounded by a 12-second timeout, four pages, 64 models and bounded
messages. Hidden entries are excluded; subprocesses are reaped on completion or
failure. Refresh occurs between stages every five minutes. Failures clear the
previous catalog, record a non-sensitive reason code and retry after one minute.
The coordinator validates the public metadata and rejects unexpected fields in
model entries. Offline runners do not contribute selectable models.

## Verification

- The actual installed Codex returned seven visible models; the running generator
  reported `model_catalog_status=ready` and `count=7` to the PostgreSQL studio.
- The in-app browser displayed those seven models and the existing generator
  default, GPT-6 Astra. Selecting an explicit model survived page reload. The
  original automatic setting and the user's two-million-token budget were
  preserved when verification finished. No game was submitted.
- Active Python suite: 197 passed, 21 environment-dependent checks skipped
  (PostgreSQL-specific checks in this SQLite test run and opt-in isolated game
  browser checks). Core branch coverage: 90.05%.
- Frontend: 60 tests passed; TypeScript/Vite build passed.
- Ruff formatting/lint and strict Mypy passed (119 source files).

Tests cover read-only handshake/order, pagination, hidden entries, malformed
responses, timeout, safe errors, refresh caching/failure, coordinator metadata
validation, offline/revoked/validator exclusion, deduplication and differing
runner defaults. Worker tests stub discovery rather than reading a real account.

The list is Codex's catalog, which may be cached or bundled depending on provider
configuration. It is not an independent entitlement or successful-inference
check; access is established by an actual successful request. OpenAI API catalog
discovery and multi-account model-aware runner scheduling are outside this patch.
