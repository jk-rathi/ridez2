import TestPaymentPage from './TestPayment';
import React, { createContext, useContext, useState, useEffect } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter, Routes, Route, Navigate, Link, NavLink, useNavigate } from 'react-router-dom';
import { ArrowUpRight, ArrowRight, MapPin, Navigation, ShieldCheck, Clock3, CarFront, LayoutDashboard, Route as RouteIcon, Wallet, LogOut, ChevronRight, Menu, X, UserRound, Radio, CircleHelp } from 'lucide-react';
import './styles.css';
import { api } from './api';
import { currentSession, subscribeSession, refreshSession, signIn, signOut } from './authSession';
import RideWorkspace from './RideWorkspace';
import FareSettings from './FareSettings';
import RevenueSettings from './RevenueSettings';
import AdminAudit from './AdminAudit';

const Auth = createContext(null);
function AuthProvider({ children }) {
  const [session,setSession]=useState(currentSession),[ready,setReady]=useState(false),[restoreError,setRestoreError]=useState(''),[signingOut,setSigningOut]=useState(false),[logoutError,setLogoutError]=useState('');
  async function restore(){setRestoreError('');setReady(false);try{await refreshSession();}catch(error){setRestoreError(error.message);}finally{setReady(true);}}
  useEffect(()=>{
    const unsubscribe=subscribeSession(value=>{setSession(value);setReady(true);setRestoreError('');});
    let alive=true;
    refreshSession().catch(error=>{if(alive)setRestoreError(error.message);}).finally(()=>{if(alive)setReady(true);});
    return ()=>{alive=false;unsubscribe();};
  },[]);
  useEffect(()=>{
    if(!session)return;
    let timer,stopped=false;
    async function renew(){try{await refreshSession();}catch{if(!stopped)timer=setTimeout(renew,15000);}}
    timer=setTimeout(renew,Math.max(1000,(session.expires_at*1000-Date.now())-60000));
    return ()=>{stopped=true;clearTimeout(timer);};
  },[session?.access_token]);
  async function logout(allDevices=false){
    setSigningOut(true);setLogoutError('');
    try{await signOut(allDevices);}catch(error){setLogoutError(error.message);}finally{setSigningOut(false);}
  }
  return <Auth.Provider value={{session,ready,restoreError,retryRestore:restore,logout,signingOut,logoutError}}>{children}</Auth.Provider>;
}
function SessionLoading(){return <main className="session-loading"><Brand/><p role="status">Restoring your session…</p></main>;}

function Brand() { return <Link className="brand" to="/">ridez<span>✳</span></Link>; }
function Tag({ children }) { return <span className="tag"><span />{children}</span>; }
function Landing() {
  return <div className="landing"><header className="public-header"><Brand /><nav><a href="#how">How it works</a><a href="#drivers">Drive with ridez</a><Link to="/login">Sign in <ArrowUpRight size={16}/></Link></nav><Link className="button dark" to="/register">Get started <ArrowUpRight size={16}/></Link></header>
    <main><section className="hero"><div className="hero-copy"><Tag>YOUR NEXT CHAPTER STARTS HERE</Tag><h1>Your city.<br/>Your plans.<br/><span>Your ride.</span></h1><p>From early starts to late-night goodbyes.<br/>A simpler way to get where life takes you.</p><div className="hero-actions"><Link to="/register" className="button lime">Find your ride <ArrowUpRight size={19}/></Link><Link to="/register?role=driver" className="text-link">Get in the driver’s seat <ArrowRight size={16}/></Link></div><div className="hero-note"><ShieldCheck size={17}/> Clear fares. Real connections. Less hassle.</div></div><CityMap hero/><div className="vertical-note">MADE FOR THE WAY YOU MOVE — RIDEZ.IO</div></section>
    <section className="trust-strip"><span>A LITTLE LESS WAITING. A LOT MORE LIVING.</span><div><MapPin size={18}/> Door to destination</div><div><Clock3 size={18}/> On your schedule</div><div><ShieldCheck size={18}/> Fares upfront</div></section>
    <section id="how" className="how"><div><Tag>LESS FRICTION. MORE FREEDOM.</Tag><h2>Good plans start<br/>with a simple ride.</h2></div><div className="steps">{[['01','Pick your places','Tell us where you are and where you’re headed.'],['02','Know your fare','Review your route and itemized estimate before you book.'],['03','Make your move','Connect with a driver and follow your trip along the way.']].map(([n,t,p])=><article key={n}><span>{n}</span><div><h3>{t}</h3><p>{p}</p></div></article>)}</div></section>
    <section id="drivers" className="driver-banner"><div><Tag>THE ROAD IS YOURS</Tag><h2>Your time.<br/>A new direction.</h2><p>Join as a driver and get ready for your next opportunity.</p></div><Link to="/register?role=driver" className="button lime">Become a driver <ArrowUpRight size={18}/></Link></section></main><footer><Brand/><span>Move through life, your way.</span><small>Development build · no payment processing</small></footer></div>;
}
function CityMap({ hero = false }) {
  return <div className={`city-map ${hero ? 'hero-map' : ''}`} aria-label="Illustrative city map, not a live map"><svg viewBox="0 0 700 700" role="img" aria-label="Decorative street grid with a sample route"><defs><pattern id="blocks" width="115" height="100" patternTransform="rotate(-25)" patternUnits="userSpaceOnUse"><rect width="115" height="100" fill="#e8e9df"/><rect x="7" y="7" width="97" height="82" rx="12" fill="#dadfd2" stroke="#f7f6ed" strokeWidth="7"/></pattern></defs><rect width="700" height="700" fill="url(#blocks)"/><path d="M470 -30 Q320 220 480 370 T520 750" fill="none" stroke="#b3cec7" strokeWidth="75"/><path d="M-50 540 L760 200 M-50 170 L700 620" stroke="#f7f6ed" strokeWidth="23"/><path d="M155 475 L285 415 L345 280 L478 214" fill="none" stroke="#243c2d" strokeWidth="10" strokeLinecap="round" strokeLinejoin="round"/><path d="M155 475 L285 415 L345 280 L478 214" fill="none" stroke="#c6f36c" strokeWidth="5" strokeLinecap="round" strokeLinejoin="round"/><circle cx="155" cy="475" r="14" fill="#1b3023" stroke="white" strokeWidth="5"/><circle cx="478" cy="214" r="14" fill="#c6f36c" stroke="#1b3023" strokeWidth="5"/><text x="75" y="210" className="map-label">THE NEIGHBOURHOOD</text><text x="392" y="540" className="map-label">RIVERSIDE</text><text x="220" y="110" className="map-label">CITY CENTRE</text></svg><div className="map-caption"><Radio size={14}/> ILLUSTRATIVE MAP</div>{hero && <><div className="map-pill"><span className="icon-square"><Navigation size={20}/></span><div><strong>A new way to move</strong><small>Your everyday, a little easier.</small></div><ArrowUpRight size={20}/></div><div className="map-car"><CarFront size={27}/></div><div className="map-place"><MapPin size={16}/> Wherever’s next.</div><div className="map-bottom"><span>GO SOMEWHERE GOOD.</span><span>↗</span></div></>}</div>;
}
function AuthPage({ register = false }) {
  const navigate = useNavigate();
  const { session,ready,restoreError,retryRestore } = useContext(Auth);
  const [role, setRole] = useState(new URLSearchParams(window.location.search).get('role') === 'driver' ? 'driver' : 'rider');
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [created, setCreated] = useState(null);
  async function submit(event) {
    event.preventDefault(); setError(''); setBusy(true);
    const fields = Object.fromEntries(new FormData(event.currentTarget));
    try {
      if (register) {
        const data = await api('/auth/register', { method: 'POST', body: JSON.stringify({ ...fields, role }) });
        setCreated(data.user);
      } else {
        const data = await signIn(fields);
        navigate(`/${data.user.role}`, { replace: true });
      }
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  if(!ready)return <SessionLoading/>;
  if(session)return <Navigate to={`/${session.user.role}`} replace/>;
  return <div className="auth-layout"><aside><Brand/><div><Tag>LET’S GET YOU THERE</Tag><h1>A good day<br/>starts with<br/><span>a little go.</span></h1><p>Your city is waiting. Make it yours.</p></div><small>YOUR CITY. YOUR PLANS. YOUR RIDE.</small></aside><main className="auth-main"><Link className="back-link" to="/">← Back to home</Link><div className="auth-card" key={register ? 'register' : 'login'}>{created ? <><span className="success-icon"><ShieldCheck size={32}/></span><Tag>YOU’RE PART OF RIDEZ</Tag><h2>Nice to meet you,<br/>{created.name}.</h2><p>Your permanent account code</p><div className="account-code">{created.user_code}</div>{created.role === 'driver' && <p className="notice">Your driver application is pending approval. You can sign in to view your workspace.</p>}<Link className="button dark full" to="/login">Continue to sign in <ArrowRight size={18}/></Link></> : <><Tag>{register ? 'YOUR NEXT MOVE' : 'GOOD TO SEE YOU AGAIN'}</Tag><h2>{register ? 'Let’s get started.' : 'Welcome back.'}</h2><p>{register ? 'A few details, and you’re on your way.' : 'Sign in to pick up where you left off.'}</p>{register && <div className="role-tabs"><button type="button" className={role === 'rider' ? 'selected' : ''} onClick={()=>setRole('rider')}><UserRound size={17}/> I want to ride</button><button type="button" className={role === 'driver' ? 'selected' : ''} onClick={()=>setRole('driver')}><CarFront size={17}/> I want to drive</button></div>}{restoreError && <div className="form-error" role="alert">{restoreError} <button type="button" className="text-link" onClick={retryRestore}>Retry restoring session</button></div>}<form onSubmit={submit}>{register && <label>Full name<input name="name" autoComplete="name" required maxLength={100} placeholder="Your name"/></label>}<label>Mobile number<input name="mobile" type="tel" autoComplete="tel" required placeholder="+91 98765 43210"/><small>Include your country code, e.g. +91.</small></label><label>Password<input name="password" type="password" autoComplete={register ? 'new-password' : 'current-password'} required minLength={register ? 10 : 1} maxLength={128} placeholder={register ? 'At least 10 characters' : 'Enter your password'}/></label>{error && <div className="form-error" role="alert">{error}</div>}<button className="button dark full" disabled={busy}>{busy ? 'Please wait…' : register ? 'Create account' : 'Sign in'}<ArrowRight size={18}/></button></form><div className="auth-switch">{register ? 'Already going places?' : 'New around here?'} <Link to={register ? '/login' : '/register'}>{register ? 'Sign in' : 'Create an account'}</Link></div><div className="auth-security"><ShieldCheck size={15}/> Mobile + password. No OTP required.</div></>}</div></main></div>;
}
function Protected({ role }) {
  const { session,ready,restoreError,retryRestore } = useContext(Auth);
  if(!ready)return <SessionLoading/>;
  if(restoreError && !session)return <main className="session-loading"><Brand/><p role="alert">{restoreError}</p><button className="button dark" onClick={retryRestore}>Retry restoring session</button><Link to="/login">Sign in again</Link></main>;
  if (!session) return <Navigate to="/login" replace/>;
  if (session.user.role !== role) return <Navigate to={`/${session.user.role}`} replace/>;
  return <Workspace role={role}/>;
}
const navItems = { rider: [['', 'Overview', LayoutDashboard], ['/history','Your rides',RouteIcon], ['/account','Your account',UserRound]], driver: [['','Overview',LayoutDashboard], ['/history','Trip history',RouteIcon], ['/earnings','Earnings',Wallet], ['/account','Your account',UserRound]], admin: [['','Overview',LayoutDashboard], ['/drivers','Drivers',CarFront], ['/rides','Rides',RouteIcon], ['/settings','Fare settings',Menu], ['/revenue','Revenue share',Wallet], ['/audit','Audit history',ShieldCheck], ['/account','Your account',UserRound]] };
function Workspace({ role }) {
  const { session,logout,signingOut,logoutError } = useContext(Auth), [open, setOpen] = useState(false);
  const user = session.user;
  return <div className="workspace"><aside className={`sidebar ${open ? 'open' : ''}`}><Brand/><div className="workspace-label">{role} workspace</div><nav>{navItems[role].map(([path,label,Icon])=><NavLink end key={path} to={`/${role}${path}`} onClick={()=>setOpen(false)}><Icon size={19}/>{label}<ChevronRight size={14}/></NavLink>)}</nav><div className="sidebar-bottom"><div><span className="avatar">{user.name.slice(0,1).toUpperCase()}</span><div><strong>{user.name}</strong><small>{user.user_code}</small></div></div>{logoutError && <p className="form-error" role="alert">{logoutError} Sign-out was not confirmed. Please retry.</p>}<button disabled={signingOut} onClick={()=>logout()}><LogOut size={18}/> {signingOut?'Signing out…':'Sign out'}</button></div></aside><div className="workspace-main"><header className="workspace-header"><button className="mobile-menu" aria-label="Toggle navigation" onClick={()=>setOpen(!open)}>{open ? <X/> : <Menu/>}</button><span>LET’S MAKE MOVES</span><div><span className="dev-dot"/> Development <span className="avatar small">{user.name.slice(0,1).toUpperCase()}</span></div></header><Routes><Route index element={<RideWorkspace role={role} user={user} token={session.access_token}/>}/>{['history','earnings','drivers','rides'].filter(view => role === 'admin' ? ['drivers','rides'].includes(view) : role === 'driver' ? ['history','earnings'].includes(view) : view === 'history').map(view=><Route key={view} path={view} element={<RideWorkspace role={role} user={user} token={session.access_token} view={view}/>}/>)}{role==='admin' && <Route path="settings" element={<FareSettings token={session.access_token}/>}/>}{role==='admin' && <Route path="revenue" element={<RevenueSettings token={session.access_token}/>}/>}{role==='admin' && <Route path="audit" element={<AdminAudit token={session.access_token}/>}/>}<Route path="account" element={<Account user={user}/>}/><Route path="*" element={<ComingSoon role={role}/>}/></Routes></div></div>;
}
function PageHeading({ eyebrow, title, text }) { return <div className="page-heading"><Tag>{eyebrow}</Tag><h1>{title}</h1><p>{text}</p></div>; }
function Account({ user }) {
  const {logout,signingOut,logoutError}=useContext(Auth);
  return <main className="dashboard"><PageHeading eyebrow="THE PERSON BEHIND THE JOURNEY" title="Your account." text="Your details, in one place."/><section className="account-panel">{[['Name',user.name],['Mobile',user.mobile],['Permanent code',user.user_code],['Workspace',user.role],['Account status',user.status]].map(([label,value])=><div key={label}><span>{label}</span><strong>{value}</strong></div>)}<button className="button dark" disabled={signingOut} onClick={()=>{if(window.confirm('Sign out all devices, including this one?'))logout(true);}}>{signingOut?'Signing out…':'Sign out all devices'}</button>{logoutError && <p className="form-error" role="alert">{logoutError}</p>}<p>Profile editing and account recovery will be introduced in a later milestone.</p></section></main>; }
function ComingSoon({ role }) { return <main className="dashboard"><PageHeading eyebrow="ONE STEP AT A TIME" title="More roads ahead." text="This part of your workspace is planned for an upcoming milestone."/><section className="empty-panel"><RouteIcon size={40}/><h2>We’re building the next chapter.</h2><p>No trips, payments, or operational changes have been made.</p><Link className="button dark" to={`/${role}`}>Back to overview <ArrowRight size={16}/></Link></section></main>; }
function App() { return <AuthProvider><BrowserRouter><Routes><Route path="/" element={<Landing/>}/><Route path="/test-payment/:token" element={<TestPaymentPage/>}/><Route path="/login" element={<AuthPage key="login"/>}/><Route path="/register" element={<AuthPage key="register" register/>}/>{['rider','driver','admin'].map(role=><Route key={role} path={`/${role}/*`} element={<Protected role={role}/>}/>)}<Route path="*" element={<main className="not-found"><Brand/><h1>Wrong turn?</h1><p>This page doesn’t exist. Let’s get you back on track.</p><Link to="/" className="button dark">Back to home <ArrowRight size={18}/></Link></main>}/></Routes></BrowserRouter></AuthProvider>; }
createRoot(document.getElementById('root')).render(<React.StrictMode><App/></React.StrictMode>);
