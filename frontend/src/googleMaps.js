let loading;
export function loadMaps() {
  if(window.google?.maps?.Map)return Promise.resolve(window.google.maps);
  const key=import.meta.env.VITE_GOOGLE_MAPS_BROWSER_KEY;
  if(!key)return Promise.reject(new Error('Set VITE_GOOGLE_MAPS_BROWSER_KEY in frontend/.env.local, then restart Vite to enable the map.'));
  if(loading)return loading;
  loading=new Promise((resolve,reject)=>{
    const script=document.createElement('script');
    const timer=setTimeout(()=>fail('Google Maps took too long to load. Check your connection and key restrictions.'),15000);
    function fail(message){clearTimeout(timer);script.remove();loading=null;reject(new Error(message));}
    window.__ridezGoogleReady=()=>{clearTimeout(timer);resolve(window.google.maps);};
    window.gm_authFailure=()=>{window.dispatchEvent(new Event('ridez.maps.error'));fail('Google Maps access was denied. Check browser key restrictions, API enablement and billing.');};
    script.src=`https://maps.googleapis.com/maps/api/js?${new URLSearchParams({key,v:'quarterly',libraries:'marker,geometry',callback:'__ridezGoogleReady',loading:'async'})}`;
    script.async=true;
    script.onerror=()=>fail('Google Maps could not load. Check your connection and browser key.');
    document.head.appendChild(script);
  });
  return loading;
}
