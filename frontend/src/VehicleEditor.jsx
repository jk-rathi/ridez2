import { useState } from 'react';
import { api } from './api';

export default function VehicleEditor({driver,token,onSaved,onCancel}) {
  const [form,setForm]=useState({registration:driver.vehicle?.registration || '',model:driver.vehicle?.model || '',color:driver.vehicle?.color || '',reason:''});
  const [busy,setBusy]=useState(false),[error,setError]=useState('');
  async function save(event){
    event.preventDefault();if(busy)return;setBusy(true);setError('');
    try{await api(`/admin/drivers/${driver.id}/vehicle`,{token,method:'PUT',body:JSON.stringify({...form,version:driver.vehicle?.version || 0})});onSaved();}
    catch(error){setError(error.message);}finally{setBusy(false);}
  }
  return <form className="driver-review" aria-label="Vehicle details form" onSubmit={save}><h3>Vehicle details · {driver.name}</h3><p>Record the car you have reviewed. These details are saved with each newly accepted ride. Vehicle details cannot change during an active trip.</p>{[['registration','Car number',20,'MH 12 AB 1234'],['model','Car model',80,'Maruti Suzuki Dzire'],['color','Colour',40,'White']].map(([key,label,maxLength,placeholder])=><label key={key}>{label}<input required maxLength={maxLength} value={form[key]} placeholder={placeholder} disabled={busy} onChange={event=>setForm(previous=>({...previous,[key]:event.target.value}))}/></label>)}<label>Reason for update<textarea required maxLength={300} value={form.reason} disabled={busy} onChange={event=>setForm(previous=>({...previous,reason:event.target.value}))}/></label>{error && <p className="form-error" role="alert">{error}</p>}<div className="driver-review-actions"><button type="button" className="button subtle" disabled={busy} onClick={onCancel}>Cancel</button><button className="button dark" disabled={busy}>{busy?'Saving…':'Save vehicle details'}</button></div></form>;
}
