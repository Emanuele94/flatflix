import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/preact';
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
  skipped: 0,
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

describe('Cancel download (D-32)', () => {
  const handlers = () => ({
    onAskCancel: vi.fn(),
    onCancel: vi.fn(),
    onKeep: vi.fn(),
    onRemove: vi.fn(),
  });

  it.each(['preparing', 'downloading', 'stalled', 'problem'])(
    '%s row with action cancel shows the Cancel button and no confirm text',
    (state) => {
      const h = handlers();
      renderRow({ state }, h);
      fireEvent.click(screen.getByRole('button', { name: MSG.cancelDownload }));
      expect(h.onAskCancel).toHaveBeenCalledWith(base.id);
      expect(screen.queryByText(MSG.cancelConfirmTitle)).toBeNull();
      expect(h.onCancel).not.toHaveBeenCalled();
    },
  );

  it('the open panel replaces the button in place and focuses "No, keep it"', () => {
    renderRow({}, { ...handlers(), confirming: true });
    expect(screen.getByText(MSG.cancelConfirmTitle)).toBeTruthy();
    expect(screen.getByText(MSG.cancelConfirmBody)).toBeTruthy();
    expect(screen.queryByRole('button', { name: MSG.cancelDownload })).toBeNull();
    expect(screen.getByRole('button', { name: MSG.cancelConfirmYes })).toBeTruthy();
    expect(document.activeElement).toBe(screen.getByRole('button', { name: MSG.cancelConfirmNo }));
  });

  it('is an inline panel, not a dialog', () => {
    const { container } = renderRow({}, { ...handlers(), confirming: true });
    expect(container.querySelector('dialog, [role="dialog"], [aria-modal]')).toBeNull();
  });

  it('"No, keep it" asks the parent to close; closing returns focus to "Cancel download"', () => {
    const h = handlers();
    const view = renderRow({}, { ...h, confirming: true });
    fireEvent.click(screen.getByRole('button', { name: MSG.cancelConfirmNo }));
    expect(h.onKeep).toHaveBeenCalledWith(base.id);
    expect(h.onCancel).not.toHaveBeenCalled();
    view.rerender(
      <ul>
        <DownloadRow item={base} {...h} confirming={false} />
      </ul>,
    );
    expect(document.activeElement).toBe(screen.getByRole('button', { name: MSG.cancelDownload }));
  });

  it('Escape in the panel asks the parent to close', () => {
    const h = handlers();
    renderRow({}, { ...h, confirming: true });
    fireEvent.keyDown(screen.getByRole('button', { name: MSG.cancelConfirmNo }), { key: 'Escape' });
    expect(h.onKeep).toHaveBeenCalledWith(base.id);
  });

  it('"Yes, cancel" calls onCancel with the opaque id', () => {
    const h = handlers();
    renderRow({}, { ...h, confirming: true });
    fireEvent.click(screen.getByRole('button', { name: MSG.cancelConfirmYes }));
    expect(h.onCancel).toHaveBeenCalledWith(base.id);
  });

  it('while cancelling both buttons are disabled and "Cancelling…" shows with a spinner', () => {
    const h = handlers();
    const { container } = renderRow({}, { ...h, confirming: true, busy: 'cancel' });
    const yes = screen.getByRole('button', { name: MSG.cancelling });
    expect(yes.disabled).toBe(true);
    expect(yes.querySelector('.spinner')).not.toBeNull();
    expect(screen.getByRole('button', { name: MSG.cancelConfirmNo }).disabled).toBe(true);
    expect(container.textContent).not.toContain(MSG.cancelConfirmYes);
  });

  it('a ready row (action remove) shows no Cancel button', () => {
    renderRow({ state: 'ready', progress: 100, action: 'remove' }, handlers());
    expect(screen.queryByRole('button', { name: MSG.cancelDownload })).toBeNull();
  });

  it('a failed-job row (action null) has no button at all', () => {
    const { container } = renderRow({ state: 'failed', action: null }, handlers());
    expect(container.querySelector('button')).toBeNull();
  });
});

describe('Remove from list (D-33)', () => {
  const ready = { state: 'ready', progress: 100, eta_seconds: null, action: 'remove' };

  it('shows Remove from list without a confirm and calls onRemove with the id', () => {
    const onRemove = vi.fn();
    renderRow(ready, { onRemove });
    fireEvent.click(screen.getByRole('button', { name: MSG.removeFromList }));
    expect(onRemove).toHaveBeenCalledWith(base.id);
    expect(screen.queryByText(MSG.cancelConfirmTitle)).toBeNull();
    expect(screen.queryByRole('button', { name: MSG.cancelDownload })).toBeNull();
  });

  it('while removing the button is disabled and shows a spinner and "Removing…"', () => {
    renderRow(ready, { busy: 'remove' });
    const button = screen.getByRole('button', { name: MSG.removing });
    expect(button.disabled).toBe(true);
    expect(button.querySelector('.spinner')).not.toBeNull();
  });
});

describe('action failure and outage lock (D-36, D-37)', () => {
  it('failed shows the plain sentence under the Cancel button as a warn status', () => {
    renderRow({}, { failed: true });
    const note = screen.getByText(MSG.actionFailed);
    expect(note.getAttribute('role')).toBe('status');
    expect(note.classList.contains('row-state-warn')).toBe(true);
    const button = screen.getByRole('button', { name: MSG.cancelDownload });
    expect(button.compareDocumentPosition(note) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('failed shows the same sentence under Remove from list', () => {
    renderRow({ state: 'ready', action: 'remove' }, { failed: true });
    expect(screen.getByText(MSG.actionFailed).getAttribute('role')).toBe('status');
  });

  it('no sentence when nothing failed', () => {
    renderRow({}, {});
    expect(screen.queryByText(MSG.actionFailed)).toBeNull();
  });

  it('stale disables Cancel, Remove and both confirm buttons', () => {
    renderRow({}, { stale: true });
    expect(screen.getByRole('button', { name: MSG.cancelDownload }).disabled).toBe(true);
    cleanup();
    renderRow({ state: 'ready', action: 'remove' }, { stale: true });
    expect(screen.getByRole('button', { name: MSG.removeFromList }).disabled).toBe(true);
    cleanup();
    renderRow({}, { stale: true, confirming: true });
    expect(screen.getByRole('button', { name: MSG.cancelConfirmYes }).disabled).toBe(true);
    expect(screen.getByRole('button', { name: MSG.cancelConfirmNo }).disabled).toBe(true);
  });
});

describe('safety check states (D-53, D-56, D-61)', () => {
  const handlers = () => ({
    onAskCancel: vi.fn(),
    onCancel: vi.fn(),
    onKeep: vi.fn(),
    onRemove: vi.fn(),
  });
  const checking = { state: 'checking', progress: 99, eta_seconds: null, action: 'cancel' };
  const checkFailed = { state: 'check_failed', progress: 99, eta_seconds: null, action: null };
  const ready = { state: 'ready', progress: 100, eta_seconds: null, action: 'remove' };

  it('check_failed: warn-tone message as the state text, no bar, no ETA, no button', () => {
    const { container } = renderRow(checkFailed, handlers());
    const el = container.querySelector('.download-state');
    expect(el.textContent).toBe(MSG.checkFailed);
    expect(el.classList.contains('row-state-warn')).toBe(true);
    expect(container.querySelector('progress')).toBeNull();
    expect(container.querySelector('.download-eta')).toBeNull();
    expect(container.querySelector('button')).toBeNull();
  });

  it('checking: spinner, hint, no bar, no percent, no ETA, Cancel download', () => {
    const { container } = renderRow(checking, handlers());
    const el = container.querySelector('.download-state');
    expect(el.textContent).toBe(MSG.stateChecking);
    expect(el.querySelector('.spinner')).not.toBeNull();
    expect(screen.getByText(MSG.checkingHint).classList.contains('muted')).toBe(true);
    expect(container.querySelector('progress')).toBeNull();
    expect(container.textContent).not.toContain('%');
    expect(container.querySelector('.download-eta')).toBeNull();
    expect(screen.getByRole('button', { name: MSG.cancelDownload })).toBeTruthy();
  });

  it('ready with skipped 1 keeps the full green bar and shows the singular note', () => {
    const { container } = renderRow({ ...ready, skipped: 1 });
    const bar = container.querySelector('progress');
    expect(bar.getAttribute('value')).toBe('100');
    expect(bar.classList.contains('is-ready')).toBe(true);
    const note = container.querySelector('p.download-note');
    expect(note.textContent).toBe(MSG.skippedOne);
  });

  it('ready with skipped 3 shows the plural note with the number', () => {
    const { container } = renderRow({ ...ready, skipped: 3 });
    expect(container.querySelector('p.download-note').textContent).toBe(
      MSG.skippedMany.replace('{n}', '3'),
    );
  });

  it('ready with skipped 0, or no skipped at all, shows no note', () => {
    const zero = renderRow({ ...ready, skipped: 0 });
    expect(zero.container.querySelector('.download-note')).toBeNull();
    cleanup();
    const { skipped, ...noSkipped } = base;
    const missing = render(
      <ul>
        <DownloadRow item={{ ...noSkipped, ...ready }} />
      </ul>,
    );
    expect(missing.container.querySelector('.download-note')).toBeNull();
  });

  it('only a ready row shows the note', () => {
    const { container } = renderRow({ ...checking, skipped: 2 });
    expect(container.querySelector('.download-note')).toBeNull();
  });

  it.each([
    ['checking', checking],
    ['check_failed', checkFailed],
  ])('%s with a null name and a null type shows the fallback name and no badge', (_s, over) => {
    const { container } = renderRow({ ...over, name: null, type: null });
    expect(container.querySelector('.download-name').textContent).toBe(MSG.unnamedDownload);
    expect(container.querySelector('.badge')).toBeNull();
  });

  it.each([
    ['checking', checking],
    ['check_failed', checkFailed],
  ])('%s renders a 200-character name with no spaces in full', (_s, over) => {
    const name = 'x'.repeat(200);
    const { container } = renderRow({ ...over, name });
    expect(container.querySelector('.download-name').textContent).toBe(name);
  });

  it('the confirm body of a checking row is the finished-download one', () => {
    renderRow(checking, { ...handlers(), confirming: true });
    expect(screen.getByText(MSG.cancelConfirmBodyDone)).toBeTruthy();
    expect(screen.queryByText(MSG.cancelConfirmBody)).toBeNull();
  });

  it('a problem row keeps its text, hint and cancel action, with the finished-download body', () => {
    const { container } = renderRow({ state: 'problem' }, { ...handlers(), confirming: true });
    expect(container.querySelector('.download-state').textContent).toBe(MSG.stateProblem);
    expect(screen.getByText(MSG.problemBody)).toBeTruthy();
    expect(screen.getByText(MSG.cancelConfirmBodyDone)).toBeTruthy();
  });

  it.each(['preparing', 'downloading', 'stalled'])('%s keeps the partly-downloaded body', (state) => {
    renderRow({ state }, { ...handlers(), confirming: true });
    expect(screen.getByText(MSG.cancelConfirmBody)).toBeTruthy();
    expect(screen.queryByText(MSG.cancelConfirmBodyDone)).toBeNull();
  });

  it('an open panel switches its body when the row moves from downloading to checking', () => {
    const h = handlers();
    const view = renderRow({}, { ...h, confirming: true });
    expect(screen.getByText(MSG.cancelConfirmBody)).toBeTruthy();
    view.rerender(
      <ul>
        <DownloadRow item={{ ...base, ...checking }} {...h} confirming />
      </ul>,
    );
    expect(screen.getByText(MSG.cancelConfirmBodyDone)).toBeTruthy();
    expect(screen.queryByText(MSG.cancelConfirmBody)).toBeNull();
  });

  it.each([
    ['ready', ready],
    ['check_failed', checkFailed],
  ])('an open checking panel closes when the row becomes %s', (_s, next) => {
    const h = handlers();
    const view = renderRow(checking, { ...h, confirming: true });
    expect(screen.getByText(MSG.cancelConfirmTitle)).toBeTruthy();
    view.rerender(
      <ul>
        <DownloadRow item={{ ...base, ...next }} {...h} confirming />
      </ul>,
    );
    expect(screen.queryByText(MSG.cancelConfirmTitle)).toBeNull();
    expect(screen.queryByRole('button', { name: MSG.cancelConfirmYes })).toBeNull();
  });

  it('a state code the frontend does not know shows no chip and still shows the name', () => {
    const { container } = renderRow({ state: 'weird', action: null });
    expect(container.querySelector('.download-state')).toBeNull();
    expect(container.querySelector('.download-name').textContent).toBe(base.name);
  });

  it('no row of the new states sets a style attribute or raw HTML', () => {
    for (const over of [checking, checkFailed, { ...ready, skipped: 2 }]) {
      const { container } = renderRow(over, { stale: true });
      expect(container.querySelectorAll('[style]')).toHaveLength(0);
      cleanup();
    }
  });
});

describe('household copy guard (T-02.1-15)', () => {
  it('no message contains a technical word', () => {
    for (const [key, value] of Object.entries(MSG)) {
      expect(value, key).not.toMatch(/quarantine|sandbox|probe|ffprobe|scan|virus|malware|reject/i);
    }
  });

  it('the existing no-video wording is unchanged', () => {
    expect(MSG.rejected).toBe('This file doesn’t contain a video. Try another result.');
  });
});
