import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen } from '@testing-library/preact';
import { DownloadRow } from '../DownloadRow.jsx';
import { MSG } from '../messages.js';

afterEach(cleanup);

const base = {
  id: 'a'.repeat(16),
  name: 'Sintel.2010.1080p',
  type: 'film',
  state: 'downloading',
  progress: 42,
  eta_seconds: 1260,
  action: 'cancel',
};

function renderRow(overrides = {}, props = {}) {
  return render(
    <ul>
      <DownloadRow item={{ ...base, ...overrides }} {...props} />
    </ul>,
  );
}

describe('states with a bar', () => {
  it('preparing: spinner, indeterminate bar, no percent', () => {
    const { container } = renderRow({ state: 'preparing', progress: 0, eta_seconds: null });
    expect(container.querySelector('.download-state').textContent).toContain(MSG.preparing);
    expect(container.querySelector('.spinner')).not.toBeNull();
    const bar = container.querySelector('progress');
    expect(bar).not.toBeNull();
    expect(bar.hasAttribute('value')).toBe(false);
    expect(bar.getAttribute('max')).toBe('100');
    expect(container.textContent).not.toContain('%');
  });

  it('downloading: value, percent text and the ETA', () => {
    const { container } = renderRow();
    expect(container.querySelector('.download-state').textContent).toBe(MSG.stateDownloading);
    const bar = container.querySelector('progress');
    expect(bar.getAttribute('value')).toBe('42');
    expect(bar.getAttribute('aria-label')).toBe(MSG.progressLabel);
    expect(bar.classList.contains('is-downloading')).toBe(true);
    expect(container.querySelector('.download-progress .muted').textContent).toBe('42%');
    expect(container.querySelector('.download-eta').textContent).toBe(
      MSG.etaMinutes.replace('{n}', '20'),
    );
  });

  it('downloading without an ETA shows no ETA element', () => {
    const { container } = renderRow({ eta_seconds: null });
    expect(container.querySelector('.download-eta')).toBeNull();
  });

  it('stalled: state, hint and amber bar, no ETA', () => {
    const { container } = renderRow({ state: 'stalled' });
    expect(container.querySelector('.download-state').textContent).toBe(MSG.stateStalled);
    expect(screen.getByText(MSG.stalledHint)).toBeTruthy();
    expect(container.querySelector('progress').classList.contains('is-stalled')).toBe(true);
    expect(container.querySelector('.download-eta')).toBeNull();
  });

  it('ready: full green bar', () => {
    const { container } = renderRow({ state: 'ready', progress: 100, eta_seconds: null });
    expect(container.querySelector('.download-state').textContent).toBe(MSG.stateReady);
    const bar = container.querySelector('progress');
    expect(bar.getAttribute('value')).toBe('100');
    expect(bar.classList.contains('is-ready')).toBe(true);
    expect(container.querySelector('.download-state').classList.contains('row-state-ok')).toBe(
      true,
    );
  });
});

describe('states without a bar', () => {
  it('problem: state text and message, no bar', () => {
    const { container } = renderRow({ state: 'problem' });
    expect(container.querySelector('.download-state').textContent).toBe(MSG.stateProblem);
    expect(screen.getByText(MSG.problemBody)).toBeTruthy();
    expect(container.querySelector('progress')).toBeNull();
    expect(container.querySelector('.download-state').classList.contains('row-state-error')).toBe(
      true,
    );
  });

  it.each([
    ['rejected', MSG.rejected, 'warn'],
    ['unsupported', MSG.unsupportedFormat, 'warn'],
    ['unavailable', MSG.unavailable, 'warn'],
    ['failed', MSG.downloadFailed, 'error'],
  ])('%s: reuses its Search wording in the %s tone and shows no bar', (state, text, tone) => {
    const { container } = renderRow({ state, progress: 0, eta_seconds: null });
    const el = container.querySelector('.download-state');
    expect(el.textContent).toBe(text);
    expect(el.classList.contains(`row-state-${tone}`)).toBe(true);
    expect(container.querySelector('progress')).toBeNull();
  });
});

describe('partial data and safety', () => {
  it('shows a fallback for a null name', () => {
    const { container } = renderRow({ name: null });
    expect(container.querySelector('.download-name').textContent).toBe(MSG.unnamedDownload);
  });

  it('omits the badge for a null type and names the type otherwise', () => {
    const none = renderRow({ type: null });
    expect(none.container.querySelector('.badge')).toBeNull();
    cleanup();
    const serie = renderRow({ type: 'serie' });
    expect(serie.container.querySelector('.badge').textContent).toBe(MSG.typeSerie);
  });

  it('renders a markup-looking name as literal text', () => {
    const { container } = renderRow({ name: '<b>x</b>' });
    expect(container.querySelector('.download-name').textContent).toBe('<b>x</b>');
    expect(container.querySelector('.download-name b')).toBeNull();
  });

  it('never sets a style attribute (CSP)', () => {
    for (const state of [
      'preparing',
      'downloading',
      'stalled',
      'ready',
      'problem',
      'rejected',
      'unsupported',
      'unavailable',
      'failed',
    ]) {
      const { container } = renderRow({ state }, { stale: true });
      expect(container.querySelectorAll('[style]')).toHaveLength(0);
      cleanup();
    }
  });
});
