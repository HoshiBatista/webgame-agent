# Trusted runtime v1

`runtime-v1.js` supplies lifecycle, scoped input, resize and a test bridge. Clock,
audio and storage are optional capabilities selected by the validated `GameSpec`.
Generated `game.js` defines `createGame(ctx)` and owns mechanics, rendering,
sound choices and save semantics. A DOM game does not acquire a clock because
an arcade game uses one.

The trusted packager calculates a digest over both runtime files and embeds those
exact bytes plus `game.js` and optional `style.css` into standalone HTML. Model
file operations cannot write the runtime. Changing its digest requires a new
candidate; already committed HTML remains unchanged.

The lifecycle bridge exposes `reset(seed)`, `snapshot()`, `dispatch(action)`,
`setManualMode(bool)`, `advance(steps)` and diagnostics. Native snapshots use
`phase: ready | playing | won | lost`. Manual mode freezes real-time updates
without suppressing real input, allowing the validator to distinguish interaction
effects from autonomous animation. Save import/export delegates to game-owned
methods only when storage is selected. Input, animation, observers and audio are
disposed with their session, and restart creates a fresh seeded session.

Scoped input may be registered on a detached Element of the current document
before it is appended. An event is delivered only while that exact target is
currently inside the game surface and its session is active. Connected external
or foreign-document targets are rejected. Document/window keyboard helpers also
require focus within the game. Session cleanup removes every scoped listener.
Runtime v1.0.4 introduced this contract; its exact bundle remains archived so
existing candidate bytes and reports can be reproduced.

Runtime v1.0.5 preserves native vertical finger scrolling on the DOM surface
with `touch-action: pan-y`. Canvas elements inside the surface use
`touch-action: none` for game gestures. A DOM game that implements dragging must
set `touch-action: none` on each draggable element, leaving its ordinary content
and controls scrollable. Binding an input listener does not disable scrolling
for the entire surface. Mobile qualification includes a raw finger swipe before
locator actions, which otherwise can silently scroll an unreachable control.

`examples/canvas` is a reviewed real-time Canvas fixture; `examples/dom` is a
reviewed turn-based DOM fixture. Their acceptance files are independent fixture
checks. They are regression material, **not fresh model generations** and not
evidence of arbitrary-genre reliability. Both require actual desktop and touch
input to reach their visible outcome. The DOM fixture can additionally exercise
audio/save delegation when explicitly enabled.

The browser validator remains mandatory. Parse-only quick checks inside an
attempt never make a candidate eligible. Generated JavaScript must run only in
the isolated runner or restricted preview; do not evaluate it on the host.
