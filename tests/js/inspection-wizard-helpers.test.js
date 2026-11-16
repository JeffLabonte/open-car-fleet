import assert from 'node:assert/strict';
import test from 'node:test';

import {
  buildFleetCarsUrl,
  isSafeCarPk,
} from '../../src/shop/static/shop/js/inspection_wizard_helpers.js';

test('accepts route-safe car primary keys', () => {
  assert.equal(isSafeCarPk('00000000-0000-0000-0000-000000000000'), true);
  assert.equal(isSafeCarPk('12345'), true);
});

test('rejects values that could alter the create-route path', () => {
  for (const value of ['../admin', '1/2', '1?next=/admin', '', 12345, null]) {
    assert.equal(isSafeCarPk(value), false, String(value));
  }
});

test('encodes a fleet primary key as one query parameter', () => {
  const fleetPk = 'fleet&next=//evil.example';
  const url = new URL(buildFleetCarsUrl('/inspection/cars/', fleetPk), 'https://fleet.example');

  assert.equal(url.pathname, '/inspection/cars/');
  assert.deepEqual([...url.searchParams.entries()], [['fleet', fleetPk]]);
});

test('appends the fleet parameter when the endpoint already has a query', () => {
  const url = new URL(buildFleetCarsUrl('/inspection/cars/?format=json', 'fleet-1'), 'https://fleet.example');

  assert.deepEqual([...url.searchParams.entries()], [['format', 'json'], ['fleet', 'fleet-1']]);
});
