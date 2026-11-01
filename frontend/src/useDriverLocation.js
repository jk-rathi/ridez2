import { useEffect, useState } from 'react';
import { api } from './api';

const locationErrors = {
  1: 'Location permission was denied. Enable it in your browser settings.',
  2: 'Your device could not determine a location. Turn on Location Services for this browser in your system settings, or set a test location in DevTools → Sensors.',
  3: 'Location request timed out. Check that Location Services and Wi-Fi are on, then try again.',
};

function locate(options) {
  return new Promise((resolve, reject)=>navigator.geolocation.getCurrentPosition(resolve, reject, options));
}

export async function getPosition() {
  if (!window.isSecureContext || !navigator.geolocation) throw new Error('Location requires HTTPS or localhost and a supported browser.');
  let position;
  try {
    position=await locate({enableHighAccuracy:true, maximumAge:0, timeout:15000});
  } catch(error) {
    // Desktop browsers often time out on high accuracy; a normal fix is still validated server-side.
    try { if (error.code === 1) throw error; position=await locate({enableHighAccuracy:false, maximumAge:0, timeout:20000}); }
    catch(retry) {const failure=new Error(locationErrors[retry.code] || 'Unable to get a fresh location. Check location services and try again.');failure.code=retry.code;throw failure;}
  }
  return {
    latitude:position.coords.latitude,
    longitude:position.coords.longitude,
    accuracy_m:position.coords.accuracy,
    recorded_at:new Date(position.timestamp).toISOString(),
  };
}

// Faster updates during a trip let the rider follow the driver; idle availability stays light.
const IDLE_INTERVAL_MS=30000, TRIP_INTERVAL_MS=10000;

export function useDriverLocation({token,enabled,available,onTrip=false}) {
  const [error,setError]=useState('');
  useEffect(()=>{
    if (!enabled) {setError('');return;}
    let stopped=false, timer, permission, paused=false;
    const controller=new AbortController();
    async function pauseRequests() {
      if(stopped || paused)return;
      try{await api('/driver/availability',{token,method:'POST',body:JSON.stringify({available:false}),signal:controller.signal});paused=true;}
      catch(error){if(!stopped)setError(error.message);}
    }
    async function send() {
      try {
        const position=await getPosition();
        if (stopped) return;
        await api('/driver/location',{token,method:'PUT',body:JSON.stringify(position),signal:controller.signal});
        if (!stopped && permission?.state!=='denied') {paused=false;setError('');}
      } catch(e) {if(!stopped){setError(e.message);if(e.code===1)await pauseRequests();}}
      if(!stopped)timer=setTimeout(send,onTrip?TRIP_INTERVAL_MS:IDLE_INTERVAL_MS);
    }
    async function permissionChanged() {
      if(stopped)return;
      if(permission.state==='granted'){paused=false;return;}
      if(permission.state!=='denied')return;
      setError('Location permission was revoked. New matching is paused; an active trip is preserved.');
      await pauseRequests();
    }
    navigator.permissions?.query({name:'geolocation'}).then(result=>{
      if(stopped)return;
      permission=result;
      permission.addEventListener('change',permissionChanged);
      permissionChanged();
    }).catch(()=>{});
    send();
    return ()=>{stopped=true;clearTimeout(timer);controller.abort();permission?.removeEventListener('change',permissionChanged);};
  },[token,enabled,available,onTrip]);
  return error;
}
