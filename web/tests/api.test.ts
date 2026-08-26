import { beforeEach, expect, it } from 'vitest';
import { tokenFromFragment } from '../src/api';

beforeEach(() => {
  window.history.replaceState(null, '', '/#token=one-launch-token');
});

it('keeps the launch token only in module memory while clearing the URL and history state', () => {
  expect(tokenFromFragment()).toBe('one-launch-token');
  expect(window.location.hash).toBe('');
  expect(window.history.state?.starklabsSessionToken).toBeUndefined();
  expect(JSON.stringify(window.history.state)).not.toContain('one-launch-token');
  expect(tokenFromFragment()).toBe('one-launch-token');
});
