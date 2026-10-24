import '@testing-library/jest-dom/vitest';
import type {} from 'vitest/jsdom';
import { afterEach } from 'vitest';
import { cleanup } from '@testing-library/react';
// Use browser Storage even when the Node runtime exposes its own localStorage.
Object.defineProperty(window, 'localStorage', {
  configurable: true,
  value: jsdom.window.localStorage,
});
globalThis.ResizeObserver = class {
  observe() {}
  unobserve() {}
  disconnect() {}
};
afterEach(cleanup);
HTMLDialogElement.prototype.showModal = function () {
  this.open = true;
};
HTMLDialogElement.prototype.close = function () {
  this.open = false;
};
