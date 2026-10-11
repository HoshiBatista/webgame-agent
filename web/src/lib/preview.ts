// Defense in depth for a credential-free, opaque-origin iframe. This policy
// blocks subresource requests; it is not a substitute for the worker container.
// navigate-to is included defensively, but is not implemented by every browser.
export const PREVIEW_SANDBOX = 'allow-scripts';

/** Execution requires an eligible revision and a separately served scoped URL.
 * Never fall back to executing diagnostic HTML from the coordinator response. */
export function previewUrl(version: { eligible?: boolean; preview_url?: string | null }, studioOrigin: string): string | null {
  if (version.eligible !== true || !version.preview_url) return null;
  try {
    const studio = new URL(studioOrigin);
    const preview = new URL(version.preview_url);
    if (!['http:', 'https:'].includes(preview.protocol) || preview.origin === studio.origin || preview.username || preview.password || preview.hash) return null;
    if (studio.protocol === 'https:' && preview.protocol !== 'https:') return null;
    if (!preview.pathname.startsWith('/preview/') || !preview.searchParams.get('token')) return null;
    return preview.href;
  } catch { return null; }
}
export const PREVIEW_CSP = [
  "default-src 'none'", "script-src 'unsafe-inline'", "style-src 'unsafe-inline'",
  'img-src data: blob:', 'media-src data: blob:', 'font-src data: blob:',
  "connect-src 'none'", "frame-src 'none'", "child-src 'none'", "worker-src 'none'",
  "object-src 'none'", "base-uri 'none'", "form-action 'none'", "manifest-src 'none'",
  "navigate-to 'none'",
].join('; ');

export function createPreviewDocument(html: string): string {
  // Prefix the policy before *all* supplied markup: even a script before the
  // source document's <head> must be parsed after our first CSP meta element.
  // Preserve the actual generated source, including JavaScript string literals.
  // The browser ignores a redundant source doctype after the prefix.
  return `<!doctype html><meta http-equiv="Content-Security-Policy" content="${PREVIEW_CSP}"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">${html}`;
}
