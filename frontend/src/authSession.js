// Access tokens live only in memory. The refresh cookie is HttpOnly.
let session=null, pendingRefresh=null, generation=0, signingOut=false;
const listeners=new Set(), knownTokens=new Set();
const channel=typeof BroadcastChannel !== 'undefined' ? new BroadcastChannel('ridez-auth') : null;
export const currentSession=()=>session;
export const subscribeSession=listener=>{listeners.add(listener);return ()=>listeners.delete(listener);};
function publish(value) {
  session=value;
  if(value)knownTokens.add(value.access_token);
  else knownTokens.clear();
  listeners.forEach(listener=>listener(value));
}
channel?.addEventListener('message',event=>{
  if(event.data==='signed-out'){generation++;publish(null);}
});
const locked=action=>globalThis.navigator?.locks ? navigator.locks.request('ridez-refresh-cookie',action) : action();
async function request(path,body,token) {
  const response=await fetch(`/api/v1/auth/${path}`,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-Session-Request':'1',...(token?{Authorization:`Bearer ${token}`}:{})},body:JSON.stringify(body || {})});
  let data;
  try{data=await response.json();}catch{data={error:'Unable to contact the session service. Please retry.'};}
  if(!response.ok){const error=new Error(data.error || 'Unable to update your session. Please retry.');error.status=response.status;throw error;}
  return data;
}
export function resolveToken(token) {
  if(!token)return undefined;
  if(!session || !knownTokens.has(token))throw new Error('Your session changed. Please retry from your current workspace.');
  return session.access_token;
}
export function refreshSession() {
  if(signingOut)return Promise.reject(new Error('Sign-out is in progress.'));
  if(pendingRefresh)return pendingRefresh;
  const started=generation;
  const task=locked(async()=>{
    if(signingOut || started!==generation)return session;
    try {
      const data=await request('refresh');
      if(started===generation)publish(data);
      return started===generation?data:session;
    } catch(error) {
      if(error.status===401 && started===generation){generation++;publish(null);return null;}
      throw error;
    }
  });
  pendingRefresh=task.finally(()=>{pendingRefresh=null;});
  return pendingRefresh;
}
export async function signIn(fields) {
  return locked(async()=>{
    const data=await request('login',fields);
    generation++;knownTokens.clear();publish(data);return data;
  });
}
export async function signOut(allDevices=false) {
  if(signingOut)return;
  signingOut=true;
  try {
    await locked(async()=>{
      let token=session?.access_token;
      if(allDevices){
        const data=await request('refresh');token=data.access_token;publish(data);
      }
      // Logout remains available with an expired access token.
      if(allDevices && token)await request('logout-all',{},token);
      else await request('logout',{},token);
      generation++;publish(null);channel?.postMessage('signed-out');
    });
  } finally {signingOut=false;}
}
