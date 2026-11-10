'use strict';
// MP02C executable EXT matrix: production detector and candidate-store, no copied mock implementations.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ext = path.join(__dirname, '..', 'src', 'main', 'extension', 'xdm-firefox');
const c = vm.createContext({URL, URLSearchParams, Date, Math, Map, Set, Object, Number, String, JSON});
c.globalThis = c;
for (const filename of ['detector-core.js', 'candidate-store.js'])
  vm.runInContext(fs.readFileSync(path.join(ext, filename), 'utf8'), c, {filename});
const core = c.XdmDetectorCoreV1;
const store = new c.XdmCandidateStoreV1({maxPerTab: 16});
const hls = '#EXTM3U\n#EXT-X-VERSION:6\n#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="main",NAME="English",LANGUAGE="en",URI="audio/en.m3u8"\n#EXT-X-STREAM-INF:BANDWIDTH=900000,RESOLUTION=1280x720,AUDIO="main"\nvideo/720.m3u8\n#EXT-X-STREAM-INF:BANDWIDTH=1500000,RESOLUTION=1920x1080,AUDIO="main"\nvideo/1080.m3u8\n';
const mpd = '<?xml version="1.0"?><MPD><Period><AdaptationSet id="v" mimeType="video/mp4"><Representation id="720p" width="1280" height="720" bandwidth="900000"><BaseURL>video/</BaseURL></Representation></AdaptationSet><AdaptationSet id="a" mimeType="audio/mp4" lang="en"><Representation id="en" bandwidth="128000"><BaseURL>audio/</BaseURL></Representation></AdaptationSet></Period></MPD>';
const rootHls = 'https://cdn.example/vod?id=1&token=secret1';
const childHls = 'https://cdn.example/video/720.m3u8';
const rootDash = 'https://cdn.example/opaque?id=2&sig=secret';
function insert(tab,url, frame=0, requestId='r', gen=100, extra={}) {
  return store.merge(tab,Object.assign({url,contentType:'application/vnd.apple.mpegurl',frameId:frame,
    source:'webRequest',requestId,requestGeneration:gen,quality:'strong',confidence:1100,
    reason:'manifest-mime',manifest:true,autoOffer:true},extra));
}
// EXT02/11: true privileged MIME accepts extensionless HLS/DASH; JSON does not.
for (const [mime,kind] of [['application/vnd.apple.mpegurl','hls'],['application/dash+xml','dash']]) {
  const result=core.classifyResponse({url:'https://cdn.example/api/opaque',type:'xmlhttprequest',contentType:mime});
  assert.equal(result.accept,true,`${kind} MIME`); assert.equal(result.manifest,true);
  assert.equal(result.reason,'manifest-mime');
}
assert.equal(core.classifyResponse({url:'https://cdn.example/video.m3u8',contentType:'application/json',type:'xmlhttprequest'}).accept,false);
assert.equal(core.analyzeBody({text:'#EXTM3U\n#EXT-X-TARGETDURATION:6',contentType:'application/json'}).manifestBody,false);
assert.equal(core.analyzeBody({text:'#EXTM3U',contentType:'text/plain'}).manifestBody,false);
assert.equal(core.analyzeBody({text:hls,contentType:'application/vnd.apple.mpegurl'}).manifestBody,true);
assert.equal(core.analyzeBody({text:mpd,contentType:'application/dash+xml'}).manifestBody,true);
assert.equal(core.analyzeBody({text:'<MPD></MPD>',contentType:'application/dash+xml'}).manifestBody,false);
assert.equal(core.analyzeBody({text:'<!DOCTYPE MPD [<!ENTITY x "y">]><MPD></MPD>',contentType:'application/dash+xml'}).manifestBody,false);
// EXT01: child variants and independent audio belong to one logical HLS root.
insert(1,childHls,0,'child',99,{contentType:'application/vnd.apple.mpegurl'});
insert(1,rootHls,0,'master',100,{manifestText:hls});
assert.equal(store.size(1),1,'variant child must be absorbed into master');
const hlsCandidate=store.best(1);
assert.equal(hlsCandidate.variantInfo.length,2);
assert.equal(hlsCandidate.trackInfo.length,1);
assert.equal(hlsCandidate.manifestRole,'master');
// EXT03: DASH is one master with scoped representation metadata, not downloadable URLs invented from source.
insert(2,rootDash,0,'mpd',200,{contentType:'application/dash+xml',manifestText:mpd});
const dash=store.best(2);
assert.equal(dash.variantInfo.length,1);
assert.equal(dash.trackInfo.length,1);
assert.equal(dash.variantInfo[0].representationId,'720p');
assert.equal(dash.trackInfo[0].language,'en');
assert.equal(dash.manifestRole,'master');
// EXT04/12: thousands of segments and common ad resources cannot storm picker/evidence cache.
for(let i=0;i<2500;i++) {
  store.merge(1,{url:`https://cdn.example/segments/segment-${i}.ts`,frameId:0,source:'webRequest',requestId:`seg${i}`});
}
assert.equal(store.size(1),1);
assert.equal(store.diagnostic(1).suppressedSegments,2500);
assert.ok((store.evidence.get(1)||new Map()).size <= 384);
assert.ok(store.recentManifestEvidence(1,0).length===1,'segment flood must not evict strong HLS manifest proof');
const groupedHlsProof=store.recentManifestEvidence(1,0);
assert.equal(groupedHlsProof.length,1,'master and child must share one frame-scoped logical proof');
assert.equal(groupedHlsProof[0].requestId,'master','the authoritative master is selected over its child variant');
insert(1,'https://cdn.example/separate.mpd',0,'independent',105,{contentType:'application/dash+xml'});
assert.equal(store.recentManifestEvidence(1,0).length,2,'unrelated manifests stay ambiguous for MSE playback');
assert.equal(store.merge(1,{url:'https://doubleclick.net/ad/video.mp4',requestId:'ad'}),false);
assert.equal(core.classifyResponse({url:'https://ads.example/ads/preroll.mp4',contentType:'video/mp4',type:'media'}).accept,false);
// EXT05/08/09: exact frame evidence only, no blob URL synthesis, and all frame evidence retired.
insert(3,'https://cdn.example/manifest?token=frameA',3,'f3',500);
insert(3,'https://cdn.example/manifest?token=frameB',7,'f7',501);
assert.equal(store.size(3),2);
assert.equal(store.recentManifestEvidence(3,3).length,1);
assert.equal(store.recentManifestEvidence(3,7).length,1);
assert.equal(store.recentManifestEvidence(3,0).length,0);
assert.equal(core.resolveUrl('blob:https://host.example/123','https://host.example'), '');
store.clearFrame(3,3);
assert.equal(store.size(3),1);
assert.equal(store.recentManifestEvidence(3,3).length,0);
store.removeTab(3);
assert.equal(store.size(3),0);
// EXT06/07: rotated signed URL retains logical ID but stale generation cannot replace current headers/URL.
insert(4,'https://cdn.example/movie.m3u8?token=OLD',0,'old',700,{headers:{authorization:'Bearer OLD'}});
const id=store.best(4).logicalMediaId;
insert(4,'https://cdn.example/movie.m3u8?token=NEW',0,'new',800,{headers:{authorization:'Bearer NEW'}});
assert.equal(store.size(4),1);
assert.equal(store.best(4).logicalMediaId,id);
assert.ok(store.best(4).url.includes('NEW'));
insert(4,'https://cdn.example/movie.m3u8?token=OLD',0,'old',700,{headers:{authorization:'Bearer OLD'}});
assert.ok(store.best(4).url.includes('NEW'),'stale async callback rolled back exact authority');
assert.equal(store.best(4).headers.authorization,'Bearer NEW');
// EXT07: untrusted re-enrichment must not refresh the time-to-live of privileged proof.
const evidence=[...(store.evidence.get(4)||new Map()).values()].find(x=>x.requestId==='new');
assert.ok(evidence);
evidence.at=Date.now()-50000;
insert(4,'https://cdn.example/movie.m3u8?token=NEW',0,'new',800);
assert.ok(!store.findEvidence(4,'https://cdn.example/movie.m3u8?token=NEW',{frameId:0,requestId:'new'},45000));
assert.equal(store.recentManifestEvidence(4,0).filter(x=>x.requestId==='new').length,0);
// EXT08: two distinct manifests in same frame must be labeled ambiguous (not silently picked).
insert(5,'https://cdn.example/manifest/A',0,'a',2001);
insert(5,'https://cdn.example/manifest/B',0,'b',2002);
assert.equal(store.recentManifestEvidence(5,0).length,2);
console.log('MP02C_PLAYBACK_RUNTIME_PASS EXT01-EXT09/EXT11-EXT12: HLS/DASH, MIME, false positives, frame, TTL, segments');
