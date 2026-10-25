# beeGame mini-games interface

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
Guest sign-in lives at `/login`; both landing-page actions open it. Successful sign-in
returns to the requested private page, or to the feed for a direct visit. The sign-in
page stays light, keeps its dotted background at every width, and has no footer.
Pixel illustrations hide at 760px and below; the logo is centered at 480px and below.
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
Apply backend migration `0011_chat_titles` before running this version.
The studio preview collapses with a 600ms width transition and a staggered opacity fade, keeping the same
game frame mounted. The centered conversation has a continuous surface without side borders.
At 760px and below, the phone mockup is hidden. A rotating chevron in the chat header
opens a collapsed action bar with version selection, fullscreen, HTML copying/download,
sharing, rating and chat deletion. Fullscreen opens the existing frame directly.
The action bar expands over 480ms; hidden actions are inert and excluded from accessibility.
Reduced-motion preferences disable panel transitions.

Tests cover CSRF and error transport, no automatic mutation retry, preserved idempotency
after a lost response, candidate/manual-review selection, immutable preview lifecycle,
fullscreen frame identity, history without generation, feed hover/like behavior,
and the waiting-games lifecycle through completion and cancellation.
Component tests use fixtures and do not count as live model evidence. Real browser and model
evidence belongs in the repository's integration report.

Typography uses **Manrope Variable**, bundled by Vite from the pinned
`@fontsource-variable/manrope` dependency. The browser loads the required language subsets
from this application; no font CDN is contacted. This is the Google Fonts OFL release,
with its copyright and license shipped at [`public/licenses/manrope-OFL.txt`](public/licenses/manrope-OFL.txt).
The interface has a 14px minimum for secondary copy and 16px body/chat/input text, using
`--text-small` and `--text-body` in `src/styles.scss`. Responsive rules preserve the minimum;
larger browser text preferences scale the rem values upward. Generated game artifacts
have their own isolated styling.

The public-facing name is **beeGame**. The primary accent is Beeline yellow `#ffc800`;
dark mode uses graphite `#191c22`, while the light background stays `#f7f5ef`.
Illustration colors are independent of the UI palette. Internal event names and the
theme storage key keep their existing `gameforge` names so saved preferences still work.
Theme colors are registered with `@property` and transition together over
`--duration-theme: 600ms`. The same transition applies to system theme changes;
`prefers-reduced-motion: reduce` disables transitions and their delays.
The logo and tab icon use the unmodified SVG supplied by the user from
[Beeline's asset server](https://static.beeline.ru/upload/images/b2c/bee-logo/beeline_logo.svg).
It lives at `public/assets/beeline-logo.svg`, which Vite copies into the `/assets/`
directory served by Django. The landing footer and login card identify beeGame as
a hackathon development, not an official Beeline product. This notice does not establish
permission to use the trademark; that depends on the event's terms or the rights holder.

Settings include an explicitly labelled synthetic analytics example (three invented touch
metrics). It is not collected player data. An opt-in action adds one editable recommendation
to preferences through the existing API and makes no model request. Genre and implementation
remain the model's choice; the recommendation is context, not a mandatory game template.
