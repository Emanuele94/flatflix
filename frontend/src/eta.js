import { MSG } from './messages.js';

const MINUTE = 60;
const HOUR = 3600;

const fill = (template, n) => template.replace('{n}', String(n));

// Rough time left, rounded coarsely so the text does not flicker on every 5 s refresh.
// Returns null when there is nothing sensible to show.
export function formatEta(seconds) {
  if (typeof seconds !== 'number' || !Number.isFinite(seconds) || seconds <= 0) return null;
  if (seconds < MINUTE) return MSG.etaUnderMinute;
  if (seconds < 90 * MINUTE) {
    let n = Math.ceil(seconds / MINUTE);
    if (n >= 10) n = Math.round(n / 5) * 5;
    return fill(MSG.etaMinutes, n);
  }
  if (seconds < 24 * HOUR) return fill(MSG.etaHours, Math.max(2, Math.round(seconds / HOUR)));
  return MSG.etaOverDay;
}
