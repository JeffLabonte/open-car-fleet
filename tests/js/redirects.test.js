import assert from 'node:assert/strict';
import test from 'node:test';

import { isSafeRedirectUrl } from '../../src/shop/static/shop/js/redirects.js';

const origin = 'https://fleet.example';

test('accepts same-origin relative paths', () => {
  assert.equal(isSafeRedirectUrl('/cars/?q=van', origin), true);
});

test('rejects empty, non-path, and cross-origin redirects', () => {
  for (const value of ['', 'cars/', '//evil.example/path', '/\\\\evil.example/path']) {
    assert.equal(isSafeRedirectUrl(value, origin), false, value);
  }
});

test('rejects URL schemes including javascript', () => {
  for (const value of ['https://evil.example/path', 'javascript:alert(1)', 'data:text/html,hi']) {
    assert.equal(isSafeRedirectUrl(value, origin), false, value);
  }
});
