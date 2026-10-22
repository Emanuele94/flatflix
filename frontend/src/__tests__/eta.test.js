import { describe, expect, it } from 'vitest';
import { formatEta } from '../eta.js';
import { MSG } from '../messages.js';

const minutes = (n) => MSG.etaMinutes.replace('{n}', String(n));
const hours = (n) => MSG.etaHours.replace('{n}', String(n));

describe('formatEta: nothing to show', () => {
  it.each([null, undefined, Number.NaN, Infinity, -Infinity, 0, -5])('gives null for %s', (value) => {
    expect(formatEta(value)).toBeNull();
  });
});

describe('formatEta: wording', () => {
  it.each([1, 59])('says less than a minute for %i s', (s) => {
    expect(formatEta(s)).toBe(MSG.etaUnderMinute);
  });

  it.each([
    [60, 1],
    [61, 2],
    [540, 9],
    [541, 10],
    [1260, 20],
    [1380, 25],
    [5399, 90],
  ])('%i s reads as %i minutes', (s, n) => {
    expect(formatEta(s)).toBe(minutes(n));
  });

  it.each([
    [5400, 2],
    [3 * 3600, 3],
    [86399, 24],
  ])('%i s reads as %i hours', (s, n) => {
    expect(formatEta(s)).toBe(hours(n));
  });

  it('says more than a day from 24 h on', () => {
    expect(formatEta(86400)).toBe(MSG.etaOverDay);
    expect(formatEta(10 * 86400)).toBe(MSG.etaOverDay);
  });
});
