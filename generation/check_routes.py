"""Opt-in scenario guidance; saved requests keep their original prompt contract."""

VERSION = 1


def eligible(request):
    from .lite import eligible as lite_eligible

    return (request.get('generation_profile') == 'full'
            and request.get('operation') in {'create', 'edit', 'repair', 'check_repair'}
            and (request.get('generation_strategy') == 'pro'
                 or (lite_eligible(request) and request.get('lite_policy') == 2)))


def guidance(request):
    if not eligible(request) or request.get('check_routes_policy') != VERSION:
        return ''
    text = TIMING
    if request.get('generation_strategy') == 'lite':
        text += LITE_ROUTES
    return text


TIMING = """
SCENARIO TIME AND ROUTE
An await_condition/await_state is ONE fail-fast condition: if its deadline expires, the scenario stops immediately. Repeating the same 600ms condition eight times does NOT wait 4800ms. Derive the earliest possible event time from YOUR actual speed, distance, spawn delay and required event count. For a setup event taking longer than 3000ms, use an ordinary wait first, then ONE bounded await with margin; total waits remain <=10000ms. For the final goal use one final wait_for, not an intermediate assertion of that goal. Repairing a route must preserve its necessary elapsed time, requested mechanics and expected outcome.
Trace the real state after EACH input. Stop the outcome route at the input that actually causes the outcome: an extra move after victory is ignored, so omitting it proves nothing. There is at most ONE checkpoint, immediately before the decisive input after setup. Do not append another checkpoint to a failed route. Restart setup must first reach the real terminal state, then checkpoint, then replay. Protected checks remain verbatim; source-only repair returns no replacement checks.
"""

LITE_ROUTES = """
LITE PLAYABLE ROUTES
Use real visible element selectors for discrete board controls when available. A Canvas fraction is relative to the WHOLE displayed Canvas, not the inner board: derive the hit position from actual margins, letterboxing, rows and columns. The center of the Canvas may be a gap. Do not guess fractions from the number of cells. Keep Canvas text within its visible bounds by measuring/wrapping text or supplying a maximum width.
When designing a NEW small game and randomness is not requested, prefer an authored first round with repeatable initial positions and spawn sequence; later rounds may vary. This is normal game design, not a test-only seed or success hook. Never silently remove explicitly requested randomness or modify an existing game's rules during check repair. For an already randomized board, a fixed guessed pairing/route is not a valid win scenario: use a genuinely valid route, or report unchanged if the existing observation/actions cannot verify it. Checks must agree with the returned code, including exactly which move wins. Do not assume consecutive card numbers form pairs while the code shuffles them.
On resize preserve ALL active objects in consistent logical coordinates, including falling objects, not only the player. Use a fixed logical world or normalized positions mapped to the actual CSS field; Canvas pixel density is separate. Changing the Canvas dimensions alone can leave an active object off-screen after landscape-to-portrait rotation. Maintain the intended pace in both orientations, without resetting the round or granting score on resize.
Showing or hiding controls can resize a flex/grid Canvas without a window resize event. Synchronize its drawing buffer and input mapping after those layout changes too (for example, observe its container or update layout after changing the controls). A correct center tap does not prove the edges map correctly. Client coordinates minus the element rectangle are already CSS pixels; do not divide them by devicePixelRatio again.
"""
