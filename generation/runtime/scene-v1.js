/* Offline, optional layout and camera for games with a scrollable world. */
(() => {
  'use strict';

  const style = document.createElement('style');
  style.textContent = `
    [data-gf-scene] {
      display: grid;
      grid-template: "hud" auto "field" minmax(0, 1fr) "controls" auto / minmax(0, 1fr);
      box-sizing: border-box;
      width: 100%;
      height: 100dvh;
      padding: max(env(safe-area-inset-top), var(--gf-tool-reserve, 0px))
               env(safe-area-inset-right) env(safe-area-inset-bottom) env(safe-area-inset-left);
    }
    [data-gf-scene] > [data-gf-hud] {
      grid-area: hud; min-width: 0; max-height: 24dvh; overflow: auto;
    }
    [data-gf-scene] > canvas[data-gf-field] {
      grid-area: field; display: block; width: 100%; height: 100%;
      min-width: 0; min-height: 0; padding: 0; border: 0;
    }
    [data-gf-scene] > [data-gf-controls] {
      grid-area: controls; display: flex; flex-wrap: wrap; align-content: start;
      min-width: 0; min-height: 0; max-height: 35dvh; overflow: auto; gap: 4px;
    }
    [data-gf-controls] button { min-width: 44px; min-height: 44px; }
    @media (orientation: landscape) and (max-height: 600px) {
      [data-gf-scene] {
        grid-template: "hud hud" auto "field controls" minmax(0, 1fr) / minmax(0, 1fr) auto;
      }
      [data-gf-scene] > [data-gf-controls] { max-width: 32vw; max-height: 100%; }
    }`;
  document.head.appendChild(style);

  function centeredEdge(focus, worldSize, visibleSize) {
    if (worldSize <= visibleSize) return (worldSize - visibleSize) / 2;
    return Math.min(worldSize - visibleSize, Math.max(0, focus - visibleSize / 2));
  }

  function view(canvas, {worldWidth, worldHeight, x, y, zoom = 1}) {
    if (![worldWidth, worldHeight, x, y, zoom].every(Number.isFinite)
        || worldWidth <= 0 || worldHeight <= 0 || zoom <= 0) {
      throw new RangeError('Invalid camera or world dimensions');
    }
    const width = canvas.clientWidth / zoom;
    const height = canvas.clientHeight / zoom;
    if (!width || !height || !canvas.width || !canvas.height) return null;

    const left = centeredEdge(x, worldWidth, width);
    const top = centeredEdge(y, worldHeight, height);
    const scaleX = canvas.width / width;
    const scaleY = canvas.height / height;
    return {
      left, top, width, height,
      apply(ctx) {
        ctx.setTransform(scaleX, 0, 0, scaleY, -left * scaleX, -top * scaleY);
      },
      point({clientX, clientY}) {
        const rect = canvas.getBoundingClientRect();
        if (!(rect.width > 0 && rect.height > 0 && clientX >= rect.left && clientX < rect.right
              && clientY >= rect.top && clientY < rect.bottom)) return null;
        const x = left + (clientX - rect.left) * width / rect.width;
        const y = top + (clientY - rect.top) * height / rect.height;
        return x >= 0 && x < worldWidth && y >= 0 && y < worldHeight ? {x, y} : null;
      },
    };
  }

  window.GameForgeScene = Object.freeze({view});
})();
