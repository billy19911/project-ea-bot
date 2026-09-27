import test from 'node:test';
import assert from 'node:assert/strict';
import { nextViewport } from './viewport.ts';

// `nextViewport` decides how the chart window reacts to a data update.
// Inputs:
//   prev:        { key, n, visibleCount, viewEnd }  (window state BEFORE the update)
//   incoming:    { key, n, appendCount }            (dataset AFTER the update)
//     - key         = data identity (e.g. `${symbol}/${timeframe}`)
//     - n           = total bars after the update
//     - appendCount = how many bars were appended at the END (0 when history prepended)
// Returns the next { visibleCount, viewEnd } (clamped to [0, n]).

test('identity change resets to latest window', () => {
  const r = nextViewport(
    { key: 'XAUUSD/H1', n: 100, visibleCount: 40, viewEnd: 50 },
    { key: 'EURUSD/H1', n: 80, appendCount: 0 },
  );
  assert.deepEqual(r, { visibleCount: 80, viewEnd: 80 });
});

test('prepended history shifts the window to keep the same bars on screen', () => {
  // 10 older bars prepended -> indices move forward by 10, no visual jump.
  const r = nextViewport(
    { key: 'XAUUSD/H1', n: 100, visibleCount: 40, viewEnd: 90 },
    { key: 'XAUUSD/H1', n: 110, appendCount: 0 },
  );
  assert.deepEqual(r, { visibleCount: 40, viewEnd: 100 });
});

test('user at right edge follows latest when a bar is appended', () => {
  const r = nextViewport(
    { key: 'XAUUSD/H1', n: 100, visibleCount: 40, viewEnd: 100 },
    { key: 'XAUUSD/H1', n: 101, appendCount: 1 },
  );
  assert.deepEqual(r, { visibleCount: 40, viewEnd: 101 });
});

test('user browsing history keeps position when a bar is appended', () => {
  const r = nextViewport(
    { key: 'XAUUSD/H1', n: 100, visibleCount: 40, viewEnd: 50 },
    { key: 'XAUUSD/H1', n: 101, appendCount: 1 },
  );
  assert.deepEqual(r, { visibleCount: 40, viewEnd: 50 });
});

test('fewer bars than before clamps the window into range', () => {
  const r = nextViewport(
    { key: 'XAUUSD/H1', n: 100, visibleCount: 40, viewEnd: 100 },
    { key: 'XAUUSD/H1', n: 30, appendCount: 0 },
  );
  assert.deepEqual(r, { visibleCount: 30, viewEnd: 30 });
});

test('empty dataset yields an empty window', () => {
  const r = nextViewport(
    { key: 'XAUUSD/H1', n: 100, visibleCount: 40, viewEnd: 100 },
    { key: 'XAUUSD/H1', n: 0, appendCount: 0 },
  );
  assert.deepEqual(r, { visibleCount: 1, viewEnd: 0 });
});
