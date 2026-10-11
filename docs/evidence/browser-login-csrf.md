# Browser login correction — 2026-10-12

The root studio attempted to read a CSRF cookie scoped to `/api/`, so its login
request omitted the header. The user's existing in-app browser also sent two
cookies named `csrftoken`; Django selected a malformed 13-character value.
The second defect remained reproducible after fixing token delivery.

Session and login responses now return a masked CSRF token. The client refreshes
it before login/logout and remembers the rotated token returned after login.
Cookies retain their `/api/` scope and now use application-specific names:
`prompt2play_csrftoken` and `prompt2play_sessionid`. Existing sessions require a
new login after this change. CSRF protection remains enabled.

Rejected login requests emit `csrf_rejected` with a bounded reason category,
cookie/header presence, cookie length and duplicate count, including with
`DEBUG=0`. No cookie values, tokens, credentials or raw headers are logged.

## Verification

- Actual in-app browser against the running PostgreSQL/Gunicorn studio: login
  succeeded, reloading preserved the session, logout succeeded, and a second
  login returned to the project workspace. Existing conflicting cookies were
  retained throughout the check. No game generation was launched.
- Active Python suite: 187 passed, 21 environment-dependent tests skipped;
  core branch coverage 90.05%. Skips cover PostgreSQL-specific checks in this
  SQLite test run and opt-in isolated browser checks, unrelated to this patch.
- Targeted active auth regression and adopted login regression: 2 passed.
  Tests reject absent/old CSRF tokens and accept a protected mutation after
  rotation; the separate audit test verifies safe duplicate-cookie diagnostics.
- Frontend: 57 tests passed; TypeScript/Vite production build passed.
- Ruff formatting/lint and strict Mypy passed (117 source files).

An exploratory run of the entire historical adopted `forge/tests/test_api.py`
returned 33 passed and 13 failed. Those failures exercise superseded direct
completion/checkpoint contracts and old module paths; this file is outside the
configured active `tests/` suite. Its targeted login regression passes. The
historical suite was not described as a passing release check or rewritten as
part of this login fix.

This verifies studio authentication, not generated-game quality or compatibility
with the still-unspecified contest WebView.
