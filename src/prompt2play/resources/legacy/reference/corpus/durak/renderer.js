/* The original card game renders DOM/SVG. The adapter owns its actual
 * surface and calls the reviewed render implementation bound by mountGame.
 * It does not invent a hidden Canvas or a parallel render state. */
class GameRenderer {
  constructor(surface){if(!surface||typeof surface.querySelector!=='function')throw new TypeError('A DOM surface is required');this.surface=surface;this.callback=null;this.disposed=false;}
  bind(callback){this.callback=callback;return this;}
  draw(){if(!this.disposed&&this.callback)this.callback();}
  dispose(){this.disposed=true;this.callback=null;}
}
