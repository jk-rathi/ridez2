import { useEffect, useId, useRef, useState } from 'react';
import { loadMaps } from './googleMaps';

export default function AddressSearch({name,label,value,onChange,onChoose,bias,disabled,selected}) {
  const id=useId(),listId=`${id}-suggestions`;
  const [query,setQuery]=useState(''),[items,setItems]=useState([]),[open,setOpen]=useState(false),[active,setActive]=useState(-1),[busy,setBusy]=useState(false),[selecting,setSelecting]=useState(false),[error,setError]=useState('');
  const sequence=useRef(0),selection=useRef(0),token=useRef(null),latest=useRef(value),alive=useRef(true);
  latest.current=value;
  useEffect(()=>{alive.current=true;return ()=>{alive.current=false;sequence.current++;selection.current++;};},[]);
  useEffect(()=>{
    const current=++sequence.current;
    if(query.trim().length<3 || query!==value || !open){setItems([]);setBusy(false);if(query!==value)setError('');return;}
    setBusy(true);setError('');
    const timer=setTimeout(async()=>{
      try{
        const maps=await loadMaps();
        const places=await maps.importLibrary('places');
        token.current ||= new places.AutocompleteSessionToken();
        const request={input:query,sessionToken:token.current};
        if(bias && Number.isFinite(bias.lat) && Number.isFinite(bias.lng))request.locationBias={center:bias,radius:50000};
        const result=await places.AutocompleteSuggestion.fetchAutocompleteSuggestions(request);
        if(!alive.current || current!==sequence.current || latest.current!==query)return;
        setItems((result.suggestions || []).filter(item=>item.placePrediction).slice(0,5));setActive(-1);
      }catch{
        if(alive.current && current===sequence.current){setItems([]);setError('Address search unavailable. Check Places API (New) and browser-key restrictions, or select on the map.');}
      }finally{if(alive.current && current===sequence.current)setBusy(false);}
    },300);
    return ()=>clearTimeout(timer);
  },[query,value,open]);
  async function choose(item){
    const current=++selection.current,typed=latest.current;
    sequence.current++;
    setSelecting(true);setOpen(false);setItems([]);setError('');
    try{
      const place=item.placePrediction.toPlace();
      await place.fetchFields({fields:['formattedAddress','location']});
      if(!alive.current || current!==selection.current || latest.current!==typed)return;
      const lat=place.location?.lat(),lng=place.location?.lng();
      if(!Number.isFinite(lat) || !Number.isFinite(lng))throw new Error('Missing location');
      const address=(place.formattedAddress || item.placePrediction.text.toString()).slice(0,160);
      token.current=null;
      onChoose({label:address,lat,lng});
      setQuery('');
    }catch{if(alive.current && current===selection.current)setError('Unable to load this address. Select another suggestion or choose a point on the map.');}
    finally{token.current=null;if(alive.current)setSelecting(false);}
  }
  return <div className="address-search"><label htmlFor={id}>{label}</label><input id={id} name={name} value={value} role="combobox" aria-autocomplete="list" aria-expanded={open && items.length>0} aria-controls={listId} aria-activedescendant={open && active>=0?`${listId}-${active}`:undefined} aria-describedby={`${id}-status`} autoComplete="off" maxLength={160} required disabled={disabled||selecting} placeholder={name==='pickup'?'Search pickup address':'Search destination address'} onChange={event=>{sequence.current++;if(!event.target.value.trim())token.current=null;setQuery(event.target.value);onChange(event.target.value);setItems([]);setOpen(true);setError('');}} onFocus={()=>{if(query && query===value)setOpen(true);}} onBlur={()=>{setOpen(false);sequence.current++;token.current=null;}} onKeyDown={event=>{
    if(event.key==='Escape'){setOpen(false);sequence.current++;return;}
    if(!open || !items.length)return;
    if(event.key==='ArrowDown'){event.preventDefault();setActive(index=>(index+1)%items.length);}
    if(event.key==='ArrowUp'){event.preventDefault();setActive(index=>(index<=0?items.length-1:index-1));}
    if(event.key==='Enter'){event.preventDefault();choose(items[active>=0?active:0]);}
  }}/>{open && items.length>0 && <div className="address-dropdown"><ul id={listId} role="listbox" aria-label={`${label} suggestions`}>{items.map((item,index)=><li key={item.placePrediction.placeId || index} id={`${listId}-${index}`} role="option" aria-selected={index===active} className={index===active?'active':''} onMouseDown={event=>event.preventDefault()} onClick={()=>choose(item)}>{item.placePrediction.text.toString()}</li>)}</ul><div className="places-attribution"><img src="https://maps.gstatic.com/mapfiles/api-3/images/powered-by-google-on-white3.png" alt="Powered by Google" width="120" height="14"/></div></div>}<small id={`${id}-status`} className={error?'address-error':'address-status'} role="status">{error || (selecting?'Loading selected address…':busy?'Searching addresses…':selected?'Location selected':open && query.trim().length>=3 && !items.length?'No matching addresses. Try another search or select on the map.':'')}</small></div>;
}
