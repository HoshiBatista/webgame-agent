import test from 'node:test';
import assert from 'node:assert/strict';
import { createPreviewDocument, PREVIEW_CSP, PREVIEW_SANDBOX } from '../src/lib/preview.ts';

test('untrusted scripts and markup follow the first restrictive CSP meta', () => {
  const input = '<script>window.started = true</script><html><head><meta http-equiv="Content-Security-Policy" content="default-src *"></head><body>game</body></html>';
  const output = createPreviewDocument(input);
  assert(output.startsWith('<!doctype html><meta http-equiv="Content-Security-Policy"'));
  assert(output.indexOf('connect-src') < output.indexOf('<script>'));
  assert(output.endsWith(input), 'Source must be preserved exactly, not regex-rewritten');
  assert.equal(PREVIEW_SANDBOX, 'allow-scripts');
  assert(!PREVIEW_SANDBOX.includes('allow-same-origin'));
  assert(!PREVIEW_SANDBOX.includes('allow-forms'));
  assert(!PREVIEW_SANDBOX.includes('allow-popups'));
  assert(!PREVIEW_SANDBOX.includes('allow-top-navigation'));
});

test('preview permits inline game code and local assets but no external subresources', () => {
  for (const directive of ["default-src 'none'", "connect-src 'none'", "frame-src 'none'", "worker-src 'none'", "object-src 'none'", "base-uri 'none'", "form-action 'none'"]) assert(PREVIEW_CSP.includes(directive));
  assert(PREVIEW_CSP.includes("script-src 'unsafe-inline'"));
  assert(PREVIEW_CSP.includes("style-src 'unsafe-inline'"));
  assert(PREVIEW_CSP.includes('img-src data: blob:'));
  assert(!PREVIEW_CSP.includes('unsafe-eval'));
  assert(!PREVIEW_CSP.includes('https:'));
});

test('HTML-looking JavaScript strings and closing tags remain unchanged', () => {
  const html = '<!DOCTYPE html><script>const sample = `<base href="/"><meta http-equiv="refresh" content="5">`; document.body.textContent=sample;</script>';
  assert(createPreviewDocument(html).endsWith(html));
});

import { previewUrl } from '../src/lib/preview.ts';
test('preview only executes eligible separately served token URLs', () => {
  const version = {eligible: true, preview_url: 'http://127.0.0.1:8001/preview/version-id/?token=scoped'};
  assert.equal(previewUrl(version, 'http://127.0.0.1:8000'), version.preview_url);
  for (const invalid of [
    {...version, eligible: false}, {...version, eligible: undefined},
    {...version, preview_url: null}, {...version, preview_url: 'http://127.0.0.1:8000/preview/x/?token=y'},
    {...version, preview_url: 'javascript:alert(1)'}, {...version, preview_url: 'data:text/html,game'},
    {...version, preview_url: 'http://user:secret@preview.example/preview/x/?token=y'},
    {...version, preview_url: 'http://preview.example/preview/x/'},
    {...version, preview_url: 'http://preview.example/other/?token=y'},
  ]) assert.equal(previewUrl(invalid, 'http://127.0.0.1:8000'), null);
  assert.equal(previewUrl(version, 'https://studio.example'), null, 'No mixed content preview');
});
