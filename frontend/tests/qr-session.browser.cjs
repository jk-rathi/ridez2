// Run against Vite: RIDEZ_TEST_URL=http://127.0.0.1:5189 node tests/qr-session.browser.cjs
// Requires Playwright and Chromium (PLAYWRIGHT_MODULE / CHROMIUM_PATH may override locations).
const assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || '/opt/codex/cua_node/lib/node_modules/playwright');
(async()=>{
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH || '/usr/bin/chromium',args:['--no-sandbox']});
 try {
  const page=await browser.newPage();
  let refreshes=0, requests=[];
  const user={name:'Test rider',user_code:'RID-TEST',role:'rider',status:'active'};
  await page.route('**/api/v1/**',async route=>{
   const path=new URL(route.request().url()).pathname;
   let json;
   if(path==='/api/v1/auth/login')json={access_token:'initial-token',expires_at:Date.now()/1000+900,user};
   else if(path==='/api/v1/auth/refresh'){refreshes++;json={access_token:'renewed-token',expires_at:Date.now()/1000+900,user};}
   else if(path==='/api/v1/workspace')json={user,route_provider:'simulator',rides:[{id:'test-ride',status:'COMPLETED',quote:{total:'137.66',base:'100',distance_fare:'30',time_fare:'7.66',pickup:'A',destination:'B',provider:'simulator'},test_payments_enabled:true}]};
   else if(path==='/api/v1/rides/test-ride/test-payment'){
    const auth=route.request().headers().authorization;requests.push(auth);
    if(auth!=='Bearer renewed-token')return route.fulfill({status:401,json:{error:'Please sign in again'}});
    json={payment:{status:'PENDING',amount:'137.66',currency:'INR',test_only:true},path:'/test-payment/signed-test-token'};
   }else return route.fulfill({status:404,json:{error:'Unknown fixture endpoint'}});
   return route.fulfill({json});
  });
  await page.goto(process.env.RIDEZ_TEST_URL || 'http://127.0.0.1:5189');
  await page.waitForFunction(async()=>{const auth=await import('/src/authSession.js');return auth.currentSession()?.access_token==='renewed-token';});
  refreshes=0;
  await page.evaluate(async()=>{
   const {default:React}=await import('/node_modules/.vite/deps/react.js');
   const {default:{createRoot}}=await import('/node_modules/.vite/deps/react-dom_client.js');
   const auth=await import('/src/authSession.js');
   const {default:Workspace}=await import('/src/RideWorkspace.jsx');
   const session=await auth.signIn({mobile:'test',password:'test'});
   const host=document.createElement('div');document.body.replaceChildren(host);
   createRoot(host).render(React.createElement(Workspace,{role:'rider',user:session.user,token:session.access_token,view:'history'}));
  });
  await page.getByRole('button',{name:'Pay by QR (test)',exact:true}).click();
  await page.getByRole('img',{name:/Scan to simulate payment/}).waitFor();
  assert.deepEqual(requests,['Bearer initial-token','Bearer renewed-token']);
  assert.equal(refreshes,1);
  assert.match(await page.getByRole('img',{name:/Scan to simulate payment/}).getAttribute('src'),/^data:image\/png;base64,/);
  await page.getByRole('button',{name:'Refresh test QR',exact:true}).click();
  await page.getByRole('button',{name:'Refresh test QR',exact:true}).waitFor({state:'visible'});
  assert.equal(await page.getByText('Please sign in again',{exact:true}).count(),0);
  console.log('PASS: rider history sends session token, refreshes an expired token, and displays QR.');
 } finally{await browser.close();}
})().catch(error=>{console.error(error);process.exit(1);});
