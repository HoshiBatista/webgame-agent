# GameForge mini-games interface

React + TypeScript + SCSS. The application uses the Django session API described in
[`../docs/api.md`](../docs/api.md); no model credentials are sent to the browser.

```sh
npm ci
npm run dev
npm run lint
npm test
npm run build
```

Development uses Vite on localhost and proxies `/api` to `127.0.0.1:8000`. Production
builds to `dist/`; Django/nginx serves the same root routes `/`, `/chats/:id`, `/games/:id`.
`/play/:revisionId` is an authenticated personal player for opening an immutable revision
in a separate tab. It keeps game execution inside the isolated sandbox, not the app origin.
The signed preview origin must be running separately and allow the configured application
origin in its frame policy. The normal local application address is `http://127.0.0.1:8000/`.

Games use `sandbox="allow-scripts"` without `allow-same-origin`. Fullscreen expands the
existing frame so its game state survives. Rotating signed URLs do not reload an unchanged
artifact. Only one live hover preview is mounted in the feed. Candidate versions are visibly
separate from accepted versions; manual confirmation is explicit, and publication uses a
captured accepted revision.

While a chat has an active queued/generating/checking run, it offers up to three
popular published games using static thumbnails shared with the feed. Links open
the public player in a separate tab with `noopener noreferrer`; the current run,
chat and preview remain in place. The current chat's publications and the original
publication of a remix are excluded. Empty/unavailable recommendations stay hidden.
The feed is fetched once per active run, without model calls or in-chat game frames.
On success, a ready action selects the exact accepted result revision and opens it
in the existing fullscreen preview. Failed or unverified candidates do not get it.

Chats start as «Новая игра», get a short prompt label on the first run, then the
accepted game's title unless manually renamed. The header editor supports save,
cancel/Escape and inline errors; polling does not replace its draft. A title chosen
before the first prompt is sent when the chat is created. Existing chats use
`PATCH /api/chats/:id/`; a confirmed rename updates the sidebar immediately and
invalidates older pending title/list responses. It changes no game or publication.
Apply backend migration `0005_chat_titles` before running this version.

Tests cover CSRF and error transport, no automatic mutation retry, preserved idempotency
after a lost response, candidate/manual-review selection, immutable preview lifecycle,
fullscreen frame identity, history without generation, feed hover/like behavior,
and the waiting-games lifecycle through completion and cancellation.
Component tests use fixtures and do not count as live model evidence. Real browser and model
evidence belongs in the repository's integration report.

Settings include an explicitly labelled synthetic analytics example (three invented touch
metrics). It is not collected player data. An opt-in action adds one editable recommendation
to preferences through the existing API and makes no model request. Genre and implementation
remain the model's choice; the recommendation is context, not a mandatory game template.
