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
artifact. Only one live hover preview is mounted in the feed. Publishing still captures
an accepted revision; automatic validation and accounting remain server-side. The normal
conversation has no manual-acceptance dialog, diagnostics, budget or duplicate run cards.
A completed answer is a message labelled beeGame Lite/Pro with its duration. While work
is active, elapsed time advances locally every second, starting at submission before HTTP
acknowledgement. The pending prompt reconciles with the saved message without duplication;
stopping is available once the server assigns the run ID. Enter sends, Shift+Enter inserts
a newline, and IME composition never sends prematurely.
An unobtrusive community-feed link opens in another tab without fetching recommendations.

The sidebar lists «Недавние» without a count. Each row reserves space for a vertical-dot
menu (visible on hover/focus, always visible on small/touch screens). Rename and delete
operate without navigating through the row link. Renaming updates the open tab title;
other pages use «beeGame». Automatic labels use 1–3 words, including a saved draft's model
title, while manual names remain protected. The backend keeps ownership and row locks.
Apply existing migrations including `0011_chat_titles` and `0013_merge_titles_and_compact`.

The chat header contains the model selector and desktop preview toggle or mobile fullscreen.
A menu beside the send button contains version selection, fullscreen, copy, audio, download,
restoration, rating and sharing (last). Desktop preview also has its top toolbar and bottom
version/actions bar. Menu actions do not submit the prompt form. Fullscreen and panel
transitions preserve the existing frame. The chat keeps its 800px maximum width in both
preview states, preventing expansion at the start of the 600ms opening transition.
Mobile uses its own viewport-height conversation scroller. Opening/reloading starts at the
bottom, including late font/content layout; reading older messages is respected during polling.
The empty invitation is centered. Reduced-motion preferences disable panel transitions.
The divider belongs to the preview and disappears with it. Audio controls appear in the
desktop preview, fullscreen and composer menu. Hiding the preview or browser tab mutes it
without reloading the game. Managed previews add a trusted audio prelude on the isolated
origin; stored artifacts and offline exports are unchanged. Commands check the parent
origin/window and artifact hash. Web Audio uses a master gain; media elements preserve
their own mute setting. No same-origin permission is added to the sandbox.

Logout replaces private UI with a themed loading screen until the anonymous session and
landing route are ready. Late session/preference responses cannot restore the prior account
or replace its accepted CSRF token. The normal logout response includes the guest session.

Tests cover transport/CSRF, retry identity, cancellation, exact displayed source revision,
immutable preview lifecycle, version/fullscreen actions, sidebar renaming, simple replies,
local timer ticks and preference persistence. Browser evidence additionally covers scroll,
continuous panel widths, logout to the landing and narrow layouts.
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
The landing's steps eyebrow stays above its heading at every width. The footer notice
sits to the right of the logo and wraps below it when the row no longer fits.

Settings have two columns: immediate model/theme choices on the left, wishes with their own
Save button on the right. They stack on narrow screens. Expenses and synthetic
analytics are omitted from the interface. Audience choices use four local authored SVGs
in `public/assets/audience-*.svg`; the request carries both the selected ID and concrete
instructions for pace, readability, difficulty and controls. No model call is made for a
setting change. The small landing illustration uses container units below 440px so its
text, pixel art and decorations scale together.
