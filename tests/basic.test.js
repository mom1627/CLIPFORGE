import test from 'node:test';
import assert from 'node:assert/strict';
import worker,{testing} from '../src/index.js';

const host='https://clipforge-live-free.example.workers.dev';

test('Twitch logins are restricted to safe characters',()=>{
 for(const name of ['xqc','kaicenat','montanablack88','caseoh_']) assert.equal(testing.validateName(name),true);
 for(const name of ['', 'x','../../file','a b','<script>']) assert.equal(testing.validateName(name),false);
});
test('HMAC session cookie validates and rejects tampering',async()=>{
 const env={SESSION_SECRET:'very-long-example-session-secret-for-testing'};
 const cookie=await testing.sessionCookie(env);
 assert.equal(await testing.loggedIn(new Request(host,{headers:{cookie}}),env),true);
 const wrong=cookie.replace(/([a-f0-9]{64})/,p=>p[0]==='a'?'b'+p.slice(1):'a'+p.slice(1));
 assert.equal(await testing.loggedIn(new Request(host,{headers:{cookie:wrong}}),env),false);
});
test('health endpoint is available without secrets',async()=>{
 const response=await worker.fetch(new Request(host+'/health'),{});
 assert.equal(response.status,200);
 assert.equal((await response.json()).ok,true);
});
test('private API rejects unauthenticated users',async()=>{
 const db={prepare(){return {run:async()=>({}),first:async()=>null,all:async()=>({results:[]})}}};
 const env={DB:db,ADMIN_PIN:'some-long-passphrase',
  SESSION_SECRET:'very-long-example-session-secret-for-testing',
  TWITCH_CLIENT_ID:'test-id',TWITCH_CLIENT_SECRET:'test-secret'};
 const response=await worker.fetch(new Request(host+'/api/state'),env);
 assert.equal(response.status,401);
 assert.equal((await response.json()).error,'Nicht angemeldet');
});
test('dashboard is served via static assets binding',async()=>{
 let seen=false;
 const env={ASSETS:{fetch:async request=>{seen=true;return new Response('<html>CLIPFORGE</html>');}}};
 const response=await worker.fetch(new Request(host+'/'),env);
 assert.equal(response.status,200);
 assert.equal(seen,true);
 assert.match(await response.text(),/CLIPFORGE/);
});
