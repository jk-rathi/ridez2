import { CarFront, MapPin, ShieldCheck, UserRound } from 'lucide-react';

const currency=value=>new Intl.NumberFormat('en-IN',{style:'currency',currency:'INR',maximumFractionDigits:2}).format(Number(value));
const progress={ASSIGNED:'Driver accepted your ride',ARRIVING:'Your driver is on the way',WAITING:'Your driver is at pickup',IN_PROGRESS:'You’re on your way'};

export default function AssignedRideDetails({ride,role,tripOtp}) {
  const vehicle=ride.driver?.vehicle;
  const beforeStart=['ASSIGNED','ARRIVING','WAITING'].includes(ride.status);
  return <section className="assigned-details" aria-label="Important ride details">
    <h2 className="ride-progress-title">{role==='rider'?progress[ride.status]:ride.status==='IN_PROGRESS'?'Trip in progress':'Your pickup details'}</h2>
    <div className="ride-person-feature"><span className="ride-person-icon" aria-hidden="true"><UserRound size={30}/></span><div><span className="ride-fact-label">{role==='rider'?'Your driver':'Your rider'}</span><h3>{role==='rider'?ride.driver.name:ride.rider.name}</h3>{role==='rider' && <small>{ride.driver.user_code}</small>}</div></div>
    <div className="ride-vehicle-feature"><div className="ride-fact-heading"><CarFront size={22}/><span className="ride-fact-label">{role==='rider'?'Look for this car':'Assigned car'}</span></div>{vehicle?<><strong className="ride-license-plate" aria-label={`Car number ${vehicle.registration}`}>{vehicle.registration}</strong><p className="ride-car-description">{vehicle.color} · {vehicle.model}</p></>:<><strong className="ride-vehicle-missing">Car number not provided</strong><p>Confirm the car details with your driver before boarding.</p></>}</div>
    <div className="ride-fare-feature"><div><span className="ride-fact-label">Confirmed trip fare</span><small>INR · no payment collected in this app</small></div><strong>{currency(ride.quote.total)}</strong></div>
    {role==='rider' && beforeStart && tripOtp && <div className="ride-otp-feature"><div><ShieldCheck size={21}/><span className="ride-fact-label">Your ride OTP</span></div><strong aria-label={`Your ride OTP ${tripOtp}`}>{tripOtp}</strong><p>Share only when you’re at pickup and ready to start.</p></div>}
    <div className="ride-important-places">{[['Pickup',ride.quote.pickup],['Destination',ride.quote.destination]].map(([label,value])=><div key={label}><MapPin size={20}/><div><span className="ride-fact-label">{label}</span><strong>{value}</strong></div></div>)}</div>
    <p className="ride-summary-meta">{ride.quote.distance_km} km · estimated {ride.quote.duration_min} min · Ride #{ride.id.slice(0,8)}</p>
    {role==='rider' && beforeStart && <p className="ride-boarding-note"><ShieldCheck size={18}/> Match the driver and car number before you board.</p>}
  </section>;
}
