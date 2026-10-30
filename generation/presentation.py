"""Versioned Pro art/motion brief; execution evidence remains application-owned."""

from .errors import ContractError

VERSION = 1
PLAN_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "art_direction": {"type": "string", "minLength": 20, "maxLength": 800},
        "motion": {"type": "string", "minLength": 20, "maxLength": 1000},
    },
    "required": ["art_direction", "motion"],
}

PLAN_GUIDANCE = """
PRO ART AND MOTION BRIEF
Treat visual design and animation as part of the finished game. In plan.presentation.art_direction choose a distinctive direction suited to this game's theme: a coordinated palette, readable type hierarchy, character/object silhouettes, scene depth and mobile composition. Describe concrete artwork and layout choices, beyond generic claims like "beautiful" or "polished". Preserve an explicitly requested style.
In plan.presentation.motion describe purposeful motion for this game's key actions and changes of state: for example smooth movement or card flips, collection/impact feedback, revealing progress, and a satisfying ending/replay transition. Choose effects for their role in play; do not apply every example to every game. Describe what the player sees in plain Russian, rather than implementation APIs. Explain the calmer presentation for reduced motion. If the user explicitly requests a static game, respect that and describe the accessible instant feedback instead.
These are implementation intentions, not evidence that artwork or animation exists or has been tested.
"""

IMPLEMENTATION_GUIDANCE = """
PRO VISUAL DESIGN AND MOTION
Realize the saved presentation brief in the actual playable scene. Aim for a finished, visually distinctive mini-game: cohesive palette and typography, expressive characters/objects, deliberate spacing, depth and theme-specific Canvas artwork. Use locally generated shapes, gradients, textures or vector detail where useful. Preserve a requested pixel-art or other style. Make the game world the visual focus; arrange compact headings/HUD/controls around it on phone and desktop, avoiding large unused regions or decorations that crowd the play area. Respect rule-fixed geometry and the player's ability to read threats and targets.
Give real gameplay actions immediate visual feedback and purposeful animation: interpolate drawn movement instead of teleporting between logical cells, animate reveals/collection/impacts when relevant, communicate progression, and stage the ending and replay clearly. Use easing and short, readable transitions; roughly 120-250ms for local feedback and 250-450ms for larger transitions are starting points, not mandatory delays. Match the game's pace. Avoid constant bouncing, excessive particles or camera shake. Animation must support the player's decisions, not obscure them.
Accept input promptly while cosmetic animations run; resolve rules and hit testing from authoritative game state, with a separate presentation state for interpolation. Do not delay controls just to finish an effect, introduce duplicate listeners/timers, reset progress on resize, or let a lingering effect/timer corrupt replay. Support prefers-reduced-motion and explicit requests for less motion with calmer/instant feedback while retaining visible gameplay information. Keep effects bounded, cache reusable artwork and maintain responsive touch controls on mobile and high-DPR screens.
A screenshot is one frame and cannot establish smooth animation. Do not claim visual quality, frame rate or animation correctness from JSON validity, a pixel change or unperformed testing. Preserve real control/outcome checks; cosmetic feedback is not proof of a gameplay effect.
"""

PRESERVATION_GUIDANCE = """
For this limited edit or repair, preserve the established art direction, responsive composition and existing motion unless the user requests a change or they cause the reported defect. Fix the cause locally; do not strip animation, simplify the artwork or replace the visual theme to make a check pass. The visual brief does not authorize unrelated redesign.
"""


def enabled(request):
    # Missing marker belongs to an already frozen pre-policy request/receipt.
    version = request.get("presentation_policy", 0)
    if type(version) is not int or version not in {0, VERSION}:
        raise ContractError("unknown_presentation_policy", "Неизвестная политика оформления Pro.")
    return request.get("generation_strategy") == "pro" and version == VERSION


def implementation_prompt(request):
    if not enabled(request) or request.get("operation", "create") not in {"create", "edit", "repair"}:
        return ""
    text = IMPLEMENTATION_GUIDANCE
    if request.get("generation_profile") == "compact":
        text += "\nUse the supplied update(dt) in seconds and render(ctx) for presentation timing. The compact runtime owns the animation loop; do not add your own loop or resize its Canvas.\n"
    else:
        text += "\nUse requestAnimationFrame timestamps/elapsed seconds for Canvas animation, with bounded dt after a background pause. CSS transitions are appropriate for DOM UI. Keep one scheduler for a running animation and stop cosmetic work when idle; motion speed must not depend on frame count or display refresh rate.\n"
    if request.get("operation") in {"edit", "repair"}:
        text += PRESERVATION_GUIDANCE
    return text
