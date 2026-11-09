"use strict";
const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
const {webcrypto} = require("node:crypto");
const source=path.resolve(__dirname,"../src/main/extension/xdm-firefox/handoff.js");
const b64=u8=>Buffer.from(u8).toString("base64url");
const u8=s=>new Uint8Array(Buffer.from(s,"base64url"));
(async()=>{
    const kp=await webcrypto.subtle.generateKey({name:"RSA-OAEP",modulusLength:2048,publicExponent:new Uint8Array([1,0,1]),hash:"SHA-1"},true,["encrypt","decrypt"]);
    const spki=b64(new Uint8Array(await webcrypto.subtle.exportKey("spki",kp.publicKey)));
    const kid="a".repeat(24);
    const ctx=vm.createContext({URL,URLSearchParams,console,encodeURI,crypto:webcrypto,TextEncoder,atob,btoa,globalThis:null});
    ctx.globalThis=ctx;
    ctx.XdmExtensionConfig={contractVersion:3,xdmScheme:"xdmdownload",captureKeyId:kid,capturePublicKeySpkiBase64Url:spki,captureOaepHash:"SHA-1"};
    vm.runInContext(fs.readFileSync(source,"utf8"),ctx,{filename:"handoff.js"});
    const handoff=ctx.XdmHandoffV1;
    const sensitive="https://cdn.example/master.m3u8?token=top-secret";
    const head={requestId:"request-77",requestGeneration:Date.now(),finalHeaders:{kind:"FinalSent",headers:{Cookie:"session=private",Authorization:"Bearer private"}}};
    const session=await handoff.buildCaptureSession({sessionId:"browser-secure-test",revision:42,pageUrl:"https://site.example/watch?session=page-secret",title:"Test",candidates:[
      {url:sensitive,requestId:"request-77",requestGeneration:head.requestGeneration,browserHandoff:head,contentType:"application/vnd.apple.mpegurl",requestFingerprint:"exact-77",stableMediaId:"logical-master-12345678",logicalMediaId:"logical-master-12345678",manifest:true,manifestRole:"master",variantInfo:[{url:"https://cdn.example/720.m3u8",width:1280,height:720,bandwidth:2800000,audioGroup:"audio"}],trackInfo:[{url:"https://cdn.example/en.vtt",type:"subtitles",name:"English",language:"en"}]},
      {url:"https://cdn.example/other.mp4?signature=second-secret",requestId:"request-88",requestGeneration:head.requestGeneration,browserHandoff:{...head,requestId:"wrong-request"},contentType:"video/mp4"}
    ]});
    assert(session.startsWith("xdmdownload://capture?v=2&"));
    assert(!/private|top-secret|page-secret|second-secret|authorization|cookie|headers|signature/i.test(decodeURIComponent(session)));
    const uri=new URL(session); assert.equal(uri.searchParams.get("kid"),kid);
    const raw=await webcrypto.subtle.decrypt({name:"RSA-OAEP"},kp.privateKey,u8(uri.searchParams.get("ek")));
    const key=await webcrypto.subtle.importKey("raw",raw,{name:"AES-GCM"},false,["decrypt"]);
    const aad=new TextEncoder().encode(`xdm-capture-v2|browser-secure-test|${kid}`);
    const plain=new Uint8Array(await webcrypto.subtle.decrypt({name:"AES-GCM",iv:u8(uri.searchParams.get("iv")),additionalData:aad,tagLength:128},key,u8(uri.searchParams.get("ct"))));
    const json=JSON.parse(new TextDecoder().decode(plain));
    assert.equal(json.candidates.length,2);
    assert.equal(json.candidates[0].url,sensitive);
    assert.equal(json.candidates[0].finalHeaders.authorization,"Bearer private");
    assert.equal(json.candidates[0].logicalMediaId,"logical-master-12345678");
    assert.equal(json.candidates[0].variantInfo[0].height,720);
    assert.equal(json.candidates[0].trackInfo[0].language,"en");
    assert.equal(json.candidates[1].finalHeaders,undefined,"frame/request-swapped proof cannot authorize headers");
    await assert.rejects(webcrypto.subtle.decrypt({name:"AES-GCM",iv:u8(uri.searchParams.get("iv")),additionalData:new TextEncoder().encode("xdm-capture-v2|forged|"+kid)},key,u8(uri.searchParams.get("ct"))));
    assert.equal(json.expiresAt-json.createdAt,10*60*1000);
    console.log("MP01 app-paired RSA/AES-GCM confidentiality, origin binding and scope: passed");
})().catch(err=>{console.error(err);process.exitCode=1});
