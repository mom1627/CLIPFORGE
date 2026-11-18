// CLIPFORGE Free – Twitch live clipper for Cloudflare Workers (no MP4 reposts).
const TWITCH = 'https://api.twitch.tv/helix';
const AUTH = 'https://id.twitch.tv/oauth2';
const TE = new TextEncoder();

function answer(data, status=200, headers={}) {
  return new Response(JSON.stringify(data), {
    status, headers: {'content-type':'application/json; charset=utf-8',
      'cache-control':'no-store','x-content-type-options':'nosniff',...headers}
  });
}
function errorText(error) { return String(error?.message || error).slice(0,250); }
function validateName(value) { return /^[a-z0-9_]{3,25}$/.test(value); }
function originCheck(request) {
  if (request.headers.get('origin') !== new URL(request.url).origin) throw new Error('Ungueltiger Origin');
}
function configCheck(env) {
  const missing = ['DB','ADMIN_PIN','SESSION_SECRET','TWITCH_CLIENT_ID','TWITCH_CLIENT_SECRET']
    .filter(k => !env[k]);
  if (missing.length) throw new Error('Fehlende Konfiguration: ' + missing.join(', '));
}
function nonce() {
  return Array.from(crypto.getRandomValues(new Uint8Array(24)),
    v=>v.toString(16).padStart(2,'0')).join('');
}
async function sign(secret, value) {
  const key = await crypto.subtle.importKey('raw',TE.encode(secret),
    {name:'HMAC',hash:'SHA-256'},false,['sign']);
  const signed = await crypto.subtle.sign('HMAC',key,TE.encode(value));
  return Array.from(new Uint8Array(signed),v=>v.toString(16).padStart(2,'0')).join('');
}
async function sessionCookie(env) {
  const exp = Math.floor(Date.now()/1000) + 14*86400;
  const value = 'v1.' + exp;
  const mac = await sign(env.SESSION_SECRET,value);
  return 'clipforge_session='+value+'.'+mac+
    '; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=1209600';
}
async function loggedIn(request,env) {
  if (!env.SESSION_SECRET) return false;
  const raw = request.headers.get('cookie') || '';
  const found = raw.match(/(?:^|;\s*)clipforge_session=(v1\.\d+\.[a-f0-9]{64})(?:;|$)/);
  if (!found) return false;
  const [version, exp, mac] = found[1].split('.');
  if (version !== 'v1' || +exp < Date.now()/1000) return false;
  const expected = await sign(env.SESSION_SECRET,version+'.'+exp);
  let changed=0;
  for(let i=0;i<64;i++) changed |= expected.charCodeAt(i)^mac.charCodeAt(i);
  return changed===0;
}
async function schema(db) {
  await db.prepare('CREATE TABLE IF NOT EXISTS twitch_auth (id INTEGER PRIMARY KEY CHECK(id=1), access_token TEXT NOT NULL, refresh_token TEXT NOT NULL, expires_at INTEGER NOT NULL)').run();
  await db.prepare('CREATE TABLE IF NOT EXISTS streamers (login TEXT PRIMARY KEY, twitch_id TEXT NOT NULL, auto_clip INTEGER NOT NULL DEFAULT 0, last_clip_at INTEGER NOT NULL DEFAULT 0)').run();
  await db.prepare("CREATE TABLE IF NOT EXISTS clips (id TEXT PRIMARY KEY, login TEXT NOT NULL, url TEXT NOT NULL, created_at INTEGER NOT NULL, mode TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending')").run();
  await db.prepare('CREATE TABLE IF NOT EXISTS oauth_states (state TEXT PRIMARY KEY, created_at INTEGER NOT NULL)').run();
  await db.prepare('CREATE TABLE IF NOT EXISTS login_attempts (client_key TEXT PRIMARY KEY, failures INTEGER NOT NULL DEFAULT 0, blocked_until INTEGER NOT NULL DEFAULT 0)').run();
  await db.prepare('CREATE TABLE IF NOT EXISTS clip_share (id TEXT PRIMARY KEY, edit_url TEXT NOT NULL, expires_at INTEGER NOT NULL)').run();
}
async function getToken(env) {
  const row = await env.DB.prepare('SELECT * FROM twitch_auth WHERE id=1').first();
  if (!row) throw new Error('Twitch ist noch nicht verbunden.');
  if (row.expires_at > Date.now()+120000) return row.access_token;
  const form = new URLSearchParams({client_id:env.TWITCH_CLIENT_ID,
    client_secret:env.TWITCH_CLIENT_SECRET, grant_type:'refresh_token',
    refresh_token:row.refresh_token});
  const result = await fetch(AUTH+'/token',{method:'POST',body:form});
  const data = await result.json();
  if (!result.ok || !data.access_token) throw new Error('Twitch-Token abgelaufen. Twitch erneut verbinden.');
  await env.DB.prepare('UPDATE twitch_auth SET access_token=?, refresh_token=?, expires_at=? WHERE id=1')
    .bind(data.access_token,data.refresh_token||row.refresh_token,Date.now()+data.expires_in*1000).run();
  return data.access_token;
}
async function twitch(env,endpoint,opts={}) {
  const headers = new Headers(opts.headers||{});
  headers.set('Authorization','Bearer '+await getToken(env));
  headers.set('Client-Id',env.TWITCH_CLIENT_ID);
  const r = await fetch(TWITCH+endpoint,{...opts,headers});
  const data = await r.json().catch(()=>({}));
  if(!r.ok) throw new Error('Twitch ('+r.status+'): '+(data.message||'API-Fehler'));
  return data;
}
async function streams(env,people) {
  if(!people.length) return new Map();
  const qs = new URLSearchParams();
  for (const p of people) qs.append('user_id',p.twitch_id);
  const r=await twitch(env,'/streams?'+qs);
  return new Map((r.data||[]).map(s=>[s.user_id,s]));
}
async function clip(env,person,mode,now=Date.now()) {
  let result;
  try {
    result=await twitch(env,'/clips?broadcaster_id='+encodeURIComponent(person.twitch_id),
      {method:'POST'});
  } catch(e) {
    if (/Twitch \(403\)/.test(String(e.message))) {
      throw new Error('Twitch verweigert Clips bei '+person.login+' (403). Oeffne twitch.tv/'+person.login+' und pruefe, ob du auf diesem Kanal Clips erstellen darfst (Follower-/Abo-Regeln, Clips deaktiviert oder Sperre).');
    }
    throw e;
  }
  const id=result.data?.[0]?.id;
  if(!id) throw new Error('Twitch hat keinen Clip erzeugt.');
  const url='https://clips.twitch.tv/'+encodeURIComponent(id);
  await env.DB.prepare('INSERT OR IGNORE INTO clips (id,login,url,created_at,mode,status) VALUES(?,?,?,?,?,?)')
    .bind(id,person.login,url,now,mode,'pending').run();
  if(result.data?.[0]?.edit_url) {
    const editUrl=result.data[0].edit_url;
    if(/^https:\/\/(clips\.twitch\.tv|www\.twitch\.tv|dashboard\.twitch\.tv)\//.test(editUrl))
      await env.DB.prepare('INSERT OR REPLACE INTO clip_share (id,edit_url,expires_at) VALUES(?,?,?)')
        .bind(id,editUrl,now+24*3600000).run();
  }
  await env.DB.prepare('UPDATE streamers SET last_clip_at=? WHERE login=?')
    .bind(now,person.login).run();
  return {id,url,login:person.login,status:'pending'};
}
async function verifyClips(env,now) {
  const pending=(await env.DB.prepare("SELECT id,created_at FROM clips WHERE status='pending' ORDER BY created_at DESC LIMIT 50").all()).results||[];
  if(!pending.length) return;
  const qs=new URLSearchParams();
  for(const entry of pending) qs.append('id',entry.id);
  const r=await twitch(env,'/clips?'+qs);
  const available=new Set((r.data||[]).map(x=>x.id));
  for(const entry of pending) {
    if(available.has(entry.id)) await env.DB.prepare("UPDATE clips SET status='ready' WHERE id=?")
      .bind(entry.id).run();
    else if(now-entry.created_at > 180000) await env.DB.prepare("UPDATE clips SET status='failed' WHERE id=?")
      .bind(entry.id).run();
  }
}
async function scan(env,auto=false) {
  const people=(await env.DB.prepare('SELECT * FROM streamers ORDER BY login LIMIT 30').all()).results||[];
  const active=await streams(env,people), now=Date.now();
  if(auto) try { await verifyClips(env,now); } catch(e) { console.error('Clip verification:',errorText(e)); }
  const interval=Math.max(15,Math.min(240,Number(env.CLIP_INTERVAL_MINUTES)||20))*60000;
  const list=[];
  for(const person of people) {
    const info=active.get(person.twitch_id);
    if(!info)continue;
    list.push({login:person.login,viewers:info.viewer_count||0});
    if(auto && person.auto_clip && now-person.last_clip_at>=interval) {
      try { await clip(env,person,'auto',now); }
      catch(e) { console.error('Auto-clip '+person.login+': '+errorText(e)); }
    }
  }
  return list;
}
async function login(request,env) {
  originCheck(request);
  const ip=request.headers.get('CF-Connecting-IP')||'unknown';
  const key=await sign(env.SESSION_SECRET,'login:'+ip);
  const attempt=await env.DB.prepare('SELECT * FROM login_attempts WHERE client_key=?').bind(key).first();
  if(attempt?.blocked_until>Date.now()) return answer({error:'Zu viele Versuche. In 15 Minuten erneut probieren.'},429);
  const input=await request.json().catch(()=>({}));
  if(!input.pin || input.pin!==env.ADMIN_PIN) {
    const failures=(attempt?.failures||0)+1;
    const until=failures>=5?Date.now()+15*60000:0;
    await env.DB.prepare('INSERT INTO login_attempts (client_key,failures,blocked_until) VALUES(?,?,?) ON CONFLICT(client_key) DO UPDATE SET failures=excluded.failures,blocked_until=excluded.blocked_until')
      .bind(key,failures,until).run();
    return answer({error:'Admin-Passwort falsch'},401);
  }
  await env.DB.prepare('DELETE FROM login_attempts WHERE client_key=?').bind(key).run();
  return answer({ok:true},200,{'set-cookie':await sessionCookie(env)});
}
async function route(request,env) {
  const url=new URL(request.url), path=url.pathname;
  if(path==='/health') return answer({ok:true,name:'CLIPFORGE Free'});
  if(path==='/' && request.method==='GET')
    return env.ASSETS ? env.ASSETS.fetch(request) : new Response('Dashboard noch nicht bereit', {status:503});
  configCheck(env);
  await schema(env.DB);
  if(path==='/login' && request.method==='POST') return login(request,env);
  if(!await loggedIn(request,env)) return answer({error:'Nicht angemeldet'},401);
  if(path==='/logout' && request.method==='POST') {
    originCheck(request);
    return answer({ok:true},200,{'set-cookie':'clipforge_session=; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=0'});
  }
  if(path==='/auth/twitch' && request.method==='GET') {
    const state=nonce();
    await env.DB.prepare('INSERT INTO oauth_states (state,created_at) VALUES(?,?)')
      .bind(state,Date.now()).run();
    await env.DB.prepare('DELETE FROM oauth_states WHERE created_at<?')
      .bind(Date.now()-600000).run();
    const qs=new URLSearchParams({client_id:env.TWITCH_CLIENT_ID,
      redirect_uri:url.origin+'/auth/callback',response_type:'code',scope:'clips:edit editor:manage:clips',state});
    return Response.redirect(AUTH+'/authorize?'+qs,302);
  }
  if(path==='/auth/callback' && request.method==='GET') {
    const state=url.searchParams.get('state'),code=url.searchParams.get('code');
    if(!state||!code)return answer({error:'Twitch-Anmeldung abgebrochen'},400);
    const saved=await env.DB.prepare('SELECT * FROM oauth_states WHERE state=?').bind(state).first();
    if(!saved || Date.now()-saved.created_at>600000)return answer({error:'Twitch-State abgelaufen'},403);
    await env.DB.prepare('DELETE FROM oauth_states WHERE state=?').bind(state).run();
    const form=new URLSearchParams({client_id:env.TWITCH_CLIENT_ID,
      client_secret:env.TWITCH_CLIENT_SECRET,code,
      redirect_uri:url.origin+'/auth/callback',grant_type:'authorization_code'});
    const response=await fetch(AUTH+'/token',{method:'POST',body:form});
    const data=await response.json();
    if(!response.ok || !data.access_token || !data.refresh_token)
      throw new Error('Twitch-OAuth fehlgeschlagen');
    await env.DB.prepare('INSERT INTO twitch_auth (id,access_token,refresh_token,expires_at) VALUES(1,?,?,?) ON CONFLICT(id) DO UPDATE SET access_token=excluded.access_token,refresh_token=excluded.refresh_token,expires_at=excluded.expires_at')
      .bind(data.access_token,data.refresh_token,Date.now()+data.expires_in*1000).run();
    return Response.redirect(url.origin+'/',302);
  }
  if(path==='/api/state' && request.method==='GET') {
    const connected=!!(await env.DB.prepare('SELECT id FROM twitch_auth WHERE id=1').first());
    const people=(await env.DB.prepare('SELECT login,twitch_id,auto_clip,last_clip_at FROM streamers ORDER BY login LIMIT 30').all()).results||[];
    const clips=(await env.DB.prepare('SELECT c.id,c.login,c.url,c.created_at,c.mode,c.status,sh.edit_url,sh.expires_at FROM clips c LEFT JOIN clip_share sh ON sh.id=c.id ORDER BY c.created_at DESC LIMIT 50').all()).results||[];
    for(const c of clips) if(c.expires_at && c.expires_at < Date.now()) c.edit_url=null;
    let live=[],warning=null;
    if(connected)try { live=await scan(env,false); } catch(e) { warning=errorText(e); }
    return answer({connected,people,clips,live,warning,interval:Math.max(15,Math.min(240,Number(env.CLIP_INTERVAL_MINUTES)||20))});
  }
  if(path==='/api/mp4' && request.method==='GET') {
    const clipId=url.searchParams.get('id')||'';
    if(!/^[A-Za-z0-9_-]{8,180}$/.test(clipId)) return answer({error:'Ungueltige Clip-ID'},400);
    const existing=await env.DB.prepare('SELECT id,login,status FROM clips WHERE id=?').bind(clipId).first();
    if(!existing) return answer({error:'Dieser Clip ist nicht in CLIPFORGE gespeichert.'},404);
    if(existing.status!=='ready') return answer({error:'Clip ist noch nicht erfolgreich auf Twitch verfuegbar.'},409);
    let streamer=await env.DB.prepare('SELECT twitch_id FROM streamers WHERE login=?').bind(existing.login).first();
    if(!streamer) {
      const look=await twitch(env,'/users?login='+encodeURIComponent(existing.login));
      if(!look.data?.[0]?.id) return answer({error:'Streamer nicht gefunden'},404);
      streamer={twitch_id:look.data[0].id};
    }
    const me=await twitch(env,'/users');
    const editorId=me.data?.[0]?.id;
    if(!editorId) return answer({error:'Twitch-Konto konnte nicht bestimmt werden.'},401);
    const qs=new URLSearchParams({broadcaster_id:streamer.twitch_id,editor_id:editorId,clip_id:clipId});
    let download;
    try {
      download=await twitch(env,'/clips/downloads?'+qs);
    }catch(e) {
      if(/Twitch \\(401\\)|Twitch \\(403\\)/.test(String(e.message)))
        return answer({error:'Twitch erlaubt diesen MP4-Download nur dem Kanalinhaber oder einem offiziell berechtigten Kanal-Editor. Bitte Twitch erneut verbinden, falls du bereits Editor bist.'},403);
      throw e;
    }
    const asset=(download.data||[]).find(x=>x.clip_id===clipId);
    const raw=asset?.portrait_download_url||asset?.landscape_download_url;
    if(!raw) return answer({error:'Kein freigegebener MP4-Download fuer diesen Clip verfuegbar.'},404);
    let assetUrl;
    try {assetUrl=new URL(raw);}catch {return answer({error:'Twitch lieferte einen ungueltigen Download-Link'},502);}
    if(assetUrl.protocol!=='https:' || !/(^|\\.)twitchcdn\\.net$/.test(assetUrl.hostname))
      return answer({error:'Unerwarteter Download-Host von Twitch'},502);
    return answer({url:assetUrl.href,format:asset.portrait_download_url?'portrait':'landscape',hint:'Twitch-Download-Link ist zeitlich begrenzt. In Safari gegebenenfalls Video gedrueckt halten und sichern.'});
  }
  if(request.method!=='POST') return answer({error:'Nicht gefunden'},404);
  originCheck(request);
  const input=await request.json().catch(()=>({}));
  let name=String(input.login||'').trim().replace(/^@/,'').toLowerCase();
  if(!validateName(name)) return answer({error:'Ungueltiger Twitch-Name'},400);
  if(path==='/api/add') {
    const count=await env.DB.prepare('SELECT COUNT(*) AS n FROM streamers').first();
    if(count.n>=30)return answer({error:'Maximal 30 Streamer'},400);
    const user=await twitch(env,'/users?login='+encodeURIComponent(name));
    if(!user.data?.[0])return answer({error:'Twitch-Konto nicht gefunden'},404);
    await env.DB.prepare('INSERT OR IGNORE INTO streamers (login,twitch_id) VALUES(?,?)')
      .bind(name,user.data[0].id).run();
    return answer({ok:true});
  }
  const person=await env.DB.prepare('SELECT * FROM streamers WHERE login=?').bind(name).first();
  if(!person)return answer({error:'Streamer nicht in der Watchlist'},404);
  if(path==='/api/remove') {
    await env.DB.prepare('DELETE FROM streamers WHERE login=?').bind(name).run();
    return answer({ok:true});
  }
  if(path==='/api/auto') {
    await env.DB.prepare('UPDATE streamers SET auto_clip=? WHERE login=?')
      .bind(person.auto_clip?0:1,name).run();
    return answer({ok:true,auto:!person.auto_clip});
  }
  if(path==='/api/clip') {
    const online=await streams(env,[person]);
    if(!online.has(person.twitch_id))return answer({error:'Streamer ist offline'},409);
    if(Date.now()-person.last_clip_at<60000)return answer({error:'60 Sekunden Pause zwischen Clips'},429);
    return answer(await clip(env,person,'manual'));
  }
  return answer({error:'Nicht gefunden'},404);
}
export default {
  async fetch(request,env) {
    try {return await route(request,env);}
    catch(e) {console.error(errorText(e)); return answer({error:errorText(e)},500);}
  },
  async scheduled(event,env) {
    try {
      configCheck(env);
      await schema(env.DB);
      const auth=await env.DB.prepare('SELECT id FROM twitch_auth WHERE id=1').first();
      if(auth) await scan(env,true);
    } catch(e) {console.error('Cron:',errorText(e));}
  }
};
export const testing={validateName,sign,sessionCookie,loggedIn};
