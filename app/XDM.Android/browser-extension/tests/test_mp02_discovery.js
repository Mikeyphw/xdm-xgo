"use strict";
// MP02A deterministic Node fixtures. No browser/device, network, or secrets.
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const root = path.resolve(__dirname, "../src/main/extension/xdm-firefox");
const sandbox = vm.createContext({ console, URL, URLSearchParams, Date, globalThis: null });
sandbox.globalThis = sandbox;
for (const file of ["detector-core.js", "candidate-store.js"]) {
  vm.runInContext(fs.readFileSync(path.join(root, file), "utf8"), sandbox, { filename: file });
}
const core = sandbox.XdmDetectorCoreV1;
const Store = sandbox.XdmCandidateStoreV1;
const store = new Store({ maxPerTab: 64, ttlMs: 900000 });
const base = "https://media.example/live/manifest";
const mpd = `<?xml version="1.0"?>
<MPD type="static"><Period><AdaptationSet id="video" contentType="video" mimeType="video/mp4">
<Representation id="v720" bandwidth="1200000" width="1280" height="720"><BaseURL>720/</BaseURL></Representation>
<Representation id="v1080" bandwidth="3200000" width="1920" height="1080"><BaseURL>1080/</BaseURL></Representation>
<SegmentList><SegmentURL media="first.m4s"/><SegmentURL media="second.m4s"/></SegmentList>
</AdaptationSet><AdaptationSet id="audio" mimeType="audio/mp4" lang="en">
<Representation id="en128" bandwidth="128000"><BaseURL>audio/en/</BaseURL></Representation>
</AdaptationSet></Period></MPD>`;
const parsed = core.parseDashRelationships(mpd, base);
assert.strictEqual(parsed.isDash, true, "EXT03 DASH XML root is identified");
assert.strictEqual(parsed.master, true);
assert.strictEqual(parsed.variantInfo.length, 2, "EXT03 video representations do not collapse");
assert.strictEqual(parsed.trackInfo.length, 1, "EXT03 audio track remains separate");
assert.strictEqual(parsed.variantInfo[1].height, 1080);
assert.strictEqual(parsed.trackInfo[0].language, "en");
assert.strictEqual(parsed.segments.length, 2);
assert.strictEqual(core.parseDashRelationships('{"text":"<MPD></MPD>"}', base).isDash, false,
  "EXT07 JSON containing MPD text must not become a manifest");
assert.strictEqual(core.parseDashRelationships('<!DOCTYPE MPD [ <!ENTITY x SYSTEM "file:///etc/passwd">]><MPD/>', base).isDash, false,
  "MP02 never follows XML entities");
assert.strictEqual(core.analyzeBody({responseUrl:base, contentType:"application/dash+xml",text:'{"result":42}'}).manifestBody, false,
  "Page-supplied DASH MIME cannot promote non-manifest content");
assert.strictEqual(core.analyzeBody({responseUrl:base,contentType:"application/dash+xml",text:mpd}).dashBody,true);
assert(store.merge(24, { url:base, frameId:0, requestId:"dash-a", requestGeneration:100,
  confidence:1040, quality:"strong", manifest:true, bodyDerived:true, manifestText:mpd }));
const dash = store.best(24);
assert.strictEqual(dash.manifestRole, "master");
assert.strictEqual(dash.variantInfo.length,2);
assert.strictEqual(dash.trackInfo.length,1);
assert.strictEqual(dash.segmentCount,2);
const same = "https://cdn.example/m/shared.m3u8?sig=one";
assert(store.merge(25,{url:same,frameId:3,requestId:"f3",requestGeneration:101,confidence:900,quality:"strong",headers:{authorization:"Bearer frame3"}}));
assert(store.merge(25,{url:same,frameId:9,requestId:"f9",requestGeneration:102,confidence:900,quality:"strong",headers:{authorization:"Bearer frame9"}}));
assert.strictEqual(store.size(25),2,"EXT05 same URL in two iframes is two selectable logical items");
const frames = store.snapshot(25,10);
assert.notStrictEqual(frames[0].logicalMediaId,frames[1].logicalMediaId);
assert.strictEqual(new Set(frames.map(x=>x.frameId)).size,2);
assert(store.merge(25,{url:"https://cdn.example/m/shared.m3u8?sig=two",frameId:3,requestId:"fresh",requestGeneration:200,
  confidence:950,quality:"strong",headers:{authorization:"Bearer fresh"}}));
assert.strictEqual(store.size(25),2,"EXT06 signed refresh does not create duplicate frame rows");
const frame3 = () => store.snapshot(25,10).find(c => c.frameId===3);
assert(frame3().url.includes("sig=two"), "fresh signed exact URL is executable");
assert.strictEqual(frame3().headers.authorization,"Bearer fresh");
assert(store.merge(25,{url:same,frameId:3,requestId:"delayed",requestGeneration:110,
  confidence:970,quality:"strong",headers:{authorization:"Bearer old"}}));
assert(frame3().url.includes("sig=two"), "stale callback must not roll exact URL backwards");
assert.strictEqual(frame3().requestId,"fresh");
assert.strictEqual(frame3().headers.authorization,"Bearer fresh","stale callback cannot overwrite final sent headers");
for (let index=0; index<80; index++) {
  assert.strictEqual(store.merge(24,{ url:`https://media.example/live/chunk-${index}.m4s`,frameId:0,
    parentManifestUrl:base,confidence:1000,quality:"strong"}),false);
}
assert.strictEqual(store.size(24),1,"EXT04 segment storm cannot create picker rows");
assert(store.best(24).segmentCount>=82);
const ad=core.classifyResponse({url:"https://doubleclick.example/ads/banner.mp4",type:"media",contentType:"video/mp4"});
assert.strictEqual(ad.accept,false,"EXT12 ad false positives remain rejected");
assert.strictEqual(core.resolveUrl("blob:https://site.example/uuid",base),"","EXT08 blob URL is not executable");
assert.strictEqual(core.classifyResponse({url:"https://cdn.example/opaque",type:"fetch",contentType:"application/vnd.apple.mpegurl"}).manifest,true,
  "EXT11 manifest MIME handles extensionless HLS");
store.clearFrame(25,3);
assert.strictEqual(store.size(25),1,"iframe navigation retires only its frame candidate");
assert.strictEqual(store.best(25).frameId,9);
store.removeTab(25);
assert.strictEqual(store.size(25),0,"top-level navigation removes all tab candidates");
console.log("MP02A_DISCOVERY_NODE_PASS: DASH hints, frames, freshness, segment storms, false positives, scoped retirement");
