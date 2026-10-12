// Real touchscreen transport. Locator auto-scrolling is not reachability proof.
export async function swipeDocument(page, direction = 'down') {
  const point = await page.evaluate(direction => {
    const root = document.querySelector('#p2p-surface') || document.querySelector('[data-testid="game-surface"]') || document.body;
    let fallback = null, buttonFallback = null;
    for (const ratioY of [0.75, 0.55, 0.35]) for (const ratioX of [0.5, 0.9, 0.1]) {
      const x = innerWidth * ratioX, y = innerHeight * ratioY, node = document.elementFromPoint(x, y);
      if (!(node instanceof Element) || !root.contains(node) || node.closest('a,input,select,textarea,canvas,svg,[contenteditable="true"]')) continue;
      const button = node.closest('button,[role="button"]');
      let pan = true;
      for (let current = node; current; current = current.parentElement) {
        const action = getComputedStyle(current).touchAction;
        pan &&= action === 'auto' || action === 'manipulation' || /\bpan-y\b/.test(action) || action.includes(direction === 'down' ? 'pan-up' : 'pan-down');
      }
      const candidate = {x, y, to_y: direction === 'down' ? Math.max(30, y - innerHeight * 0.5) : Math.min(innerHeight - 30, y + innerHeight * 0.5), vertical_pan_permitted: pan, element: node.tagName.toLowerCase(), button_fallback: Boolean(button)};
      if (button) {if (pan) buttonFallback ||= candidate; continue;}
      if (pan) return candidate;
      fallback ||= candidate;
    }
    return buttonFallback || fallback;
  }, direction);
  const before = await page.evaluate(() => ({position: scrollY, height: document.documentElement.scrollHeight, viewport: innerHeight}));
  if (!point) return {actual_touch: false, reason: 'No visible noninteractive game region for a vertical gesture', before, after: before};
  const session = await page.context().newCDPSession(page);
  try {
    await session.send('Input.dispatchTouchEvent', {type: 'touchStart', touchPoints: [{x: point.x, y: point.y}]});
    for (let index = 1; index <= 10; index++) {
      await session.send('Input.dispatchTouchEvent', {type: 'touchMove', touchPoints: [{x: point.x, y: point.y + (point.to_y-point.y)*index/10}]});
      await page.waitForTimeout(15);
    }
    await session.send('Input.dispatchTouchEvent', {type: 'touchEnd', touchPoints: []});
    await page.waitForTimeout(500);
  } finally {await session.detach();}
  const after = await page.evaluate(() => ({position: scrollY, height: document.documentElement.scrollHeight, viewport: innerHeight}));
  return {actual_touch: true, point, before, after, scroll_changed: Math.abs(after.position - before.position) >= 2};
}
export async function tapReachable(page, selector) {
  const swipes = [];
  const fail = message => {
    const error = new Error(message);
    error.touch_scroll = {selector, swipes, real_touch_attempted: swipes.some(swipe => swipe.actual_touch)};
    throw error;
  };
  for (let attempt = 0; attempt < 8; attempt++) {
    const box = await page.locator(selector).boundingBox();
    if (!box || box.width <= 0 || box.height <= 0) throw new Error('Touch target has no rendered geometry');
    const viewport = page.viewportSize();
    const center = {x: box.x+box.width/2, y: box.y+box.height/2};
    if (center.x >= 0 && center.x < viewport.width && center.y >= 4 && center.y < viewport.height-4) {
      const hit = await page.locator(selector).evaluate((element, point) => {
        const node = document.elementFromPoint(point.x, point.y);
        return {target: {tag: element.tagName, id: element.id, disabled: Boolean(element.disabled)},
          hit: node ? {tag: node.tagName, id: node.id, text: (node.textContent || '').slice(0, 160)} : null,
          target_hit: node === element || element.contains(node), scroll: {x: scrollX, y: scrollY}};
      }, center);
      // Coordinates are already in the viewport: no locator auto-scroll.
      await page.touchscreen.tap(center.x, center.y);
      return {selector, swipes, box, point: center, ...hit, actual_touch: true};
    }
    if (center.x < 0 || center.x >= viewport.width) throw new Error('Touch target is outside the horizontal viewport');
    const swipe = await swipeDocument(page, center.y >= viewport.height ? 'down' : 'up');
    swipes.push(swipe);
    const moved = await page.locator(selector).boundingBox();
    if (!swipe.actual_touch || !moved || Math.abs(moved.y - box.y) < 2) fail('A real swipe could not reach the offscreen touch control');
  }
  fail('Touch target remains outside the viewport after bounded real swipes');
}
