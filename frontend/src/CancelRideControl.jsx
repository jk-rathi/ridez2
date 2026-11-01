import { useState } from 'react';

const choices={rider:['Plans changed','Pickup location changed','Wait is too long','Driver or car details do not match'],driver:['Vehicle problem','Cannot reach pickup','Rider is not at pickup']};

export default function CancelRideControl({ride,role,perform,disabled,onReview}) {
  const [open,setOpen]=useState(false),[reason,setReason]=useState(''),[notes,setNotes]=useState('');
  function close(){setOpen(false);setReason('');setNotes('');onReview?.(false);}
  async function submit(event){
    event.preventDefault();if(disabled)return;
    const message=reason==='Other'?notes.trim():`${reason}${notes.trim()?` — ${notes.trim()}`:''}`;
    if(!message)return;
    const response=await perform(`/rides/${ride.id}/cancel`,{reason:message});
    if(response)close();
  }
  if(!open)return <button type="button" className="button subtle full cancel-ride-toggle" disabled={disabled} onClick={()=>{setOpen(true);onReview?.(true);}}>{ride.status==='SEARCHING'?'Cancel request':'Cancel ride'}</button>;
  return <form className="cancel-ride-review" aria-label="Cancel ride confirmation" onSubmit={submit}><h3>Cancel this ride?</h3><p>{ride.driver?'The assignment will end for both rider and driver. The driver stays offline.':'The search will stop and pending invitations will close.'} No payment or refund will be processed.</p><label>Reason for cancellation<select aria-label="Reason for cancellation" required value={reason} disabled={disabled} onChange={event=>setReason(event.target.value)}><option value="">Choose a reason</option>{choices[role].map(value=><option key={value}>{value}</option>)}<option>Other</option></select></label><label>{reason==='Other'?'Describe the reason':'Additional details (optional)'}<textarea required={reason==='Other'} maxLength={200} value={notes} disabled={disabled} onChange={event=>setNotes(event.target.value)}/></label><p className="cancel-sharing-note">The cancellation reason is shared with the other participant and recorded in ride history.</p><div className="cancel-review-actions"><button type="button" className="button dark" disabled={disabled} onClick={close}>Keep ride</button><button className="button review-danger" disabled={disabled || !reason || (reason==='Other' && !notes.trim())}>Confirm cancellation</button></div></form>;
}
