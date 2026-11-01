import { Navigation, MapPin } from 'lucide-react';
import { tripPhase } from './TripRouteMap';

// Opens Google Maps (app or site) in a new tab so ridez.io stays open for GPS updates and trip controls.
export function googleNavigationUrl(place,lat,lng) {
  const target=Number.isFinite(lat) && Number.isFinite(lng)?`${lat},${lng}`:place;
  if(!target)return null;
  return `https://www.google.com/maps/dir/?${new URLSearchParams({api:'1',destination:target,travelmode:'driving',dir_action:'navigate'})}`;
}

const clock=value=>new Date(value).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'});
const km=metres=>`${(metres/1000).toFixed(1)}`;

function liveRoute(ride,routeState,target) {
  const data=routeState.data;
  if(ride.quote.provider!=='google' || routeState.error || !data || data.target!==target || data.origin_source!=='driver')return null;
  return {minutes:data.at_destination?0:Math.max(1,Math.ceil(data.duration_seconds/60)),distance:km(data.distance_m),arrival:clock(Date.parse(data.generated_at)+data.duration_seconds*1000),there:data.at_destination};
}

export default function TripStatsCard({ride,role,routeState}) {
  if(!ride.driver || !['ASSIGNED','ARRIVING','WAITING','IN_PROGRESS'].includes(ride.status))return null;
  const phase=ride.status==='WAITING'?'waiting':tripPhase(ride);
  const driver=role==='driver';
  const quote=ride.quote;
  let title,place,placeLabel,metrics,note,navigation=null;
  if(phase==='approach'){
    const live=liveRoute(ride,routeState,'pickup');
    title=live?.there?(driver?'You’re at the pickup point':'Your driver is at the pickup point'):(driver?'Head to pickup':'Your driver is on the way');
    placeLabel='Pickup';place=quote.pickup;
    metrics=[[driver?'Time to pickup':'Arriving in',live?(live.there?'Now':live.minutes):'—',live && !live.there?'min':''],['Distance',live?live.distance:'—',live?'km':''],['Expected at',live?live.arrival:'—','']];
    note=live?'Live estimate from Google. Traffic may change it.':routeState.loading?'Getting live estimate…':'Live estimate unavailable until the driver’s location is fresh.';
    navigation=googleNavigationUrl(quote.pickup,quote.pickup_lat,quote.pickup_lng);
  }else if(phase==='waiting'){
    title=driver?'At pickup — ask the rider for the OTP':'Your driver has arrived';
    placeLabel='Destination';place=quote.destination;
    metrics=[['Trip time',quote.duration_min,'min'],['Trip distance',quote.distance_km,'km']];
    note=driver?'Enter the rider’s OTP to start the trip.':'Share your ride OTP with the driver to start the trip.';
  }else{
    const live=liveRoute(ride,routeState,'destination');
    title=live?.there?'Arriving at destination':'On the way to destination';
    placeLabel='Destination';place=quote.destination;
    metrics=live?[['Time left',live.there?'Now':live.minutes,live.there?'':'min'],['Distance left',live.distance,'km'],['Arrive by',live.arrival,'']]:[['Trip time',quote.duration_min,'min'],['Trip distance',quote.distance_km,'km']];
    note=live?'Live estimate from Google. Traffic may change it.':quote.provider==='google'?(routeState.loading?'Getting live estimate…':'Showing the booked estimate until a fresh driver location arrives.'):'Simulated trip: showing the booked estimate.';
    navigation=googleNavigationUrl(quote.destination,quote.destination_lat,quote.destination_lng);
  }
  return <section className="trip-stats-card" aria-label="Trip status" aria-live="polite">
    <h2>{title}</h2>
    <div className={`trip-stats-metrics count-${metrics.length}`}>{metrics.map(([label,value,unit])=><div key={label}><span>{label}</span><strong>{value}{unit && <small> {unit}</small>}</strong></div>)}</div>
    <p className="trip-stats-place"><MapPin size={18}/><span><small>{placeLabel}</small>{place}</span></p>
    {driver && navigation && <a className="button lime full trip-navigate" href={navigation} target="_blank" rel="noopener noreferrer">Navigate in Google Maps<Navigation size={20}/></a>}
    {driver && navigation && <p className="trip-stats-hint">Opens Google Maps separately. Come back to ridez to update the trip; your phone may pause location updates while you’re in Maps.</p>}
    <p className="trip-stats-note">{note}</p>
  </section>;
}
