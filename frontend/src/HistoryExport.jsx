import { useState } from 'react';
import { Download } from 'lucide-react';
import { api } from './api';
import { saveBase64File } from './downloadFile';

const pad = value => String(value).padStart(2, '0');
const isoDate = day => `${day.getFullYear()}-${pad(day.getMonth() + 1)}-${pad(day.getDate())}`;
function lastDays(days) {
  const end = new Date(), start = new Date();
  start.setDate(end.getDate() - (days - 1));
  return [isoDate(start), isoDate(end)];
}

// "Download ride history" bar for rider history, driver trip history and admin rides.
export default function HistoryExport({ token, role }) {
  const [[from, to], setRange] = useState(() => lastDays(90));
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [message, setMessage] = useState('');
  async function download(event) {
    event.preventDefault();
    if (from > to) { setError('The start date must be on or before the end date.'); return; }
    setBusy(true); setError(''); setMessage('');
    try {
      const file = await api(`/ride-history/export?from=${from}&to=${to}`, { token });
      saveBase64File(file);
      setMessage(file.rides ? `Downloaded ${file.rides} ride${file.rides === 1 ? '' : 's'}.` : 'No rides in this range. The file is empty.');
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  const what = role === 'admin' ? 'all rides' : role === 'driver' ? 'your trips and earnings' : 'your rides';
  return <form className="history-export" onSubmit={download} aria-label="Download ride history">
    <div><strong>Download ride history</strong><small>Excel sheet of {what} requested in this date range.</small></div>
    <label>From<input type="date" required value={from} max={to} onChange={e => setRange([e.target.value, to])} /></label>
    <label>To<input type="date" required value={to} min={from} onChange={e => setRange([from, e.target.value])} /></label>
    <button className="button dark" disabled={busy}><Download size={16} />{busy ? 'Preparing…' : 'Download Excel'}</button>
    {error && <p className="form-error" role="alert">{error}</p>}
    {message && <p className="history-export-note" role="status">{message}</p>}
  </form>;
}
