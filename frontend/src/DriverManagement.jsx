import { useEffect, useState } from 'react';
import { api } from './api';
import VehicleEditor from './VehicleEditor';

const actions={pending:['approve','Approve driver'],active:['suspend','Suspend driver'],suspended:['reinstate','Reinstate driver']};
const statusLabels={pending:'Pending approval',active:'Active',suspended:'Suspended',disabled:'Disabled'};

export default function DriverManagement({token,disabled,onChanged,refreshKey}) {
  const [data,setData]=useState(null),[status,setStatus]=useState(''),[draft,setDraft]=useState(''),[query,setQuery]=useState(''),[page,setPage]=useState(1),[revision,setRevision]=useState(0);
  const [selected,setSelected]=useState(null),[reason,setReason]=useState(''),[error,setError]=useState(''),[message,setMessage]=useState(''),[loading,setLoading]=useState(false),[saving,setSaving]=useState(false),[vehicleDriver,setVehicleDriver]=useState(null);
  useEffect(()=>{
    const controller=new AbortController();setLoading(true);
    const params=new URLSearchParams({page:String(page),status,q:query});
    api(`/admin/drivers?${params}`,{token,signal:controller.signal}).then(result=>{if(!controller.signal.aborted)setData(result);}).catch(error=>{if(!controller.signal.aborted)setError(error.message);}).finally(()=>{if(!controller.signal.aborted)setLoading(false);});
    return ()=>controller.abort();
  },[token,status,query,page,revision,refreshKey]);
  const locked=disabled || saving;
  function choose(driver){setVehicleDriver(null);setSelected(driver);setReason('');setError('');setMessage('');}
  async function save(event){
    event.preventDefault();if(locked || !selected)return;
    const [action]=actions[selected.status];setSaving(true);setError('');setMessage('');
    try{
      await api(`/admin/drivers/${selected.id}/${action}`,{token,method:'POST',body:JSON.stringify({version:selected.status_revision,reason})});
      setMessage(`${selected.name}: ${action==='suspend'?'suspended':action==='reinstate'?'reinstated and offline':'approved and offline'}.`);
      setSelected(null);setReason('');setRevision(value=>value+1);onChanged();
    }catch(error){setError(error.message);}
    finally{setSaving(false);}
  }
  return <section className="journey-card driver-management"><h2>Driver management</h2><p>Review applications, suspend new requests, or reinstate a driver. Every decision records your reason.</p>
    <form className="driver-filters" onSubmit={event=>{event.preventDefault();setQuery(draft);setPage(1);setRevision(value=>value+1);}}>
      <label>Status<select aria-label="Driver status" value={status} disabled={saving} onChange={event=>{setStatus(event.target.value);setPage(1);}}><option value="">All drivers</option>{Object.entries(statusLabels).map(([value,label])=><option value={value} key={value}>{label}</option>)}</select></label>
      <label>Search drivers<input type="search" maxLength={100} value={draft} disabled={saving} onChange={event=>setDraft(event.target.value)} placeholder="Name, mobile or account code"/></label><button className="button dark" disabled={locked || loading}>Search drivers</button>
    </form>
    {error && <div className="form-error" role="alert">{error} <button type="button" className="text-link" disabled={locked} onClick={()=>{setSelected(null);setError('');setRevision(value=>value+1);}}>Reload drivers</button></div>}
    {message && <div className="notice" role="status">{message}</div>}
    {vehicleDriver && <VehicleEditor key={`${vehicleDriver.id}:${vehicleDriver.vehicle?.version || 0}`} driver={vehicleDriver} token={token} onCancel={()=>setVehicleDriver(null)} onSaved={()=>{setVehicleDriver(null);setMessage('Vehicle details saved.');setRevision(value=>value+1);onChanged();}}/>}
    {selected && <form className="driver-review" onSubmit={save} aria-label="Driver status review"><h3>{actions[selected.status][1]} · {selected.name}</h3><p>{selected.user_code} · {statusLabels[selected.status]}</p><p>{selected.status==='active'?'Suspension immediately stops new requests and closes pending invitations. The driver can still sign in, view earnings and finish an assigned trip.':selected.status==='suspended'?'Reinstatement restores eligibility. The driver stays offline and must provide a fresh location before going available.':'Approve only after reviewing the driver’s application.'}</p>{selected.active_ride && <p className="driver-trip-notice">Active trip #{selected.active_ride.id.slice(0,8)} · {selected.active_ride.status.replaceAll('_',' ').toLowerCase()}. This trip will be preserved.</p>}<label>Reason{selected.status==='active'?' (visible to driver)':''}<textarea required maxLength={300} value={reason} disabled={saving} onChange={event=>setReason(event.target.value)} placeholder="Explain the review decision"/></label><div className="driver-review-actions"><button type="button" className="button subtle" disabled={saving} onClick={()=>setSelected(null)}>Cancel review</button><button className={`button ${selected.status==='active'?'review-danger':'dark'}`} disabled={locked || !reason.trim()}>{saving?'Saving…':`Confirm ${actions[selected.status][1].toLowerCase()}`}</button></div></form>}
    {loading && <p role="status">Loading drivers…</p>}
    {data && <><p className="audit-count">{data.total} driver{data.total===1?'':'s'} · page {data.page} of {Math.max(1,Math.ceil(data.total/data.page_size))}</p>{data.items.length?data.items.map(driver=><article className="driver-row managed-driver" key={driver.id} aria-label={`Driver ${driver.name}`}><div><strong>{driver.name}</strong><small>{driver.user_code} · {driver.mobile}</small><span className={`driver-status status-${driver.status}`}>{statusLabels[driver.status]}</span><small>{driver.vehicle?`${driver.vehicle.registration} · ${driver.vehicle.color} ${driver.vehicle.model}`:'Vehicle details not added'}</small><small>{driver.active_ride?`Active trip #${driver.active_ride.id.slice(0,8)} · ${driver.active_ride.status.replaceAll('_',' ').toLowerCase()}`:driver.location?.fresh?'Location fresh':'Location stale or missing'}</small></div><div className="managed-driver-actions">{driver.status!=='disabled' && <button type="button" className="button subtle" disabled={locked || loading || !!driver.active_ride} onClick={()=>{setSelected(null);setVehicleDriver(driver);setMessage('');}}>Vehicle details</button>}{actions[driver.status]?<button className={`button ${driver.status==='active'?'subtle':'dark'}`} disabled={locked || loading} onClick={()=>choose(driver)}>{actions[driver.status][1]}</button>:<small>Disabled accounts require a separate account review.</small>}</div></article>):<div className="empty-panel"><h3>No matching drivers.</h3><p>Try another name or status.</p></div>}<nav className="audit-pagination" aria-label="Driver pagination"><button className="button subtle" disabled={locked || loading || page===1} onClick={()=>setPage(value=>value-1)}>Previous</button><button className="button subtle" disabled={locked || loading || page*data.page_size>=data.total} onClick={()=>setPage(value=>value+1)}>Next</button></nav></>}
  </section>;
}
