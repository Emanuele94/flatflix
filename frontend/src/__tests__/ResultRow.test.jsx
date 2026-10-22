import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/preact';
import { ResultRow } from '../ResultRow.jsx';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const base = {
  result_id: 'r1',
  name: 'Sintel.2010.1080p.BluRay.x264',
  size_human: '4.2 GB',
  seeders: 120,
  leechers: 35,
  source: 'piratebay',
  quality: '1080p',
};

function renderRow(overrides = {}, props = {}) {
  return render(
    <ul>
      <ResultRow result={{ ...base, ...overrides }} onDownload={() => {}} {...props} />
    </ul>,
  );
}

describe('ResultRow layout (D-09)', () => {
  it('shows the full name, size and seeders in the prominent line', () => {
    const { container } = renderRow();
    expect(container.querySelector('.result-name').textContent).toBe(base.name);
    const main = container.querySelector('.result-main');
    expect(main.textContent).toContain('4.2 GB');
    expect(main.textContent).toContain('120 seed');
  });

  it('shows leechers and source small and grey', () => {
    const { container } = renderRow();
    const meta = container.querySelector('.result-meta.muted');
    expect(meta.textContent).toBe('35 downloading · piratebay');
    expect(screen.getByText('35 downloading · piratebay')).toBeTruthy();
  });

  it('shows a quality badge when the quality is known', () => {
    const { container } = renderRow({ quality: '1080p' });
    expect(container.querySelector('.badge').textContent).toBe('1080p');
  });

  it('shows no badge when the quality is null', () => {
    const { container } = renderRow({ quality: null });
    expect(container.querySelector('.badge')).toBeNull();
  });
});

describe('ResultRow encoding (T-01-28)', () => {
  it('renders an HTML-looking name literally and creates no img element', () => {
    const name = '<img src=x onerror=alert(1)>';
    const { container } = renderRow({ name });
    expect(container.querySelector('.result-name').textContent).toBe(name);
    expect(container.querySelector('img')).toBeNull();
  });
});

// Every outcome a row can show, with its exact Italian text (D-10, D-11, D-13).
const TEXT = {
  started: 'Started ✓',
  preparing: 'Preparing',
  rejected: 'This file doesn’t contain a video. Try another result.',
  unavailable: 'Not available. Try another result.',
  duplicate: 'Already added',
  failed: 'Download failed. Try again.',
  expired: 'Search expired. Search again.',
  notReady: 'The service is starting up. Try again in a moment.',
  network: 'Can’t reach the server. Check that the computer is turned on.',
  lost: 'We lost track of this download. Tap Download to check it again.',
};
const NON_STARTED = Object.keys(TEXT).filter((k) => k !== 'started');

describe('ResultRow Download button (DOWN-01, D-10)', () => {
  it('offers an enabled Download button and hands the result to onDownload on tap', () => {
    const onDownload = vi.fn();
    renderRow({}, { onDownload });
    const button = screen.getByRole('button', { name: 'Download' });
    expect(button.disabled).toBe(false);
    fireEvent.click(button);
    expect(onDownload).toHaveBeenCalledTimes(1);
    expect(onDownload).toHaveBeenCalledWith(expect.objectContaining({ result_id: 'r1' }));
  });

  it('disables the button and shows a spinner while the request is pending', () => {
    const onDownload = vi.fn();
    const { container } = renderRow({}, { state: 'pending', onDownload });
    const button = screen.getByRole('button', { name: /Download/ });
    expect(button.disabled).toBe(true);
    expect(container.querySelector('.spinner')).toBeTruthy();
    fireEvent.click(button);
    expect(onDownload).not.toHaveBeenCalled();
  });

  it.each(['started', 'preparing', 'duplicate'])(
    'shows %s as a disabled button and a tap does nothing (idempotency)',
    (state) => {
      const onDownload = vi.fn();
      renderRow({}, { state, onDownload });
      const button = screen.getByRole('button', { name: TEXT[state] });
      expect(button.disabled).toBe(true);
      fireEvent.click(button);
      expect(onDownload).not.toHaveBeenCalled();
    },
  );

  it('shows "Preparing" with a spinner', () => {
    const { container } = renderRow({}, { state: 'preparing' });
    expect(container.querySelector('.spinner')).toBeTruthy();
  });

  it.each(['rejected', 'unavailable', 'failed', 'expired', 'notReady', 'network', 'lost'])(
    'shows the plain Italian message for %s on its own row',
    (state) => {
      const { container } = renderRow({}, { state });
      expect(container.querySelector('.row-state').textContent).toBe(TEXT[state]);
    },
  );

  it.each(['failed', 'notReady', 'network', 'lost'])('lets the user retry after %s', (state) => {
    const onDownload = vi.fn();
    renderRow({}, { state, onDownload });
    const button = screen.getByRole('button', { name: 'Download' });
    expect(button.disabled).toBe(false);
    fireEvent.click(button);
    expect(onDownload).toHaveBeenCalledTimes(1);
  });

  it.each(['rejected', 'unavailable', 'expired'])('does not offer a retry after %s', (state) => {
    const onDownload = vi.fn();
    renderRow({}, { state, onDownload });
    const button = screen.getByRole('button', { name: 'Download' });
    expect(button.disabled).toBe(true);
    fireEvent.click(button);
    expect(onDownload).not.toHaveBeenCalled();
  });

  it('styles ok, warning and error states with classes only', () => {
    expect(renderRow({}, { state: 'rejected' }).container.querySelector('.row-state-warn')).toBeTruthy();
    cleanup();
    expect(renderRow({}, { state: 'failed' }).container.querySelector('.row-state-error')).toBeTruthy();
    cleanup();
    const { container } = renderRow({}, { state: 'started' });
    expect(container.querySelector('.row-state-ok')).toBeTruthy();
    expect(container.querySelector('[style]')).toBeNull();
  });
});

describe('ResultRow never_success prohibition (T-01-45)', () => {
  it.each(NON_STARTED)('never_success: state %s never renders "Started" or a check mark', (state) => {
    const { container } = renderRow({}, { state });
    expect(container.textContent).not.toContain('Started');
    expect(container.textContent).not.toContain('✓');
    expect(container.querySelector('.row-state-ok')).toBeNull();
  });

  it('never_success: a row without any state never says Started', () => {
    const { container } = renderRow();
    expect(container.textContent).not.toContain('Started');
  });
});
