import { createContext, useContext, useState } from 'react';
import { Star } from 'lucide-react';
import { api } from './api';

const NEGATIVE = new Set(['Unsafe driving', 'Late', 'Rude', 'Dirty car', 'Wrong route', 'Left a mess', 'Wrong pickup']);
const words = ['', 'Poor', 'Below average', 'Okay', 'Good', 'Excellent'];

// Tag choices come from the server (workspace.rating_tags) so the list lives in one place.
export const RatingTags = createContext([]);

export function RatingBadge({rating,label='ratings'}) {
  if(!rating)return null;
  if(!rating.count)return <span className="rating-badge new">New</span>;
  return <span className="rating-badge" aria-label={`Rated ${rating.average} out of 5 from ${rating.count} ${label}`}><Star size={14} fill="currentColor"/>{rating.average}<small>({rating.count})</small></span>;
}

export function StarsShown({stars}) {
  return <span className="stars-shown" aria-label={`${stars} out of 5 stars`}>{[1,2,3,4,5].map(n=><Star key={n} size={16} fill={n<=stars?'currentColor':'none'}/>)}</span>;
}

// The rider rates the driver, or the driver rates the rider, once per completed trip.
export default function RatingForm({ride,role,token,compact=false,onRated}) {
  const tags=useContext(RatingTags);
  const [stars,setStars]=useState(0),[hover,setHover]=useState(0),[chosen,setChosen]=useState([]),[comment,setComment]=useState('');
  const [busy,setBusy]=useState(false),[error,setError]=useState(''),[saved,setSaved]=useState(ride.my_rating || null);
  const other=role==='rider'?ride.driver?.name || 'your driver':ride.rider?.name || 'your rider';
  if(saved)return <div className="rating-done" role="status"><StarsShown stars={saved.stars}/><span>You rated {other} {saved.stars} star{saved.stars===1?'':'s'}. Thanks!</span></div>;
  const shown=hover || stars;
  // Match tags to the sentiment of the stars: praise for 4-5, problems for 1-2, either for 3.
  const offered=tags.filter(tag=>stars>=4?!NEGATIVE.has(tag):stars<=2?NEGATIVE.has(tag):true);
  function toggle(tag){setChosen(list=>list.includes(tag)?list.filter(item=>item!==tag):list.length<5?[...list,tag]:list);}
  function pick(value){setStars(value);setChosen([]);}
  async function submit(event) {
    event.preventDefault();setBusy(true);setError('');
    try{
      const data=await api(`/rides/${ride.id}/rating`,{token,method:'POST',body:JSON.stringify({stars,tags:chosen,comment:comment.trim() || undefined})});
      setSaved(data.rating);onRated?.(data.rating);
    }catch(e){setError(e.message);}finally{setBusy(false);}
  }
  return <form className={`rating-form ${compact?'compact':''}`} onSubmit={submit} aria-label={`Rate ${other}`}>
    <h3>{role==='rider'?`How was your trip with ${other}?`:`Rate your rider ${other}`}</h3>
    <div className="rating-stars" role="radiogroup" aria-label="Star rating" onMouseLeave={()=>setHover(0)}>
      {[1,2,3,4,5].map(n=><button type="button" key={n} role="radio" aria-checked={stars===n} aria-label={`${n} star${n===1?'':'s'}`} className={n<=shown?'on':''} onMouseEnter={()=>setHover(n)} onClick={()=>pick(n)}><Star size={34} fill={n<=shown?'currentColor':'none'}/></button>)}
    </div>
    <p className="rating-word" aria-live="polite">{shown?words[shown]:'Tap a star to rate'}</p>
    {stars>0 && <>
      {offered.length>0 && <div className="rating-tags">{offered.map(tag=><button type="button" key={tag} aria-pressed={chosen.includes(tag)} className={chosen.includes(tag)?'chosen':''} onClick={()=>toggle(tag)}>{tag}</button>)}</div>}
      <label className="rating-comment"><span>Add a comment (optional, only our team sees it)</span><textarea maxLength={300} rows={2} value={comment} onChange={event=>setComment(event.target.value)} placeholder={stars<=3?'What could have been better?':'Anything you’d like to share?'}/></label>
      <button className="button dark full" disabled={busy}>{busy?'Submitting…':'Submit rating'}</button>
    </>}
    {error && <p className="form-error" role="alert">{error}</p>}
  </form>;
}
