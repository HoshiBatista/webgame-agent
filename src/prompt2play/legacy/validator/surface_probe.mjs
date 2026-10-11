// Trusted generic surface transport; no game source or arbitrary expressions.
export async function inspectSurface(page, presentationMode = 'canvas') {
  if (!['canvas', 'dom', 'hybrid'].includes(presentationMode)) throw new Error('Unsupported presentation mode');
  const marker = page.locator('[data-testid="game-surface"]');
  const count = await marker.count();
  if (count > 1) throw new Error('Exactly one game surface marker is allowed');
  const native = page.locator('#p2p-surface');
  if (!count && presentationMode !== 'canvas' && await native.count() !== 1) throw new Error('DOM and hybrid games require a visible game-surface marker');
  const locator = count ? marker : presentationMode === 'canvas' ? page.locator('canvas').first() : native;
  if (await locator.count() !== 1 || !(await locator.isVisible())) throw new Error('The game surface must exist and be visible');
  const evidence = await locator.evaluate((node, mode) => {
    const rect = node.getBoundingClientRect();
    const isCanvas = node instanceof HTMLCanvasElement;
    // Playwright's isVisible checks geometry/display/visibility, but deliberately
    // permits opacity:0. A transparent ancestor also hides the playing surface.
    const opacityChainVisible = element => {
      for (let current = element; current; current = current.parentElement || current.getRootNode?.().host || null) {
        const opacity = Number(getComputedStyle(current).opacity);
        if (!Number.isFinite(opacity) || opacity <= 0) return false;
      }
      return true;
    };
    const dimensions = canvas => {
      const bounds = canvas.getBoundingClientRect();
      const style = getComputedStyle(canvas);
      return canvas.width > 0 && canvas.height > 0 && bounds.width > 0 && bounds.height > 0
        && style.display !== 'none' && style.visibility !== 'hidden' && opacityChainVisible(canvas);
    };
    const visibleCanvases = isCanvas ? (dimensions(node) ? 1 : 0)
      : Array.from(node.querySelectorAll('canvas')).filter(dimensions).length;
    return {presentation_mode: mode, tag: node.tagName.toLowerCase(), width: rect.width, height: rect.height,
      visible_canvases: visibleCanvases, canvas_backing_valid: isCanvas ? dimensions(node) : null,
      opacity_chain_visible: opacityChainVisible(node),
      markup_elements: node.querySelectorAll('*').length};
  }, presentationMode);
  if (!(evidence.width > 0 && evidence.height > 0)) throw new Error('The game surface has empty geometry');
  if (!evidence.opacity_chain_visible) throw new Error('The game surface or an ancestor is fully transparent');
  if (presentationMode === 'canvas' && (evidence.tag !== 'canvas' || !evidence.canvas_backing_valid)) {
    throw new Error('Canvas presentation requires the real visible canvas with nonzero backing dimensions');
  }
  if (presentationMode === 'dom' && (evidence.tag === 'canvas' || evidence.markup_elements < 1)) {
    throw new Error('DOM presentation requires rendered markup in an HTMLElement, not a dummy canvas');
  }
  if (presentationMode === 'hybrid' && (evidence.tag === 'canvas' || evidence.visible_canvases < 1
      || evidence.markup_elements <= evidence.visible_canvases)) {
    throw new Error('Hybrid presentation requires a visible canvas and non-canvas markup inside its game surface');
  }
  return {locator, evidence};
}
