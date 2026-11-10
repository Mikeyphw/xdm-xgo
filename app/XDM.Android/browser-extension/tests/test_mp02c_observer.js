'use strict';
// Real production observer+store under simulated privileged Firefox webRequest chronology.
// EXT02/05/07/08/09/10/12 positive + negative runtime receipts.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const ext=path.join(__dirname,'..','src','main','extension','xdm-firefox');
const event=()=>({callbacks:[],addListener(fn){this.callbacks.push(fn)}});
const e={before:event(),sent:event(),headers:event(),complete:event(),error:event(),
  changed:event(),message:event(),commit:event(),updated:event(),removed:event()};
let currentUrl='https://allowed.example/watch', reviewStarts=0, pairedCalls=0;
let pausePair=false, releasePair;
// Await the actual capture-session entry signal; two Promise microtasks are NOT
// a contract for the Firefox runtime's asynchronous handoff schedule. The
// competing outcome surfaces pre-handoff failures immediately and the timer
// refuses a handoff that genuinely never starts.
async function awaitPairedHandoffStarted(entered, running, timeoutMs=2500) {
  let timer;
  try {
    const outcome=await Promise.race([
      entered.then(()=>({state:'started'})),
      running.then(result=>({state:'exited',result}),error=>({state:'rejected',error:String(error)})),
      new Promise(resolve=>{timer=setTimeout(()=>resolve({state:'timeout'}),timeoutMs)})
    ]);
    assert.equal(outcome.state,'started',
      'paired handoff did not begin: '+JSON.stringify(outcome));
  } finally {if(timer!==undefined)clearTimeout(timer)}
}
const settings={};
const browser={
  storage:{local:{async get(key){return typeof key==='string'?{[key]:settings[key]}:settings;},async set(data){Object.assign(settings,data)}},onChanged:e.changed},
  runtime:{onMessage:e.message},
  webRequest:{onBeforeSendHeaders:e.before,onSendHeaders:e.sent,onHeadersReceived:e.headers,
    onCompleted:e.complete,onErrorOccurred:e.error},
  webNavigation:{onCommitted:e.commit}, browserAction:{async setBadgeText(){}},
  tabs:{onRemoved:e.removed,onUpdated:e.updated,
    async get(id){return {id,url:currentUrl,title:'MP02C fixture'};},
    async executeScript(id,args){if(String(args.code||'').includes('location.href ='))reviewStarts++;return [true]}}
};
const c=vm.createContext({browser,console,URL,URLSearchParams,Date,JSON,Promise,Math,Map,Set,Object,
  Number,String,Uint8Array,setTimeout,clearTimeout});c.globalThis=c;
for(const name of ['detector-core.js','candidate-store.js','network-observer.js'])
  vm.runInContext(fs.readFileSync(path.join(ext,name),'utf8'),c,{filename:name});
c.XdmHandoffV1={async buildCaptureSession(){pairedCalls++;if(pausePair)return new Promise(resolve=>{releasePair=()=>resolve('xdm://capture?opaque=1')});return 'xdm://capture?opaque=1';},
  buildOneDm(){return 'one-dm://capture'} };
const recv=e.message.callbacks[0], sender=(tab,frame)=>({tab:{id:tab,url:currentUrl},frameId:frame,url:currentUrl});
const chooser=async tab=>(await recv({type:'xdmGetLogicalCandidatesV2',tabId:tab},{})).candidates;
const send=(tab,id,target='xdm')=>Promise.resolve(recv({type:target==='xdm'?'xdmSendLogicalCandidatesV2':'xdmSendLogicalCandidatesTo1DmV1',tabId:tab,logicalMediaIds:[id]},{}));
function request(tab,frame,requestId,url,mime='application/vnd.apple.mpegurl',sentUrl=url){
  const info={tabId:tab,frameId:frame,requestId,url,documentUrl:currentUrl,
    requestHeaders:[{name:'Authorization',value:'Bearer SUPER_SECRET'},
      {name:'Cookie',value:'SESSION=SUPER_SECRET'}]};
  e.before.callbacks[0](info);
  e.sent.callbacks[0](Object.assign({},info,{url:sentUrl}));
  e.headers.callbacks[0]({tabId:tab,frameId:frame,requestId,url,documentUrl:currentUrl,
    type:'xmlhttprequest',responseHeaders:[{name:'Content-Type',value:mime}]});
}
const playback=(tab,frame,data)=>recv({type:'xdmFramePlaybackV1',candidate:data},sender(tab,frame));
const page=(tab,frame,data)=>recv({type:'xdmPageObservationV1',observation:data},sender(tab,frame));
(async()=>{
  await Promise.resolve();
  // EXT02/11: opaque MIME is strong, but a forged page JSON/manifest string isn't.
  const opaque='https://cdn.example/resource?token=TOP_SECRET';
  request(1,2,'opaque',opaque,'application/vnd.apple.mpegurl');
  let all=await chooser(1); assert.equal(all.length,1);assert.equal(all[0].streamKind,'hls');
  assert.ok(!JSON.stringify(all).includes('TOP_SECRET'));
  assert.ok(!JSON.stringify(all).includes('SUPER_SECRET'));
  assert.ok(all[0].url.endsWith('/xdm-detected-media'));
  request(2,1,'json','https://cdn.example/media-api','application/json');
  page(2,1,{responseUrl:'https://cdn.example/media-api',contentType:'application/vnd.apple.mpegurl',
    bodyExcerpt:'#EXTM3U\n#EXT-X-TARGETDURATION:4\n#EXTINF:4\npart.ts'});
  assert.equal((await chooser(2)).length,0,'forged page MIME/body created candidate');
  // EXT08/05: only one same-frame, recent MIME manifest may tentatively correlate.
  assert.equal(playback(1,2,{blobPlayback:true,observedAt:Date.now()}),true);
  all=await chooser(1);
  assert.equal(all.length,1);
  assert.equal(all[0].playbackCorrelation,'tentative-same-frame-network');
  assert.equal(all[0].playbackObserved,false);
  assert.equal(playback(1,8,{blobPlayback:true}),false,'iframe mismatch');
  request(1,2,'another','https://cdn.example/second.mpd','application/dash+xml');
  assert.equal(playback(1,2,{blobPlayback:true}),false,'two manifests are ambiguous');
  assert.equal((await chooser(1)).length,2);
  // EXT12: redirect requestId reused with cross-origin response cannot carry final sent headers.
  request(3,0,'redirect','https://different.example/redirected.m3u8',
    'application/vnd.apple.mpegurl','https://original.example/old.m3u8');
  assert.equal((await chooser(3)).length,1);
  const sendId=(await chooser(3))[0].logicalMediaId;
  const captureArgs=[];
  c.XdmHandoffV1.buildCaptureSession=async args=>{pairedCalls++;captureArgs.push(args);return 'xdm://capture?opaque=1'};
  const result=await send(3,sendId);
  assert.equal(result.ok,true);
  assert.equal(reviewStarts,1);
  assert.equal(Object.keys(captureArgs[0].candidates[0].headers||{}).length,0,'cross-hop Authorization leaked');
  // EXT10: rapid FAB+popup sends target same exact logical ID; one Android review start.
  request(4,0,'single','https://cdn.example/video.m3u8?sig=PRIVATE','application/vnd.apple.mpegurl');
  const id=(await chooser(4))[0].logicalMediaId;
  const before=reviewStarts;
  const responses=await Promise.all([send(4,id),send(4,id),send(4,id)]);
  assert.equal(responses[0].ok,true);
  assert.equal(responses[1].deduplicated,true);
  assert.equal(responses[2].sentCount,0);
  assert.equal(reviewStarts,before+1,'duplicated Android review');
  assert.equal((await send(4,id)).sentCount,0,'settled quick re-click duplicated Android review');
  // External 1DM+ intents have no encrypted-v2 protection: refuse signed URLs.
  const oneDmSigned=await send(4,id,'1dm');
  assert.equal(oneDmSigned.ok,false);
  assert.match(oneDmSigned.error,/Signed media URLs require XDM encrypted capture/);
  const beforeOneDm=reviewStarts;
  request(6,0,'authenticated','https://cdn.example/direct.mp4','video/mp4');
  const oneDmPrivateId=(await chooser(6))[0].logicalMediaId;
  const oneDmPrivate=await send(6,oneDmPrivateId,'1dm');
  assert.equal(oneDmPrivate.ok,false);
  assert.match(oneDmPrivate.error,/cannot safely receive authenticated request headers/);
  assert.equal(reviewStarts,beforeOneDm,'private 1DM+ intent navigated browser');
  // EXT09: frame navigation, site modes and tab close retire authority.
  e.commit.callbacks[0]({tabId:4,frameId:0});
  assert.equal((await chooser(4)).length,0);
  request(4,0,'fresh','https://cdn.example/new.m3u8','application/vnd.apple.mpegurl');
  e.changed.callbacks[0]({settings:{newValue:{enabled:false,autoDetectPlayingVideos:true,siteMode:'all'}}},'local');
  assert.equal((await chooser(4)).length,0);
  assert.equal(playback(4,0,{blobPlayback:true}),false);
  e.changed.callbacks[0]({settings:{newValue:{enabled:true,autoDetectPlayingVideos:true,siteMode:'whitelist',whitelist:['allowed.example']}}},'local');
  currentUrl='https://blocked.example/watch';
  assert.equal(page(4,0,{responseUrl:'https://cdn.example/new.m3u8'}),false);
  currentUrl='https://allowed.example/watch';
  e.changed.callbacks[0]({settings:{newValue:{enabled:true,autoDetectPlayingVideos:true,siteMode:'all'}}},'local');
  request(7,0,'pending','https://cdn.example/pending.m3u8','application/vnd.apple.mpegurl');
  const pending=(await chooser(7))[0].logicalMediaId;
  // Navigation race: async paired encryption may complete only AFTER tab changed.
  pausePair=true;
  let signalPairEntry;
  const pairingStarted=new Promise(resolve=>{signalPairEntry=resolve});
  c.XdmHandoffV1.buildCaptureSession=async()=>new Promise(resolve=>{
    releasePair=()=>resolve('xdm://capture?opaque=1');
    signalPairEntry();
  });
  const running=send(7,pending);
  await awaitPairedHandoffStarted(pairingStarted,running);
  assert.equal(typeof releasePair,'function','paired handoff entry signal did not install release callback');
  currentUrl='https://different.example/next';
  releasePair();
  const failed=await running;
  assert.equal(failed.ok,false);
  assert.ok(/changed during review/i.test(failed.error));
  assert.equal(reviewStarts,beforeOneDm,'navigation race sent review to wrong page');
  e.removed.callbacks[0](7);
  assert.equal((await chooser(7)).length,0);
  // EXT07: two requests in one millisecond keep distinct generations and freshness.
  currentUrl='https://allowed.example/watch';
  const urlOld='https://cdn.example/same.m3u8?token=old';
  const urlNew='https://cdn.example/same.m3u8?token=new';
  function beforeSame(id,url) {
    e.before.callbacks[0]({tabId:8,frameId:0,requestId:id,url,documentUrl:currentUrl,requestHeaders:[]});
    e.sent.callbacks[0]({tabId:8,frameId:0,requestId:id,url,documentUrl:currentUrl,requestHeaders:[]});
  }
  beforeSame('old-same-ms',urlOld);beforeSame('new-same-ms',urlNew);
  function replySame(id,url) {
    e.headers.callbacks[0]({tabId:8,frameId:0,requestId:id,url,documentUrl:currentUrl,
      type:'xmlhttprequest',responseHeaders:[{name:'Content-Type',value:'application/vnd.apple.mpegurl'}]});
  }
  replySame('new-same-ms',urlNew);replySame('old-same-ms',urlOld);
  const chooser8=await chooser(8);
  assert.equal(chooser8.length,1,'same logical video duplicated by token rotation');
  c.XdmHandoffV1.buildCaptureSession=async args=>{captureArgs.push(args);return 'xdm://capture?opaque=1'};
  const send8=await send(8,chooser8[0].logicalMediaId);
  assert.equal(send8.ok,true,send8.error);
  assert.equal(captureArgs.at(-1).candidates[0].url,urlNew,'delayed old request rolled back same-ms signed URL');
  // Negative: opaque query keys are not provably safe to expose in an external 1DM+ URL.
  request(9,0,'opaque-query','https://cdn.example/direct.mp4?k=PRIVATE','video/mp4');
  const queryId=(await chooser(9))[0].logicalMediaId;
  assert.equal((await send(9,queryId,'1dm')).ok,false,'opaque query leaked into 1DM+ intent');
  // Positive: truly plain URLs remain usable with the documented 1DM+ custom scheme.
  request(10,0,'plain','https://cdn.example/plain.mp4','video/mp4');
  const plainId=(await chooser(10))[0].logicalMediaId;
  // This fixture sends private headers by default, so add a clean final-sent request.
  e.before.callbacks[0]({tabId:11,frameId:0,requestId:'public',url:'https://cdn.example/public.mp4',
    documentUrl:currentUrl,requestHeaders:[]});
  e.sent.callbacks[0]({tabId:11,frameId:0,requestId:'public',url:'https://cdn.example/public.mp4',
    documentUrl:currentUrl,requestHeaders:[]});
  e.headers.callbacks[0]({tabId:11,frameId:0,requestId:'public',url:'https://cdn.example/public.mp4',
    documentUrl:currentUrl,type:'xmlhttprequest',responseHeaders:[{name:'Content-Type',value:'video/mp4'}]});
  const publicId=(await chooser(11))[0].logicalMediaId;
  const publicSend=await send(11,publicId,'1dm');
  assert.equal(publicSend.ok,true,publicSend.error);
  console.log('MP02C_OBSERVER_RUNTIME_PASS EXT02/05/08/09/10/11/12: forged hints, blob correlation, redirect, one send, navigation');
})().catch(err=>{console.error(err.stack||err);process.exitCode=1});
