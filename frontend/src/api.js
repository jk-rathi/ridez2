import { currentSession, refreshSession, resolveToken } from './authSession';

export async function api(path, { token, ...options } = {}) {
  const activeToken=resolveToken(token);
  async function send(accessToken) {
    return fetch(`/api/v1${path}`, { ...options, credentials:'same-origin', headers: { 'Content-Type': 'application/json', ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}), ...options.headers } });
  }
  let response=await send(activeToken);
  if(response.status===401 && activeToken && !options.signal?.aborted) {
    // Refresh is shared across concurrent requests and serialized across tabs.
    const renewed=currentSession()?.access_token!==activeToken ? currentSession() : await refreshSession();
    if(renewed && resolveToken(token))response=await send(renewed.access_token);
  }
  let data;
  try{data=await response.json();}catch{throw new Error('Unable to read the server response. Please retry.');}
  if(!response.ok)throw new Error(data.error || 'Something went wrong. Please try again.');
  return data;
}
