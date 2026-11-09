"use strict";
const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path"),vm=require("node:vm"),os=require("node:os"),cp=require("node:child_process");
const source=path.resolve(__dirname,"../src/main/extension/xdm-firefox");
const ctx=vm.createContext({URL,URLSearchParams,console,encodeURI,globalThis:null,
  document:{baseURI:"https://site.example/watch",title:"Video"},location:{href:"https://site.example/watch"}});
ctx.globalThis=ctx;ctx.XdmExtensionConfig={contractVersion:3,xdmScheme:"xdmdownload"};
vm.runInContext(fs.readFileSync(path.join(source,"handoff.js"),"utf8"),ctx);
const h=ctx.XdmHandoffV1;
assert.equal(h.buildXdmCapture({url:"https://cdn.example/stream.m3u8?signature=signed-a"}),"");
assert.equal(h.buildXdmCapture({url:"https://cdn.example/video.mp4",browserHandoff:{finalHeaders:{headers:{Authorization:"Bearer forbidden"}}}}),"");
const safe=h.buildXdmCapture({url:"https://cdn.example/video.mp4",pageUrl:"https://site.example/watch"});
assert(safe.startsWith("xdmdownload://add?v=1&"));
assert(!safe.includes("headers="));
assert(fs.readFileSync(path.join(source,"generated-config.template.js"),"utf8").includes("@@CAPTURE_PAIRING_CONFIG@@"));
const output=fs.mkdtempSync(path.join(os.tmpdir(),"xdm-mp01-keyless-"));
try {
  const render=cp.spawnSync("python3",[path.resolve(__dirname,"../tools/prepare_extension.py"),
    "--source",source,"--output",output,"--contract-version","3","--extension-version","1.6.1"],{encoding:"utf8"});
  assert.equal(render.status,0,render.stderr||render.stdout);
  const generated=fs.readFileSync(path.join(output,"generated-config.js"),"utf8");
  assert(!generated.includes("@@")); assert(!generated.includes("captureKeyId"));
} finally { fs.rmSync(output,{recursive:true,force:true}); }
(async()=>{
  const unsigned=await h.buildCaptureSession({sessionId:"unpaired",candidates:[{url:"https://cdn.example/master.m3u8?signature=secret"}]});
  assert.equal(unsigned,"");
  const safeSession=await h.buildCaptureSession({sessionId:"unpaired",candidates:[{url:"https://cdn.example/video.mp4"}]});
  assert(safeSession.startsWith("xdmdownload://add?"));
  console.log("MP01 release gate: no keyless credential leaks and paired template renders");
})().catch(e=>{console.error(e);process.exitCode=1});
