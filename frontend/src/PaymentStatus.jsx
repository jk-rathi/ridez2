import { useEffect, useRef, useState } from 'react';
import { Banknote, Smartphone, CircleCheck } from 'lucide-react';

const money=value=>new Intl.NumberFormat('en-IN',{style:'currency',currency:'INR'}).format(Number(value));

export function paymentLabel(payment) {
  if(!payment)return null;
  if(payment.status==='CONFIRMED')return payment.method==='CASH'?'Paid in cash':payment.method==='ONLINE'?'Paid online':'Paid';
  return payment.method==='CASH'?'Paying by cash · awaiting driver confirmation':payment.method==='ONLINE'?'Paying online · awaiting payment':'Awaiting payment';
}

export function PaymentStatusLine({ride}) {
  const payment=ride.payment;
  if(ride.status!=='COMPLETED' || !payment)return null;
  return <p className={`payment-status ${payment.status==='CONFIRMED'?'paid':'pending'}`}>{payment.status==='CONFIRMED'?<CircleCheck size={16}/>:payment.method==='CASH'?<Banknote size={16}/>:<Smartphone size={16}/>}<span><b>{money(payment.amount)}</b> · {paymentLabel(payment)}</span></p>;
}

// Shown on the driver's overview for every completed trip whose payment is not yet confirmed.
export function DriverCollectCard({ride,perform,disabled}) {
  const payment=ride.payment;
  const choice=payment.method==='CASH'?'Rider will pay in cash':payment.method==='ONLINE'?'Rider is paying online…':'Rider hasn’t chosen how to pay yet';
  async function received(){
    if(window.confirm(`Confirm you received ${money(payment.amount)} in cash from ${ride.rider.name}?`))await perform(`/rides/${ride.id}/confirm-cash`);
  }
  return <section className="collect-card" aria-label={`Collect payment from ${ride.rider.name}`}>
    <span className="collect-label">COLLECT PAYMENT</span>
    <p className="collect-amount">{money(payment.amount)}</p>
    <p className="collect-rider">from {ride.rider.name} · {ride.quote.destination}</p>
    <p className={`collect-choice ${payment.method==='ONLINE'?'online':''}`}>{payment.method==='ONLINE'?<Smartphone size={18}/>:<Banknote size={18}/>}{choice}</p>
    <button className="button lime full" disabled={disabled} onClick={received}>Cash received<Banknote size={20}/></button>
    <p className="collect-note">Earnings for this trip are added once payment is confirmed. Online payments confirm automatically.</p>
  </section>;
}

// Briefly celebrates payments that become confirmed while the driver is watching.
export function usePaymentConfirmedFlash(rides) {
  const pending=useRef(null),[flash,setFlash]=useState(null);
  useEffect(()=>{
    if(!rides)return;
    const now=new Set(rides.filter(ride=>ride.payment?.status==='PENDING').map(ride=>ride.id));
    const confirmed=pending.current && rides.find(ride=>pending.current.has(ride.id) && ride.payment?.status==='CONFIRMED');
    pending.current=now;
    if(confirmed)setFlash({id:confirmed.id,amount:confirmed.payment.amount,method:confirmed.payment.method});
  },[rides]);
  useEffect(()=>{if(!flash)return;const timer=setTimeout(()=>setFlash(null),6000);return ()=>clearTimeout(timer);},[flash]);
  return flash;
}

export function PaymentConfirmedFlash({flash}) {
  return <div className="payment-flash" role="status"><svg className="pay-success-mark small" viewBox="0 0 120 120" aria-hidden="true"><circle className="pay-ring" cx="60" cy="60" r="52"/><circle className="pay-disc" cx="60" cy="60" r="44"/><path className="pay-tick" d="M38 62 L53 77 L84 45"/></svg><div><strong>Payment received · {money(flash.amount)}</strong><span>{flash.method==='CASH'?'Cash confirmed.':'Paid online.'} Added to your earnings.</span></div></div>;
}
