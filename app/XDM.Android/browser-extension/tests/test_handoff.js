"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs"), path = require("node:path"), vm = require("node:vm");
const source = path.resolve(__dirname, "../src/main/extension/xdm-firefox/handoff.js");
const ctx = vm.createContext({ URL, URLSearchParams, console, encodeURI,
    document: {baseURI:"https://example.test/watch",title:"Video"},
    location: {href:"https://example.test/watch"}, globalThis:null });
ctx.globalThis = ctx;
ctx.XdmExtensionConfig = { contractVersion:3, xdmScheme:"xdmdownload" };
vm.runInContext(fs.readFileSync(source,"utf8"),ctx,{filename:"handoff.js"});
const handoff = ctx.XdmHandoffV1;
assert.equal(handoff.buildXdmCapture({url:"https://cdn.example/video.mp4?token=abc"}), "");
assert.equal(handoff.buildXdmCapture({url:"https://cdn.example/video.mp4", browserHandoff:{finalHeaders:{headers:{Cookie:"sid=secret"}}}}), "");
assert.equal(handoff.buildXdmAdd({url:"https://cdn.example/video.mp4?signature=secret"}), "");
const plain=handoff.buildXdmCapture({url:"https://cdn.example/video.mp4",pageUrl:"https://example.test/watch"});
assert(plain.startsWith("xdmdownload://add?v=1&"));
assert(!/headers|candidate|session|cookie|authorization/i.test(plain));
assert.equal(handoff.buildOneDm({url:"javascript:alert(1)"}), "");
console.log("MP01 public-only URL fallback: passed");
