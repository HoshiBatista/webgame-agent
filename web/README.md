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

Tests cover CSRF and error transport, no automatic mutation retry, preserved idempotency
after a lost response, candidate/manual-review selection, immutable preview lifecycle,
fullscreen frame identity, history without generation, and feed hover/like behavior.
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
