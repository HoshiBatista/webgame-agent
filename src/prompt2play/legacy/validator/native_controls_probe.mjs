// A bounded rendered-controls observation, not hostile same-realm attestation.
export async function inspectNativeControls(page) {
  return page.evaluate(() => {
    const selectors = ['#p2p-start', '#p2p-restart', '#p2p-status'];
    const controls = selectors.map(selector => {
      const node = document.querySelector(selector);
      if (!(node instanceof HTMLElement)) return {selector, rendered: false, reason: 'missing'};
      const box = node.getBoundingClientRect();
      const geometry = {width: box.width, height: box.height};
      let opacity = 1, hiddenAncestor = false;
      for (let current = node; current; current = current.parentElement) {
        const style = getComputedStyle(current);
        const value = Number(style.opacity);
        opacity *= Number.isFinite(value) ? value : 1;
        hiddenAncestor ||= style.display === 'none' || ['hidden', 'collapse'].includes(style.visibility) || style.contentVisibility === 'hidden';
      }
      const rendered = node.isConnected && box.width >= 1 && box.height >= 1 && !hiddenAncestor && opacity >= 0.1;
      return {selector, rendered, geometry, effective_opacity: opacity, hidden_ancestor: hiddenAncestor, text: node.textContent?.trim().slice(0, 160) || ''};
    });
    return {rendered: controls.every(control => control.rendered), controls};
  });
}
