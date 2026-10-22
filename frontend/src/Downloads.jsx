import { useEffect, useState } from 'preact/hooks';
import { api } from './api.js';
import { DownloadRow } from './DownloadRow.jsx';
import { MSG } from './messages.js';

// The last list this session saw, so coming back to the tab shows it at once (UI-SPEC: Polling).
let cachedItems = null;

export function clearDownloadsCache() {
  cachedItems = null;
}

// The Downloads tab. Mounted only while its tab is active.
export function Downloads({ onGoToSearch }) {
  const [items, setItems] = useState(cachedItems);

  useEffect(() => {
    let alive = true;
    api('/api/downloads')
      .then((data) => {
        if (!alive) return;
        cachedItems = data.items;
        setItems(data.items);
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);

  if (items === null) return null;
  return (
    <ul class="downloads">
      {items.map((item) => (
        <DownloadRow key={item.id} item={item} />
      ))}
    </ul>
  );
}
