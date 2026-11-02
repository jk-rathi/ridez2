import { useEffect, useRef, useState } from 'react';
import { useParams } from 'react-router-dom';
import QRCode from 'qrcode';
import { Banknote, Smartphone } from 'lucide-react';
import RatingForm from './Rating';
import { api } from './api';

const warning='TEST PAYMENT — no money transferred';
const money=value=>new Intl.NumberFormat('en-IN',{style:'currency',currency:'INR'}).format(Number(value));

function useTestQr(ride,token) {
  const [result,setResult]=useState(null),[qr,setQr]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState('');
  async function generate() {
    setBusy(true);setError('');
    try {
      const data=await api(`/rides/${ride.id}/test-payment`,{token,method:'POST',body:'{}'});
      const url=new URL(data.path,window.location.origin).href;
      setQr(await QRCode.toDataURL(url,{width:256,margin:4,errorCorrectionLevel:'M'}));setResult({...data,url});
    } catch(e){setError(e.message);} finally{setBusy(false);}
  }
  // The workspace copy is live (pushed on every result); the generate response covers the gap before it arrives.
  return {payment:ride.test_payment || result?.payment,result,qr,busy,error,generate};
}

export function TestPaymentCard({ride,role,token}) {
  const {payment,result,qr,busy,error,generate}=useTestQr(ride,token);
  if(ride.status!=='COMPLETED' || (!ride.test_payments_enabled && !payment) || (ride.payment?.status==='CONFIRMED' && ride.payment.method!=='ONLINE' && !payment))return null;
  return <section className="test-payment"><strong>{warning}</strong><h3>QR payment testing</h3><p>Test status: <b>{payment?.status || 'NOT STARTED'}</b> · {money(payment?.amount || ride.quote.total)}</p>{role==='rider' && ride.test_payments_enabled && payment?.status!=='SUCCESS' && ride.payment?.status!=='CONFIRMED' && <><button className="button dark" onClick={generate} disabled={busy}>{busy?'Generating…':result?'Refresh test QR':'Pay by QR (test)'}</button>{qr && <div className="test-qr"><img src={qr} width="256" height="256" alt="Scan to simulate payment. No money is transferred."/><a href={result.url} target="_blank" rel="noreferrer">Open test payment page</a><p>Scan with your phone camera. Expires after 15 minutes. Choose an outcome on the test page.</p></div>}</>}{payment?.status==='SUCCESS' && <p>Simulation successful. This is not a payment receipt.</p>}{error && <p role="alert" className="form-error">{error}</p>}</section>;
}

export default function TestPaymentPage() {
  const {token}=useParams();
  const [payment,setPayment]=useState(null),[error,setError]=useState(''),[busy,setBusy]=useState(false);
  useEffect(()=>{let active=true;api(`/test-payments/${encodeURIComponent(token)}`).then(data=>{if(active)setPayment(data.payment);}).catch(e=>{if(active)setError(e.message);});return()=>{active=false;};},[token]);
  async function simulate(status) {
    setBusy(true);setError('');
    try{const data=await api(`/test-payments/${encodeURIComponent(token)}`,{method:'POST',body:JSON.stringify({status})});setPayment(data.payment);}catch(e){setError(e.message);}finally{setBusy(false);}
  }
  return <main className="test-payment-page"><section className="journey-card test-payment"><strong>{warning}</strong><h1>Simulate QR payment</h1><p>This page tests ridez.io payment screens. It does not connect to a bank or UPI app.</p>{payment && <><h2>{money(payment.amount)}</h2><p role="status">Test status: <b>{payment.status}</b></p>{payment.status!=='SUCCESS'?<div className="test-payment-actions">{['SUCCESS','FAILED','PENDING'].map(status=><button key={status} className="button dark" disabled={busy} onClick={()=>simulate(status)}>Simulate {status.toLowerCase()}</button>)}</div>:<p>Simulation complete. Further scans keep this successful test result.</p>}</>}{error && <p className="form-error" role="alert">{error}</p>}<p>You can return to the ride workspace to view the updated test status.</p></section></main>;
}

function PaymentSuccess({amount,method}) {
  return <div className="pay-success" role="status"><svg className="pay-success-mark" viewBox="0 0 120 120" aria-hidden="true"><circle className="pay-ring" cx="60" cy="60" r="52"/><circle className="pay-disc" cx="60" cy="60" r="44"/><path className="pay-tick" d="M38 62 L53 77 L84 45"/></svg><h2>{method==='CASH'?'Cash payment confirmed':'Payment successful'}</h2><p className="pay-amount">{money(amount)}</p><p>{method==='CASH'?'Your driver confirmed receiving the cash. ':''}Thanks for riding with ridez.</p></div>;
}

// Opens on the rider's screen when their trip completes; stays until they pay, close, or acknowledge success.
export function PaymentPrompt({ride,token,onClose}) {
  const {payment:testPayment,result,qr,busy:qrBusy,error:qrError,generate}=useTestQr(ride,token);
  const [view,setView]=useState(()=>ride.payment?.method==='CASH'?'cash':ride.payment?.method==='ONLINE'?'online':'choose');
  const [busy,setBusy]=useState(false),[error,setError]=useState('');
  const dialog=useRef(null);
  useEffect(()=>{
    dialog.current?.querySelector('button')?.focus();
    const escape=event=>{if(event.key==='Escape')onClose();};
    window.addEventListener('keydown',escape);
    return ()=>window.removeEventListener('keydown',escape);
  },[]);
  const online=ride.test_payments_enabled;
  const confirmed=ride.payment?.status==='CONFIRMED' || testPayment?.status==='SUCCESS';
  const method=ride.payment?.status==='CONFIRMED'?ride.payment.method:testPayment?.status==='SUCCESS'?'ONLINE':null;
  const amount=ride.payment?.amount || ride.quote.total;
  const driver=ride.driver?.name || 'your driver';
  async function choose(next) {
    setBusy(true);setError('');
    try{
      await api(`/rides/${ride.id}/payment-method`,{token,method:'POST',body:JSON.stringify({method:next})});
      setView(next==='CASH'?'cash':'online');
      if(next==='ONLINE')await generate();
    }catch(e){setError(e.message);}finally{setBusy(false);}
  }
  const later=<button className="text-link pay-later" onClick={onClose}>Pay later</button>;
  let content;
  if(confirmed)content=<><PaymentSuccess amount={amount} method={method}/><RatingForm ride={ride} role="rider" token={token}/><button className={`button ${ride.my_rating?'dark':'subtle'} full pay-done`} onClick={onClose}>Done</button></>;
  else if(view==='cash')content=<><p className="pay-label">Please pay in cash</p><p className="pay-amount">{money(amount)}</p><p className="pay-cash-to"><Banknote size={20}/>Hand the cash to {driver}</p><p className="pay-waiting" role="status"><span className="pay-spinner" aria-hidden="true"/>Waiting for {driver} to confirm…</p>{online && <button className="button subtle full" disabled={busy} onClick={()=>choose('ONLINE')}>Pay online instead<Smartphone size={20}/></button>}{later}</>;
  else if(view==='online' && qr && testPayment?.status==='FAILED')content=<><div className="pay-failed" role="alert"><strong>Payment failed</strong><p>The online payment didn’t go through. Try again or pay by cash.</p></div><button className="button dark full" onClick={generate} disabled={qrBusy}>{qrBusy?'Generating…':'Try again'}</button><button className="button subtle full" disabled={busy} onClick={()=>choose('CASH')}>Pay by cash instead<Banknote size={20}/></button>{later}</>;
  else if(view==='online' && qr)content=<><p className="pay-amount">{money(amount)}</p><div className="pay-qr"><img src={qr} width="220" height="220" alt="Scan to simulate payment. No money is transferred."/></div><a className="button lime full" href={result.url} target="_blank" rel="noreferrer">Open payment page</a><p className="pay-waiting" role="status"><span className="pay-spinner" aria-hidden="true"/>Waiting for payment…</p><p className="pay-hint">Scan with another phone, or open the payment page on this device. The link expires in 15 minutes.</p><button className="button subtle full" disabled={busy} onClick={()=>choose('CASH')}>Pay by cash instead<Banknote size={20}/></button>{later}</>;
  else if(view==='online')content=<><p className="pay-label">Pay online</p><p className="pay-amount">{money(amount)}</p><button className="button dark full" onClick={generate} disabled={qrBusy}>{qrBusy?'Generating…':'Show payment QR'}<Smartphone size={20}/></button><button className="button subtle full" disabled={busy} onClick={()=>choose('CASH')}>Pay by cash instead<Banknote size={20}/></button>{later}</>;
  else content=<><p className="pay-label">Amount to pay</p><p className="pay-amount">{money(amount)}</p><div className="pay-route"><span>{ride.quote.pickup}</span><span>{ride.quote.destination}</span></div><p className="pay-label">How would you like to pay?</p><div className="pay-methods">{online && <button className="pay-method" disabled={busy || qrBusy} onClick={()=>choose('ONLINE')}><Smartphone size={26}/><strong>Pay online</strong><small>UPI / QR</small></button>}<button className="pay-method" disabled={busy || qrBusy} onClick={()=>choose('CASH')}><Banknote size={26}/><strong>Pay by cash</strong><small>to {driver}</small></button></div>{later}</>;
  const shownError=error || qrError;
  return <div className="pay-overlay" onClick={event=>{if(event.target===event.currentTarget)onClose();}}><section className="pay-dialog" role="dialog" aria-modal="true" aria-labelledby="pay-title" ref={dialog}>{online && <span className="pay-test-badge">Online option is a TEST PAYMENT — no money transferred</span>}{!confirmed && <h2 id="pay-title">You’ve arrived!</h2>}{confirmed && <span id="pay-title" className="visually-hidden">Payment confirmed</span>}{!confirmed && <p className="pay-sub">Your trip with {driver} is complete.</p>}{content}{shownError && <p role="alert" className="form-error">{shownError}</p>}</section></div>;
}
