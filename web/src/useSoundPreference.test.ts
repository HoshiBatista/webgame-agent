import { act, renderHook } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { useSoundPreference } from './useSoundPreference';

afterEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

it('preserves mute on navigation and synchronizes mounted players', () => {
  const first = renderHook(useSoundPreference);
  const second = renderHook(useSoundPreference);
  act(() => first.result.current[1](true));
  expect(second.result.current[0]).toBe(true);
  first.unmount();
  const next = renderHook(useSoundPreference);
  expect(next.result.current[0]).toBe(true);
  act(() => next.result.current[1]((value) => !value));
  expect(second.result.current[0]).toBe(false);
});

it('still mutes when persistent storage is unavailable', () => {
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
    throw new Error('blocked');
  });
  const player = renderHook(useSoundPreference);
  act(() => player.result.current[1](true));
  expect(player.result.current[0]).toBe(true);
});
