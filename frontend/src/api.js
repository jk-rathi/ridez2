import { currentSession, refreshSession, resolveToken } from './authSession';
import { secureFetch } from './secureChannel';

export async function api(path, { token, ...options } = {}) {
  const activeToken=resolveToken(token);
  async function send(accessToken) {
    return secureFetch(`/api/v1${path}`, { ...options, credentials:'same-origin', headers: { 'Content-Type': 'application/json', ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}), ...options.headers } });
  }
  let {response,data}=await send(activeToken);
  if(response.status===401 && activeToken && !options.signal?.aborted) {
    // Refresh is shared across concurrent requests and serialized across tabs.
    const renewed=currentSession()?.access_token!==activeToken ? currentSession() : await refreshSession();
    if(renewed && resolveToken(token))({response,data}=await send(renewed.access_token));
  }
  if(data===undefined)throw new Error('Unable to read the server response. Please retry.');
  if(!response.ok)throw new Error(data.error || 'Something went wrong. Please try again.');
  return data;
}
