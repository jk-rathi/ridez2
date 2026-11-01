import { useState } from 'react';
import { ArrowRight, MapPin } from 'lucide-react';
import { getPosition } from './useDriverLocation';
import GoogleRouteMap from './GoogleRouteMap';
import AddressSearch from './AddressSearch';

export default function BookingPanel({provider,perform,disabled,QuoteDetails}) {
  const [quote,setQuote]=useState(null),[error,setError]=useState(''),[locating,setLocating]=useState(false);
  const [form,setForm]=useState({pickup:'',destination:'',pickup_lat:'',pickup_lng:'',destination_lat:'',destination_lng:''});
  const google=provider==='google';
  function change(key,value){setForm(previous=>({...previous,[key]:value,...(google && ['pickup','destination'].includes(key)?{[`${key}_lat`]:'',[`${key}_lng`]:''}:{})}));setQuote(null);setError('');}
  function point(prefix){return form[`${prefix}_lat`]!=='' && form[`${prefix}_lng`]!=='' ? {lat:Number(form[`${prefix}_lat`]),lng:Number(form[`${prefix}_lng`])}:null;}
  function select(prefix,point){setForm(previous=>({...previous,[`${prefix}_lat`]:String(point.lat),[`${prefix}_lng`]:String(point.lng),[prefix]:point.label || `${prefix==='pickup'?'Pickup':'Destination'} (${point.lat.toFixed(5)}, ${point.lng.toFixed(5)})`}));setQuote(null);setError('');}
  async function locate(){
    setLocating(true);setError('');
    try{const position=await getPosition();select('pickup',{lat:position.latitude,lng:position.longitude});}
    catch(e){setError(e.message);}finally{setLocating(false);}
  }
  async function submit(event){
    event.preventDefault();setError('');setQuote(null);
    if((google?['pickup','destination']:['pickup']).some(prefix=>form[`${prefix}_lat`]==='' || form[`${prefix}_lng`]==='')){setError('Select an address suggestion or map point for each location before requesting a fare.');return;}
    const payload={...form,pickup_lat:Number(form.pickup_lat),pickup_lng:Number(form.pickup_lng)};
    if(form.destination_lat!=='' || form.destination_lng!==''){
      payload.destination_lat=Number(form.destination_lat);payload.destination_lng=Number(form.destination_lng);
    }else{delete payload.destination_lat;delete payload.destination_lng;}
    const response=await perform('/fares/quotes',payload);
    if(response){setQuote(response.quote);}
  }
  return <div className="booking-layout">{google && <GoogleRouteMap pickup={point('pickup')} destination={point('destination')} polyline={quote?.polyline} onSelect={select}/>}<div className="journey-grid"><section className="journey-card"><h2>Let’s go places.</h2><p>{google?'Search pickup and destination addresses, then select a suggestion. You can also choose on the map.':'Simulator mode uses sample route distances and rates.'}</p>{error && <div className="form-error" role="alert">{error}</div>}<form onSubmit={submit}><div className="location-fields">{[['pickup','Pickup location'],['destination','Destination']].map(([key,label])=>google?<AddressSearch key={key} name={key} label={label} value={form[key]} disabled={disabled||locating} selected={!!point(key)} bias={point('pickup')} onChange={text=>change(key,text)} onChoose={place=>select(key,place)}/>:<label key={key}>{label}<input name={key} value={form[key]} onChange={e=>change(key,e.target.value)} maxLength={160} required placeholder={key==='pickup'?'Pickup label':'Destination label'}/></label>)}</div><details className="coordinate-details" open={!google}><summary>Coordinates and manual adjustment</summary>{['pickup','destination'].map(prefix=><div className="coordinate-fields" key={prefix}>{['lat','lng'].map(axis=><label key={axis}>{prefix==='pickup'?'Pickup':'Destination'} {axis==='lat'?'latitude':'longitude'}<input name={`${prefix}_${axis}`} value={form[`${prefix}_${axis}`]} onChange={e=>change(`${prefix}_${axis}`,e.target.value)} type="number" step="any" min={axis==='lat'?-90:-180} max={axis==='lat'?90:180} required={!google && prefix==='pickup'}/></label>)}</div>)}</details><button type="button" className="button subtle full" disabled={disabled||locating} onClick={locate}>{locating?'Getting your location…':'Use my location'}</button><p>{google?'Select a suggestion to use its exact location. Editing an address clears its previous location.':'Simulator labels do not search Google. Coordinates determine matching.'}</p><button className="button dark full" disabled={disabled||locating}>Get fare estimate <ArrowRight size={17}/></button></form></section>{quote ? <section className="journey-card"><h2>Your fare, upfront.</h2><QuoteDetails quote={quote}/><p>Quote expires at {new Date(quote.expires_at).toLocaleTimeString()}. Rate version {quote.fare_rule_version}. Development rates apply until configured by your admin. Taxes, discounts and payment fees are not included.</p><button className="button dark full" disabled={disabled} onClick={async()=>{const response=await perform('/rides',{quote_id:quote.id});if(response)setQuote(null);}}>{quote.provider==='google'?'Confirm ride':'Confirm simulated ride'}<ArrowRight size={17}/></button></section> : <section className="empty-panel"><MapPin size={38}/><h2>Every journey starts somewhere.</h2><p>Your route estimate and itemized fare will appear here. Google failures are shown explicitly and do not switch to sample data.</p></section>}</div></div>;
}
