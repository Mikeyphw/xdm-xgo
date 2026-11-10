'use strict';
// MP02B: REAL browser-observer and candidate-store modules under a mocked Firefox API.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.join(__dirname, '..', 'src', 'main', 'extension', 'xdm-firefox');
const event = () => ({ callbacks: [], addListener(fn) { this.callbacks.push(fn); } });
const e = {
  before: event(), sent: event(), headers: event(), complete: event(), error: event(),
  changed: event(), message: event(), commit: event(), updated: event(), removed: event()
};
const settings = {};
const browser = {
  storage: {
    local: { async get(key) { return typeof key === 'string' ? { [key]: settings[key] } : settings; },
      async set(data) { Object.assign(settings, data); } },
    onChanged: e.changed
  },
  runtime: { onMessage: e.message },
  webRequest: { onBeforeSendHeaders: e.before, onSendHeaders: e.sent,
    onHeadersReceived: e.headers, onCompleted: e.complete, onErrorOccurred: e.error },
  webNavigation: { onCommitted: e.commit },
  browserAction: { async setBadgeText() {} },
  tabs: { onRemoved: e.removed, onUpdated: e.updated,
    async get(id) { return { id, url: 'https://allowed.example/watch', title: 'MP02B test' }; },
    async executeScript() { return [true]; } }
};
const ctx = vm.createContext({ console, browser, URL, URLSearchParams, Date, JSON,
  setTimeout, clearTimeout, Promise, Object, Number, String, Map, Set, Math });
ctx.globalThis = ctx;
for (const name of ['detector-core.js','candidate-store.js','network-observer.js']) {
  vm.runInContext(fs.readFileSync(path.join(root,name),'utf8'),ctx,{filename:name});
}
assert.equal(e.message.callbacks.length,1,'page observation receiver must register synchronously');
assert.equal(e.headers.callbacks.length,1);
assert.equal(e.changed.callbacks.length,1);
assert.equal(e.commit.callbacks.length,1);
assert.equal(e.updated.callbacks.length,1);
const recv=e.message.callbacks[0];
const chooser=async tabId=>recv({type:'xdmGetLogicalCandidatesV2',tabId},{});
function response(tabId,frameId,requestId,url,documentUrl='https://allowed.example/watch') {
  e.headers.callbacks[0]({tabId,frameId,requestId,url,documentUrl,type:'xmlhttprequest',
    responseHeaders:[{name:'Content-Type',value:'application/vnd.apple.mpegurl'}]});
}
function before(tabId,frameId,requestId,url='https://cdn.example/master.m3u8?sig=private') {
  e.before.callbacks[0]({tabId,frameId,requestId,url,
    documentUrl:'https://allowed.example/watch',
    requestHeaders:[{name:'Authorization',value:'Bearer ephemeral'}]});
}
function change(value) { e.changed.callbacks[0]({settings:{newValue:value}},'local'); }
(async()=>{
  await Promise.resolve();
  // Initial evidence and two isolated frames.
  before(5,2,'frame2');
  response(5,2,'frame2','https://cdn.example/master.m3u8?sig=frame2');
  before(5,9,'frame9');
  response(5,9,'frame9','https://cdn.example/master.m3u8?sig=frame9');
  assert.equal((await chooser(5)).candidates.length,2,'two frames must be separate candidates');
  e.commit.callbacks[0]({tabId:5,frameId:2});
  assert.equal((await chooser(5)).candidates.length,1,'iframe commit removes only its frame');
  // Disabling collection revokes all previously accumulated header/evidence/offer state.
  change({enabled:false,autoDetectPlayingVideos:true,siteMode:'all',blacklist:[],whitelist:[]});
  assert.equal((await chooser(5)).candidates.length,0,'disabling must revoke existing signed candidates');
  response(5,9,'after-disabled','https://cdn.example/master.m3u8?sig=denied');
  const injected=recv({type:'xdmPageObservationV1',observation:{responseUrl:'https://cdn.example/master.m3u8?sig=frame9',
    bodyExcerpt:'#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1\nchild.m3u8'}},
    {tab:{id:5,url:'https://allowed.example/watch'},frameId:9,url:'https://allowed.example/watch'});
  assert.equal(injected,false,'late page hints must not bypass disabled settings');
  assert.equal((await chooser(5)).candidates.length,0);
  // Re-enable but restrict site: CDN URL alone cannot imply site permission.
  change({enabled:true,autoDetectPlayingVideos:true,siteMode:'whitelist',whitelist:['allowed.example'],blacklist:[]});
  response(6,0,'no-document','https://cdn.example/video/master.m3u8?sig=x','');
  assert.equal((await chooser(6)).candidates.length,0,'unknown document origin fails closed');
  response(6,0,'blocked-document','https://cdn.example/video/master.m3u8?sig=y','https://blocked.example/watch');
  assert.equal((await chooser(6)).candidates.length,0,'non-allowlisted document cannot contribute');
  response(6,0,'allowed-document','https://cdn.example/video/master.m3u8?sig=z','https://allowed.example/watch');
  assert.equal((await chooser(6)).candidates.length,1,'allowlisted document is accepted');
  change({enabled:true,autoDetectPlayingVideos:true,siteMode:'blacklist',whitelist:[],blacklist:['allowed.example']});
  assert.equal((await chooser(6)).candidates.length,0,'switching site-mode retires stale rows');
  response(6,0,'blacklisted','https://cdn.example/video/master.m3u8?sig=z','https://allowed.example/watch');
  assert.equal((await chooser(6)).candidates.length,0);
  // A new policy and a full navigation both require new privileged evidence.
  change({enabled:true,autoDetectPlayingVideos:true,siteMode:'all',whitelist:[],blacklist:[]});
  before(7,0,'pending-before-navigation');
  e.updated.callbacks[0](7,{status:'loading'});
  response(7,0,'fresh','https://cdn.example/master.m3u8?sig=fresh');
  assert.equal((await chooser(7)).candidates.length,1);
  e.commit.callbacks[0]({tabId:7,frameId:0});
  assert.equal((await chooser(7)).candidates.length,0,'top-level navigation clears all frame rows');
  response(7,0,'fresh-new','https://cdn.example/master.m3u8?sig=next');
  e.removed.callbacks[0](7);
  assert.equal((await chooser(7)).candidates.length,0,'tab close retires rows');
  change({enabled:false,autoDetectPlayingVideos:false,siteMode:'all',whitelist:[],blacklist:[]});
  // Dedicated store primitive must clear all four maps (including privileged evidence).
  const store=new ctx.XdmCandidateStoreV1();
  store.merge(10,{url:'https://cdn.example/master.m3u8',frameId:0,requestId:'p',requestGeneration:3,
    confidence:950,quality:'strong'});
  assert.equal(store.size(10),1);
  const tabs=store.clearAll();
  assert.deepEqual(Array.from(tabs),[10]);
  assert.equal(store.size(10),0);
  assert.equal(store.evidence.size,0);
  assert.equal(store.aliases.size,0);
  assert.equal(store.stats.size,0);
  console.log('MP02B_SITE_MODE_RUNTIME_PASS: permission revocation, no-origin/denied-frame guards, navigation and evidence retirement');
})().catch(err=>{console.error(err.stack||err);process.exitCode=1;});
