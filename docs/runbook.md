# Installation, operation and demonstration

## Development installation

Use the README setup sequence. Pin the Python interpreter explicitly if several
Python environments are installed: `uv sync --locked --all-groups --python 3.13`.
Keep `.venv` stable while parallel checks run; `uv run` may recreate it when a
different interpreter is selected.

Build `web/dist` before `uv build`. Wheels and source distributions include the
built studio, all required prompts, reviewed runtime versions and validator
sources. A wheel installation can serve from any working directory; data is
created under `.prompt2play`, or the configured data directory.

`prompt2play doctor` prints tool availability and credential presence, never
credential values. `setup` generates the local signing secret and administrator.
Codex authentication remains on each generation worker. API credentials are
worker environment variables and never sent to the coordinator or candidate.

## Configuration

The CLI reads `.prompt2play/.env` as literal `NAME=value` entries. It does not
execute shell substitutions. Environment variables take precedence. Keep the
file private; setup creates it with permission 0600.
Workers, evaluation, backup and restore use this same configuration as the
studio, including its database selection. Worker credentials stay local.
Setup preserves existing configuration and creates a signing key if none is
configured. If the file redirects `PROMPT2PLAY_DATA_DIR`, it still stores that
key in the originally discovered configuration file. A supplied nonempty process
signing key takes precedence; an explicitly empty process key must be unset.

| Variable | Purpose |
| --- | --- |
| `PROMPT2PLAY_DATA_DIR` | Database/local data root; default `.prompt2play` |
| `PROMPT2PLAY_ARTIFACT_ROOT` | Immutable CAS store; default `<data>/artifacts` |
| `DJANGO_SECRET_KEY` | Signing/session secret; required outside debug mode |
| `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` | PostgreSQL connection components |
| `DATABASE_URL` | Optional database URL; takes precedence over DB components |
| `DJANGO_DB_PATH` | Explicit local SQLite file |
| `PROMPT2PLAY_WEB_DIST` | Override built studio location |
| `PROMPT2PLAY_APP_ORIGIN` | Trusted studio origin; local default port 8000 |
| `PROMPT2PLAY_PREVIEW_ORIGIN` | Separate preview origin; local default port 8001 |
| `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS` | Deployment host/origin policy |
| `OPENAI_API_KEY`, `OPENAI_MODEL` | Credentials/model for an API generation worker |
| `CODEX_MODEL` | Optional local Codex adapter default |
| `PROMPT2PLAY_RUNNER_TOKEN` | Role-scoped worker credential |

Set PostgreSQL components before `setup`. Use a dedicated database and user;
the automated tests create their own test database and must never target a
production database. SQLite is suitable for a local demonstration with one
generator; concurrency acceptance is measured on PostgreSQL.

## Workers and validation

Create both runner roles in the studio settings. Only a team administrator may
authorize a validator. Revoking a runner stops its next authenticated operation.
Tokens are shown once and should be supplied through an environment variable.

```bash
prompt2play worker --role generator --provider codex --model YOUR_AVAILABLE_MODEL --codex /path/to/codex
prompt2play worker --role generator --provider openai --model YOUR_AVAILABLE_MODEL
prompt2play worker --role validator --image prompt2play-validator:local
```

Use one provider command per desired generation worker. `--once` processes one
stage for diagnostics. `--deadline`, `--call-timeout`, `--poll` and validator
`--validation-timeout` configure bounds. Jobs carry the run-wide token budget and
allow at most two additional semantic candidates. Codex has no portable enforced
output-token cap in the adopted CLI adapter: its reservation target, actual usage
and uncertain spend are recorded distinctly; a timeout is still enforced.
Reservations admit new calls using an estimate; an already running call can report
more tokens than reserved. Actual receipts remain accounted, and further calls
stop when headroom is exhausted. The configured budget is not a guaranteed
provider billing cap.

For legacy four-module candidates, pass the validation worker `--acceptance`
with a trusted JSON map from project UUID to real-input scenario, or a `default`
scenario. Supported steps are bounded key/click/tap/drag/wait declarations, never
executable JavaScript. The native profile fixes lifecycle controls and the
terminal `/phase` oracle independently of model-suggested outcome conditions.
Declared control mappings are guidance; actual state/render changes, terminal
outcome and restart must occur in the isolated browser.

The validator executes the exact HTML in Docker with no network, read-only root,
no capabilities, an unprivileged user, and CPU/memory/PID/time limits. It persists
desktop/mobile screenshots, console/network logs and traces. Missing runtime,
missing evidence or required skipped checks means `unverified`; failed checks
cannot enable normal preview or download.
An upgraded validator does not retroactively certify stored versions: their
reports retain the recorded suite/image. Current release evidence must separately
bind the exact preserved HTML to the upgraded checks, without rewriting the
historical report or counting revalidation as fresh generation.

## Recovery and backups

The coordinator owns stage transitions. A generator reserves model calls before
invoking the provider and can only submit a candidate. The validator separately
claims committed candidates and reports evidence. Each stage has a fresh lease
and fence; a released lease must not be reused.

```bash
prompt2play manage recover
prompt2play backup /path/to/private/new-backup
prompt2play restore /path/to/private/new-backup --data-dir /path/to/empty-restored-data
```

`recover` finalizes pending CAS commits without replaying model calls and cannot
resume a cancelled run. Completed invocation responses can be reused under their
recorded identity. Uncertain invocations are not automatically repeated. A late
known response after lease loss may update accounting only; it cannot save model
output, create a candidate or promote a version.

Backups include a consistent database snapshot and referenced immutable/pending
objects, with a checksum inventory. They contain private team metadata and
credential hashes; store them privately. Local environment files and provider
credentials are excluded. Verification rejects missing/changed bytes, symlinks,
unexpected files and traversal. Restore requires an empty data directory.

For PostgreSQL, ensure `pg_dump` and `pg_restore` for the installed server are on
PATH. Configure an **empty dedicated destination database**, then add
`--postgresql` to restore. Existing populated PostgreSQL databases are rejected.
Restore the deployment signing secret separately, then run `manage recover`.
Do not remove old CAS objects by file age: candidates, provider responses and
evidence may reference them. There is no destructive automatic retention job.

## Shared deployment

`serve` is a local development launcher. For shared use run the studio WSGI
application and preview application as separate services behind HTTPS, with
different origins and isolated cookie scopes. Preview settings expose only
scoped preview routes and no session or API middleware. Use
`prompt2play.adapters.django.config.wsgi:application` for the studio, and start
the preview process with `DJANGO_SETTINGS_MODULE=prompt2play.adapters.django.config.preview_settings`.
Set debug off, signing secret, hosts and CSRF origins explicitly. Trust forwarded
headers only when the proxy overwrites them. This remains a trusted-team product;
public hostile multi-tenant execution has not been established.

The preview has an opaque sandbox origin, so browser persistence is unavailable
there; the studio and runtime show that condition. Games must remain playable
and must not claim that a denied write saved progress. Storage in downloaded HTML
depends on its actual browser/WebView host and needs that host's acceptance test.

Preview query tokens are bearer capabilities. Django's server/request handlers
and exception reports mask their values while retaining request paths, status
codes and diagnostics. Exception reports sanitize GET data, query metadata and
traceback text without changing the actual request.
Configure **every proxy and Gunicorn access log to omit query strings** as well;
the Django filter cannot sanitize a separate process's access log. For Gunicorn,
use `--access-logformat '%(h)s %(m)s %(U)s %(H)s %(s)s %(b)s'` (path `U`, without
request-line `r` or query `q`). For Nginx, log `$request_method $uri
$server_protocol` and status, rather than `$request` or `$request_uri`. Do not log
authorization headers or cookies. Verify the deployed log pipeline with a
temporary preview capability before sharing the installation.

## Diagnostic records

The database retains each user request, stage events, attempt/fence identities,
model reservations and actual usage. Completed structured provider responses are
kept in private content-addressed storage. Submitted source, plans, specifications,
failed candidates and browser reports remain immutable. Browser evidence includes
screenshots, console/network records and traces of the automated validation run;
it is not a recording of the user's subsequent manual play session.

Workers emit one JSON record per line for startup, stage start/completion/failure,
model reservation/receipt and idle connection recovery. Records include timestamps,
job/stage/fence identifiers, model and duration. Failures retain a bounded exception
message, schema coordinates where available, and file/function/line frames. They
exclude traceback locals, suppressed rejected response data, raw provider event
streams and hidden reasoning. Known environment credentials, lease tokens and
credential-shaped strings are redacted. Redirect worker output into private
files (`0600` in a `0700` directory) and retain them alongside the database/store.
Do not publish these operational records without reviewing their contents.

A temporary connection failure while waiting for a claim retries with bounded
backoff. Revoked credentials stop the worker. A claim retry does not replay a
model call, candidate submission or interrupted stage. Actual in-flight invocation
reconciliation continues to follow the recovery rules above.

The local user-test instance is configured under `.prompt2play/user-testing/`.
Its `running.json` records listener/worker process IDs, private log paths and the
source hashes at launch. Login information is in its private `Вход.txt`. This
local configuration, credentials, database and logs are excluded from Git.

## Reproducible evaluation and demo

```bash
prompt2play evaluate --model YOUR_AVAILABLE_MODEL --mode single_author --output /path/to/new-evaluation
prompt2play evaluate --model YOUR_AVAILABLE_MODEL --mode four_author --output /path/to/another-new-evaluation
```

The fixed suite contains five small mechanics, two fresh generations each,
bounded repair, and one meaningful revision for the first successful base per
case. Freeze the suite, provider/model, runtime and budgets before comparison.
Keep all failed attempts in the denominator. Completed evidence is immutable;
changed settings require a new evaluation directory. Recorded response reuse is
marked resumed and does not count as a new live generation. Reports leave human
rubric review and real WebView acceptance explicit.

Demonstrate a fresh prompt, stage progress, validated game, actual input/outcome,
restart and exact HTML download. Then make a meaningful revision. A failed edit
must leave the previous playable preview selected; its source/report remains
inspectable. Saved examples must be labelled saved, with their model, runtime,
artifact digest and validation scope. Demonstrate unavailable-validator behavior
without calling its result ready.

The contest WebView is unknown (confirmed 2026-10-11). Once named, test offline
load, real touch/drag, viewport/focus, pause/resume, restart and applicable audio
and storage on that actual host. Synthetic visibility events and touch emulation
are automated evidence with narrower scope.
