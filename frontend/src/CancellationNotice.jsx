export default function CancellationNotice({cancellation,onDismiss,role}) {
  if(!cancellation)return null;
  const actor=cancellation.by_you?'You cancelled this ride':cancellation.by==='driver'?(role==='rider'?'Your driver cancelled this ride':'Driver cancelled this ride'):cancellation.by==='rider'?(role==='driver'?'The rider cancelled this ride':'Rider cancelled this ride'):'This ride was cancelled';
  return <section className="cancellation-notice" aria-label="Ride cancellation" role="status"><div className="cancellation-notice-head"><h2>{actor}</h2>{onDismiss && <button type="button" className="text-link" onClick={onDismiss}>Dismiss</button>}</div><p>{cancellation.reason}</p>{cancellation.cancelled_at && <small>{new Date(cancellation.cancelled_at).toLocaleString()}</small>}<p className="cancel-payment-note">No payment or refund was processed by this cancellation.</p></section>;
}
