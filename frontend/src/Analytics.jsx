import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { Download } from 'lucide-react';
import { api } from './api';
import { saveBase64File } from './downloadFile';

// Chart colours: brand green + violet, validated with the dataviz palette checker
// (CVD ΔE ≥ 8 for protan, deutan and tritan; contrast ≥ 3:1 on white).
const SERIES = { primary: 'var(--viz-series-1)', secondary: 'var(--viz-series-2)', neutral: 'var(--viz-neutral)' };
const PRESETS = [['7', 'Last 7 days'], ['30', 'Last 30 days'], ['90', 'Last 90 days'], ['month', 'This month'], ['custom', 'Custom']];

const pad = value => String(value).padStart(2, '0');
const isoDate = day => `${day.getFullYear()}-${pad(day.getMonth() + 1)}-${pad(day.getDate())}`;
const parseDay = value => new Date(`${value}T00:00:00`);
const shortDate = value => parseDay(value).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' });
const longDate = value => parseDay(value).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' });
const inr = (value, digits = 0) => new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: digits, minimumFractionDigits: digits }).format(Number(value));
const compactInr = value => Number(value) >= 1000 ? `₹${new Intl.NumberFormat('en-IN', { notation: 'compact', maximumFractionDigits: 1 }).format(Number(value))}` : `₹${Math.round(Number(value))}`;
const count = value => new Intl.NumberFormat('en-IN').format(value);
const hourLabel = hour => `${pad(hour)}:00`;

function presetRange(preset) {
  const today = new Date();
  if (preset === 'month') return [isoDate(new Date(today.getFullYear(), today.getMonth(), 1)), isoDate(today)];
  const start = new Date(today);
  start.setDate(today.getDate() - (Number(preset) - 1));
  return [isoDate(start), isoDate(today)];
}

function niceTicks(max, target = 4) {
  if (!max || max <= 0) return [0, 1];
  const raw = max / target, power = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 5, 10].map(m => m * power).find(s => s >= raw);
  const ticks = [];
  for (let value = 0; value <= max + step * 0.0001 || ticks.length < 2; value += step) ticks.push(Math.round(value * 1e6) / 1e6);
  if (ticks[ticks.length - 1] < max) ticks.push(ticks[ticks.length - 1] + step);
  return ticks;
}

function useWidth() {
  const ref = useRef(null), [width, setWidth] = useState(640);
  useLayoutEffect(() => {
    if (!ref.current) return undefined;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(280, Math.floor(entry.contentRect.width))));
    observer.observe(ref.current);
    return () => observer.disconnect();
  }, []);
  return [ref, width];
}

// Rounded 4px data-end, square at the baseline.
function columnPath(x, y, width, height) {
  const r = Math.min(4, width / 2, height);
  return `M${x},${y + height}V${y + r}Q${x},${y} ${x + r},${y}H${x + width - r}Q${x + width},${y} ${x + width},${y + r}V${y + height}Z`;
}
function barPath(x, y, width, height) {
  const r = Math.min(4, height / 2, width);
  return `M${x},${y}H${x + width - r}Q${x + width},${y} ${x + width},${y + r}V${y + height - r}Q${x + width},${y + height} ${x + width - r},${y + height}H${x}Z`;
}

function Tooltip({ tip }) {
  if (!tip) return null;
  return <div className="viz-tooltip" style={{ left: tip.x, top: tip.y }} role="status">
    <small>{tip.title}</small>
    {tip.rows.map(row => <div key={row.label} className="viz-tooltip-row">{row.color && <span className="viz-line-key" style={{ background: row.color }} />}<strong>{row.value}</strong><span>{row.label}</span></div>)}
  </div>;
}

function ChartCard({ title, subtitle, legend, table, empty, children }) {
  const [showTable, setShowTable] = useState(false);
  return <figure className="journey-card viz-card">
    <div className="viz-card-head"><div><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</div>
      {!empty && <button type="button" className="text-link" onClick={() => setShowTable(value => !value)} aria-pressed={showTable}>{showTable ? 'Show chart' : 'Show table'}</button>}</div>
    {legend && !showTable && !empty && <ul className="viz-legend">{legend.map(item => <li key={item.label}><span className={`viz-swatch ${item.shape || 'rect'}`} style={{ background: item.color }} />{item.label}</li>)}</ul>}
    {empty ? <p className="viz-empty">{empty}</p> : showTable ? <div className="viz-table-wrap"><table className="viz-table"><thead><tr>{table.columns.map(column => <th key={column}>{column}</th>)}</tr></thead><tbody>{table.rows.map((row, index) => <tr key={index}>{row.map((cell, i) => <td key={i}>{cell}</td>)}</tr>)}</tbody></table></div> : children}
  </figure>;
}

const MARGIN = { top: 16, right: 64, bottom: 28, left: 48 };

function LineChart({ points, series, height = 240, format = count }) {
  const [ref, width] = useWidth(), [hovered, setActive] = useState(null);
  const active = hovered !== null && hovered < points.length ? hovered : null; // the range may shrink under the pointer
  const innerW = width - MARGIN.left - MARGIN.right, innerH = height - MARGIN.top - MARGIN.bottom;
  const ticks = niceTicks(Math.max(...series.flatMap(s => points.map(p => p[s.key]))));
  const top = ticks[ticks.length - 1];
  const x = index => MARGIN.left + (points.length === 1 ? innerW / 2 : (index / (points.length - 1)) * innerW);
  const y = value => MARGIN.top + innerH - (value / top) * innerH;
  const labelEvery = Math.max(1, Math.ceil(points.length / Math.max(2, Math.floor(innerW / 70))));
  function locate(event) {
    const box = event.currentTarget.getBoundingClientRect();
    const ratio = (event.clientX - box.left - MARGIN.left) / innerW;
    setActive(Math.min(points.length - 1, Math.max(0, Math.round(ratio * (points.length - 1)))));
  }
  function keys(event) {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    setActive(current => event.key === 'Home' ? 0 : event.key === 'End' ? points.length - 1 : Math.min(points.length - 1, Math.max(0, (current ?? points.length - 1) + (event.key === 'ArrowRight' ? 1 : -1))));
  }
  const last = points.length - 1;
  const tip = active === null ? null : { x: Math.min(x(active) + 12, width - 180), y: MARGIN.top, title: longDate(points[active].date), rows: series.map(s => ({ label: s.label, value: format(points[active][s.key]), color: s.color })) };
  return <div className="viz-plot" ref={ref}>
    <svg width={width} height={height} tabIndex={0} role="img" aria-label={`${series.map(s => s.label).join(' and ')} per day. Use arrow keys to read each day.`}
      onPointerMove={locate} onPointerLeave={() => setActive(null)} onFocus={() => setActive(last)} onBlur={() => setActive(null)} onKeyDown={keys}>
      {ticks.map(tick => <g key={tick}><line className="viz-grid" x1={MARGIN.left} x2={width - MARGIN.right} y1={y(tick)} y2={y(tick)} /><text className="viz-axis" x={MARGIN.left - 8} y={y(tick)} dy="0.32em" textAnchor="end">{format(tick)}</text></g>)}
      <line className="viz-baseline" x1={MARGIN.left} x2={width - MARGIN.right} y1={y(0)} y2={y(0)} />
      {points.map((point, index) => index % labelEvery === 0 && <text key={point.date} className="viz-axis" x={x(index)} y={height - 8} textAnchor="middle">{shortDate(point.date)}</text>)}
      {active !== null && <line className="viz-crosshair" x1={x(active)} x2={x(active)} y1={MARGIN.top} y2={y(0)} />}
      {series.map(s => <g key={s.key}>
        <path className="viz-line" stroke={s.color} d={points.map((p, i) => `${i ? 'L' : 'M'}${x(i)},${y(p[s.key])}`).join('')} />
        <circle className="viz-dot" cx={x(last)} cy={y(points[last][s.key])} r={4} fill={s.color} />
        {active !== null && <circle className="viz-dot" cx={x(active)} cy={y(points[active][s.key])} r={4} fill={s.color} />}
      </g>)}
      {endLabels(series, points[last], y).map(label => <text key={label.key} className="viz-end-label" x={x(last) + 9} y={label.y} dy="0.32em">{format(label.value)} {label.label}</text>)}
      <rect x={MARGIN.left} y={MARGIN.top} width={innerW} height={innerH} fill="transparent" />
    </svg>
    <Tooltip tip={tip} />
  </div>;
}

// Direct end-labels, only when they don't collide; otherwise the legend carries identity.
function endLabels(series, point, y) {
  const labels = series.map(s => ({ key: s.key, label: s.label.toLowerCase(), value: point[s.key], y: y(point[s.key]) })).sort((a, b) => a.y - b.y);
  return labels.every((label, i) => i === 0 || label.y - labels[i - 1].y >= 14) ? labels : [];
}

function ColumnChart({ items, valueKey, label, color = SERIES.primary, height = 220, format = count, axisFormat = format, xLabel, tipTitle, tipExtra }) {
  const [ref, width] = useWidth(), [hovered, setActive] = useState(null);
  const active = hovered !== null && hovered < items.length ? hovered : null;
  const margin = { ...MARGIN, right: 16 };
  const innerW = width - margin.left - margin.right, innerH = height - margin.top - margin.bottom;
  const values = items.map(item => Number(item[valueKey]));
  const ticks = niceTicks(Math.max(...values)), top = ticks[ticks.length - 1];
  const band = innerW / items.length, barWidth = Math.max(1, Math.min(24, band * 0.7, band - 2));
  const y = value => margin.top + innerH - (value / top) * innerH;
  const peak = values.indexOf(Math.max(...values));
  const labelEvery = Math.max(1, Math.ceil(items.length / Math.max(2, Math.floor(innerW / 60))));
  const tip = active === null ? null : { x: Math.min(margin.left + band * active + band / 2 + 12, width - 180), y: margin.top, title: tipTitle(items[active]), rows: [{ label, value: format(values[active]), color }, ...(tipExtra ? tipExtra(items[active]) : [])] };
  return <div className="viz-plot" ref={ref}>
    <svg width={width} height={height} role="img" aria-label={`${label} by ${xLabel}`}>
      {ticks.map(tick => <g key={tick}><line className="viz-grid" x1={margin.left} x2={width - margin.right} y1={y(tick)} y2={y(tick)} /><text className="viz-axis" x={margin.left - 8} y={y(tick)} dy="0.32em" textAnchor="end">{axisFormat(tick)}</text></g>)}
      {items.map((item, index) => {
        const value = values[index], left = margin.left + band * index, barX = left + (band - barWidth) / 2, barH = y(0) - y(value);
        return <g key={index} className={active === index ? 'viz-mark active' : 'viz-mark'}>
          {value > 0 && <path d={columnPath(barX, y(value), barWidth, barH)} fill={color} />}
          {index === peak && value > 0 && <text className="viz-value" x={left + band / 2} y={y(value) - 6} textAnchor="middle">{format(value)}</text>}
          {index % labelEvery === 0 && <text className="viz-axis" x={left + band / 2} y={height - 8} textAnchor="middle">{item.axis}</text>}
          <rect x={left} y={margin.top} width={band} height={innerH} fill="transparent" tabIndex={0} aria-label={`${tipTitle(item)}: ${format(value)}`}
            onPointerEnter={() => setActive(index)} onPointerLeave={() => setActive(null)} onFocus={() => setActive(index)} onBlur={() => setActive(null)} />
        </g>;
      })}
      <line className="viz-baseline" x1={margin.left} x2={width - margin.right} y1={y(0)} y2={y(0)} />
    </svg>
    <Tooltip tip={tip} />
  </div>;
}

function RankedBars({ items }) {
  const [ref, width] = useWidth();
  const sorted = [...items].sort((a, b) => b.rides - a.rides), max = Math.max(1, ...sorted.map(item => item.rides));
  const labelW = 130, valueW = 56, barMax = width - labelW - valueW, row = 34, thickness = 20;
  return <div className="viz-plot" ref={ref}>
    <svg width={width} height={sorted.length * row} role="img" aria-label="Ride outcomes, ranked">
      {sorted.map((item, index) => {
        const w = (item.rides / max) * barMax, top = index * row + (row - thickness) / 2;
        return <g key={item.key}><title>{`${item.label}: ${count(item.rides)}`}</title>
          <text className="viz-category" x={0} y={top + thickness / 2} dy="0.32em">{item.label}</text>
          <line className="viz-baseline" x1={labelW} x2={labelW} y1={top - 4} y2={top + thickness + 4} />
          {item.rides > 0 && <path d={barPath(labelW, top, w, thickness)} fill={SERIES.primary} />}
          <text className="viz-value" x={labelW + w + 8} y={top + thickness / 2} dy="0.32em">{count(item.rides)}</text>
        </g>;
      })}
    </svg>
  </div>;
}

function SegmentedBar({ parts }) {
  const [ref, width] = useWidth(), [hovered, setActive] = useState(null);
  const total = parts.reduce((sum, part) => sum + part.value, 0);
  const shown = parts.filter(part => part.value > 0), gap = 2, usable = width - gap * (shown.length - 1);
  let cursor = 0;
  const blocks = shown.map(part => { const block = { ...part, x: cursor, w: (part.value / total) * usable, share: Math.round((part.value / total) * 100) }; cursor += block.w + gap; return block; });
  const active = hovered !== null && hovered < blocks.length ? hovered : null;
  const tip = active === null ? null : { x: Math.min(blocks[active].x + 8, width - 180), y: 36, title: blocks[active].label, rows: [{ label: `${blocks[active].share}% of completed rides`, value: count(blocks[active].value), color: blocks[active].color }] };
  return <div className="viz-plot" ref={ref}>
    <svg width={width} height={28} role="img" aria-label={blocks.map(block => `${block.label} ${block.share}%`).join(', ')}>
      {blocks.map((block, index) => {
        const label = `${block.share}%`, fits = block.w >= label.length * 7.5 + 16;
        return <g key={block.label} tabIndex={0} onPointerEnter={() => setActive(index)} onPointerLeave={() => setActive(null)} onFocus={() => setActive(index)} onBlur={() => setActive(null)} className={active === index ? 'viz-mark active' : 'viz-mark'}>
          <rect x={block.x} y={0} width={block.w} height={28} rx={4} fill={block.color} />
          {fits && <text className="viz-inside" x={block.x + 8} y={14} dy="0.32em" fill={block.ink}>{label}</text>}
        </g>;
      })}
    </svg>
    <Tooltip tip={tip} />
  </div>;
}

function StatTile({ label, value, change, period }) {
  return <div className="stat viz-stat"><small>{label}</small><strong>{value}</strong>
    {change !== undefined && <span className={`viz-delta ${change === null ? '' : change >= 0 ? 'up' : 'down'}`}>{change === null ? `No data for the previous ${period}` : `${change >= 0 ? '▲' : '▼'} ${Math.abs(change)}% vs previous ${period}`}</span>}
  </div>;
}

export default function Analytics({ token }) {
  const [preset, setPreset] = useState('30'), [[from, to], setRange] = useState(() => presetRange('30'));
  const [draft, setDraft] = useState(() => presetRange('30'));
  const [data, setData] = useState(null), [loading, setLoading] = useState(false), [error, setError] = useState(''), [downloading, setDownloading] = useState(false);
  const query = `from=${from}&to=${to}`;

  useEffect(() => {
    let alive = true;
    setLoading(true); setError('');
    api(`/admin/analytics?${query}`, { token }).then(result => { if (alive) setData(result); }).catch(e => { if (alive) setError(e.message); }).finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [query, token]);

  function choose(value) {
    setPreset(value);
    if (value !== 'custom') { const range = presetRange(value); setRange(range); setDraft(range); }
  }
  function applyCustom(event) {
    event.preventDefault();
    if (draft[0] > draft[1]) { setError('The start date must be on or before the end date.'); return; }
    setRange(draft);
  }
  async function download() {
    setDownloading(true); setError('');
    try {
      saveBase64File(await api(`/admin/analytics/export?${query}`, { token }));
    } catch (e) { setError(e.message); } finally { setDownloading(false); }
  }

  const k = data?.kpis, period = data ? `${data.range.days} day${data.range.days === 1 ? '' : 's'}` : '';
  const noRides = data && k.requested_rides === 0 && k.completed_rides === 0;
  const daily = data?.daily.map(day => ({ ...day, axis: shortDate(day.date) }));
  const hourly = data?.hourly.map(item => ({ ...item, axis: pad(item.hour) }));
  const payments = data?.payments.map(part => ({ label: part.label, value: part.rides, color: part.key === 'CASH' ? SERIES.primary : part.key === 'ONLINE' ? SERIES.secondary : SERIES.neutral, ink: part.key === 'PENDING' ? 'var(--viz-ink)' : '#ffffff' }));
  const paidTotal = data ? data.payments.reduce((sum, part) => sum + part.rides, 0) : 0;

  return <main className="dashboard viz-root">
    <div className="page-heading"><span className="tag"><span />ANALYTICS</span><h1>The numbers behind every ride.</h1><p>Rides, fares, demand and payments for any date range, with an Excel export.</p></div>

    <form className="viz-filters" onSubmit={applyCustom} aria-label="Date range">
      <div className="viz-presets" role="radiogroup" aria-label="Date range presets">
        {PRESETS.map(([value, label]) => <button type="button" role="radio" aria-checked={preset === value} key={value} className={preset === value ? 'selected' : ''} onClick={() => choose(value)}>{label}</button>)}
      </div>
      {preset === 'custom' && <div className="viz-custom">
        <label>From<input type="date" required value={draft[0]} max={draft[1]} onChange={e => setDraft([e.target.value, draft[1]])} /></label>
        <label>To<input type="date" required value={draft[1]} min={draft[0]} onChange={e => setDraft([draft[0], e.target.value])} /></label>
        <button className="button subtle">Apply</button>
      </div>}
      <button type="button" className="button dark viz-download" onClick={download} disabled={downloading || !data}><Download size={16} />{downloading ? 'Preparing…' : 'Download Excel'}</button>
    </form>
    {data && <p className="viz-range">Showing {longDate(data.range.start)} – {longDate(data.range.end)} · {data.range.timezone}</p>}
    {error && <div className="form-error" role="alert">{error}</div>}

    {!data ? (!error && <p>Loading analytics…</p>) : <div className={loading ? 'viz-body refreshing' : 'viz-body'} aria-busy={loading}>
      <div className="viz-kpis">
        <StatTile label="Rides completed" value={count(k.completed_rides)} change={k.completed_change_pct} period={period} />
        <StatTile label="Gross fares" value={inr(k.gross_fares)} change={k.gross_fares_change_pct} period={period} />
        <StatTile label="Company revenue" value={inr(k.company_revenue)} />
        <StatTile label="Rides requested" value={count(k.requested_rides)} change={k.requested_change_pct} period={period} />
        <StatTile label="Average fare" value={k.average_fare ? inr(k.average_fare) : '—'} />
        <StatTile label="Cancellation rate" value={k.cancellation_rate_pct === null ? '—' : `${k.cancellation_rate_pct}%`} />
        <StatTile label="Average driver rating" value={k.average_driver_rating === null ? '—' : `${k.average_driver_rating} ★`} />
        <StatTile label="New riders · new drivers" value={`${count(k.new_riders)} · ${count(k.new_drivers)}`} />
      </div>

      <ChartCard title="Rides per day" subtitle="Requested on the day they were booked; completed on the day the trip ended."
        empty={noRides && 'No rides in this range.'}
        legend={[{ label: 'Completed', color: SERIES.primary, shape: 'line' }, { label: 'Requested', color: SERIES.secondary, shape: 'line' }]}
        table={{ columns: ['Date', 'Requested', 'Completed', 'Cancelled'], rows: data.daily.map(day => [longDate(day.date), count(day.requested), count(day.completed), count(day.cancelled)]) }}>
        <LineChart points={data.daily} series={[{ key: 'completed', label: 'Completed', color: SERIES.primary }, { key: 'requested', label: 'Requested', color: SERIES.secondary }]} />
      </ChartCard>

      <ChartCard title="Gross fares per day" subtitle="Confirmed fares of completed trips, including surge."
        empty={k.completed_rides === 0 && 'No completed trips in this range.'}
        table={{ columns: ['Date', 'Gross fares', 'Company revenue', 'Completed rides'], rows: data.daily.map(day => [longDate(day.date), inr(day.gross_fares, 2), inr(day.company_revenue, 2), count(day.completed)]) }}>
        <ColumnChart items={daily} valueKey="gross_fares" label="Gross fares" format={value => inr(value)} axisFormat={compactInr} xLabel="day"
          tipTitle={item => longDate(item.date)} tipExtra={item => [{ label: 'Company revenue', value: inr(item.company_revenue) }, { label: 'Completed rides', value: count(item.completed) }]} />
      </ChartCard>

      <div className="viz-pair">
        <ChartCard title="Ride requests by hour" subtitle={`When riders book, in ${data.range.timezone} time.`}
          empty={k.requested_rides === 0 && 'No ride requests in this range.'}
          table={{ columns: ['Hour', 'Requests'], rows: data.hourly.map(item => [`${hourLabel(item.hour)}–${pad(item.hour)}:59`, count(item.requests)]) }}>
          <ColumnChart items={hourly} valueKey="requests" label="Ride requests" xLabel="hour of day" tipTitle={item => `${hourLabel(item.hour)}–${pad(item.hour)}:59`} />
        </ChartCard>

        <ChartCard title="Ride outcomes" subtitle="What happened to rides requested in this range."
          empty={k.requested_rides === 0 && 'No ride requests in this range.'}
          table={{ columns: ['Outcome', 'Rides'], rows: data.outcomes.map(item => [item.label, count(item.rides)]) }}>
          <RankedBars items={data.outcomes} />
        </ChartCard>
      </div>

      <ChartCard title="How completed trips were paid" subtitle={`${count(paidTotal)} completed trip${paidTotal === 1 ? '' : 's'}.`}
        empty={paidTotal === 0 && 'No completed trips in this range.'}
        legend={payments?.filter(part => part.value > 0).map(part => ({ label: part.label, color: part.color }))}
        table={{ columns: ['Payment', 'Trips', 'Share'], rows: data.payments.map(part => [part.label, count(part.rides), paidTotal ? `${Math.round(part.rides / paidTotal * 100)}%` : '—']) }}>
        <SegmentedBar parts={payments} />
      </ChartCard>
    </div>}
  </main>;
}
