"""Optional scene utilities pinned by experiments that use the full source format."""

from pathlib import Path

# This namespace has always been reserved for app-owned files in the full format.
PATH = 'gf-assets/scene-v1.js'
SOURCE = Path(__file__).parent / 'runtime' / 'scene-v1.js'

GUIDANCE = """
For scrolling worlds or fitted touch controls you may use GameForgeScene v1.
Load <script src="gf-assets/scene-v1.js"></script> before game.js; the app supplies the bytes.
Use a full-page <main data-gf-scene> with direct children: optional [data-gf-hud],
<canvas data-gf-field>, optional <nav data-gf-controls> containing your controls.
The grid reserves separate space for controls and the mute tool, switching to a side
rail on short landscape screens. Set body margin:0. Style your game; leave field padding,
borders and object-fit at their defaults. Size the canvas backing store for its displayed
size and pixel density. For a following camera, compute a view at draw time:
const v = GameForgeScene.view(canvas, {worldWidth, worldHeight, x: hero.x, y: hero.y, zoom: 1});
A hidden/zero-size canvas returns null. zoom is CSS pixels per world unit. v.apply(ctx)
sets the complete world-to-backing-pixel transform. Keep v for hit testing: v.point(event)
maps pointer clientX/clientY to world {x,y} or null outside the visible world. Recompute
and redraw after resize. Camera/layout never change game state, rules or input bindings.
"""


def existing_game_guidance(request):
    if (request.get('operation') in {'edit', 'repair'} and PATH in request.get('helper_catalog', {})
            and PATH in (request.get('files') or {})):
        return GUIDANCE
    return ''
