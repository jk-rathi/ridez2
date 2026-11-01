import { useEffect, useState } from 'react';
import { api } from './api';
import GoogleRouteMap from './GoogleRouteMap';

export function tripPhase(ride) {
  return ride.status==='IN_PROGRESS'?'in_progress':['ASSIGNED','ARRIVING'].includes(ride.status)?'approach':'overview';
}

// One authenticated poll shared by the trip card and the map, paced by the server.
export function useTripRoute(ride,token) {
  const enabled=ride.quote.provider==='google';
  const key=`${ride.id}:${tripPhase(ride)}`;
  const [state,setState]=useState({}),[revision,setRevision]=useState(0);
  useEffect(()=>{
    if(!enabled)return;
    const controller=new AbortController();let timer,delay=15000;
    setState({key,loading:true});
    async function load(){
      try{
        const result=await api(`/rides/${ride.id}/map`,{token,signal:controller.signal});
        if(!controller.signal.aborted)setState({key,data:result.map,loading:false});
        delay=(result.map.refresh_after_seconds||15)*1000;
      }catch(error){if(!controller.signal.aborted)setState({key,error:error.message,loading:false});delay=15000;}
      if(!controller.signal.aborted)timer=setTimeout(load,delay);
    }
    load();return ()=>{controller.abort();clearTimeout(timer);};
  },[key,token,revision,enabled]);
  return {...(state.key===key?state:{}),refresh:()=>setRevision(value=>value+1)};
}

const headings={
  approach:{rider:['Your driver is on the way','Live route from your driver to your pickup point. Your confirmed fare stays the same.'],driver:['Route to pickup','Your road route to the rider’s pickup point.']},
  in_progress:{rider:['Your trip on Google Maps','The road route refreshes as the driver moves. Your confirmed fare stays the same.'],driver:['Your trip on Google Maps','The road route refreshes as you move. The confirmed fare stays the same.']},
  overview:{rider:['Your Google road route','Your pickup and destination are connected using Google’s driving route.'],driver:['Your Google road route','Pickup and destination are connected using Google’s driving route.']},
};

export default function TripRouteMap({ride,role='rider',routeState}) {
  const phase=tripPhase(ride);
  const [heading,text]=headings[phase][role==='driver'?'driver':'rider'];
  const data=routeState.data;
  const pickup={lat:ride.quote.pickup_lat,lng:ride.quote.pickup_lng};
  const destination={lat:ride.quote.destination_lat,lng:ride.quote.destination_lng};
  return <section className="trip-route" aria-label="Live Google trip map"><div className="trip-route-heading"><div><h2>{heading}</h2><p>{text}</p></div><button type="button" className="button subtle" disabled={routeState.loading} onClick={routeState.refresh}>Refresh route</button></div>
    {routeState.loading && <p className="map-route-status" role="status">Loading Google road route…</p>}
    {routeState.error && <p className="form-error" role="alert">{routeState.error} Trip controls remain available. Use Refresh route to try again.</p>}
    <GoogleRouteMap pickup={pickup} destination={destination} polyline={data?.polyline} driverPosition={data?.driver_position}/>
    {data && <div className="trip-map-summary"><span>{data.driver_position?`Driver location captured ${new Date(data.driver_position.recorded_at).toLocaleTimeString()}`:ride.driver?'Driver location unavailable or stale; showing the pickup-to-destination route.':'Driver position will appear after assignment.'}</span><small>Google route updated {new Date(data.generated_at).toLocaleTimeString()}. Location updates may be delayed.</small></div>}
  </section>;
}
