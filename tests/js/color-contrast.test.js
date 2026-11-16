import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const tokens = readFileSync(new URL('../../src/shop/static/shop/css/tokens.css', import.meta.url), 'utf8');
const lightTheme = tokens.match(/:root \{([\s\S]*?)\n\}/)?.[1];
const darkTheme = tokens.match(/html\[data-theme="dark"\] \{([\s\S]*?)\n\}/)?.[1];

function color(theme, token) {
  const value = theme?.match(new RegExp(`--${token}:\\s*(#[0-9a-f]{6})`, 'i'))?.[1];
  assert.ok(value, `Expected --${token} to be a hex color.`);
  return value;
}

function luminance(hex) {
  const channels = [1, 3, 5].map((index) => parseInt(hex.slice(index, index + 2), 16) / 255);
  const linear = channels.map((channel) => (
    channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4
  ));
  return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
}

function contrast(first, second) {
  const [lighter, darker] = [luminance(first), luminance(second)].sort((a, b) => b - a);
  return (lighter + 0.05) / (darker + 0.05);
}

function selectedBackground(theme) {
  const rgba = theme?.match(/--accent-soft:\s*rgba\((\d+),\s*(\d+),\s*(\d+),\s*([\d.]+)\)/i);
  assert.ok(rgba, 'Expected --accent-soft to be an rgba color.');
  const base = color(theme, 'bg-primary');
  const alpha = Number(rgba[4]);
  const channels = [1, 3, 5].map((index, channel) => (
    Math.round(Number(rgba[channel + 1]) * alpha + parseInt(base.slice(index, index + 2), 16) * (1 - alpha))
  ));
  return `#${channels.map((channel) => channel.toString(16).padStart(2, '0')).join('')}`;
}

for (const [name, theme] of [['light', lightTheme], ['dark', darkTheme]]) {
  test(`${name} accent text and interactive states meet WCAG contrast`, () => {
    const backgrounds = [
      color(theme, 'bg-primary'),
      color(theme, 'bg-surface'),
      color(theme, 'bg-elevated'),
      color(theme, 'bg-inset'),
      selectedBackground(theme),
    ];
    const accents = ['accent', 'accent-hover', 'accent-active'].map((token) => color(theme, token));
    const buttonText = color(theme, 'on-accent');
    const focus = color(theme, 'focus-ring');

    for (const background of backgrounds) {
      for (const accent of accents) {
        assert.ok(contrast(accent, background) >= 4.5, `${accent} on ${background} is below 4.5:1.`);
        assert.ok(contrast(focus, background) >= 3, `Focus ${focus} on ${background} is below 3:1.`);
      }
    }
    for (const accent of accents) {
      assert.ok(contrast(buttonText, accent) >= 4.5, `${buttonText} on ${accent} is below 4.5:1.`);
    }
  });
}
