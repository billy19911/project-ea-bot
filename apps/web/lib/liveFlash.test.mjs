import test from 'node:test';
import assert from 'node:assert/strict';
import { shouldFlash } from './liveFlash.ts';

test('equal values never flash', () => assert.equal(shouldFlash(10, 10), false));
test('tiny relative change never flashes', () => assert.equal(shouldFlash(100, 100.01), false));
test('sub-threshold relative change never flashes', () => assert.equal(shouldFlash(100, 100.0001), false));
test('meaningful relative change flashes', () => assert.equal(shouldFlash(100, 100.5), true));
test('change just above threshold flashes', () => assert.equal(shouldFlash(100, 100.06, 0.0005), true));
test('non-finite prev never flashes', () => assert.equal(shouldFlash(NaN, 1), false));
test('non-finite next never flashes', () => assert.equal(shouldFlash(1, Infinity), false));
test('zero base uses fallback so tiny absolute move is ignored', () =>
  assert.equal(shouldFlash(0, 0.0001), false));
test('zero base with meaningful absolute move flashes', () =>
  assert.equal(shouldFlash(0, 1), true));
