const assert = require("assert");
const path = require("path");

function event() {
  const listeners = [];
  return {
    listeners,
    addListener(fn) { listeners.push(fn); }
  };
}

const storageState = {};
const executeCalls = [];
const handoffInputs = [];
const events = {
  before: event(),
  sent: event(),
  headers: event(),
  completed: event(),
  error: event(),
  removed: event(),
  changed: event(),
  message: event()
};

globalThis.XdmHandoffV1 = {
  async buildCaptureSession(input) {
    handoffInputs.push(input);
    const candidate = input.candidates[0];
    return `xdmdownload://capture?v=3&url=${encodeURIComponent(candidate.url)}`;
  }
};

globalThis.browser = {
  storage: {
    local: {
      async get(keys) {
        if (typeof keys === "string") return { [keys]: storageState[keys] };
        if (Array.isArray(keys)) return Object.fromEntries(keys.map(key => [key, storageState[key]]));
        return { ...storageState };
      },
      async set(values) { Object.assign(storageState, values); }
    },
    onChanged: events.changed
  },
  runtime: {
    onMessage: events.message
  },
  webRequest: {
    onBeforeSendHeaders: events.before,
    onSendHeaders: events.sent,
    onHeadersReceived: events.headers,
    onCompleted: events.completed,
    onErrorOccurred: events.error
  },
  tabs: {
    onRemoved: events.removed,
    async get(tabId) { return { id: tabId, url: `https://page.example/watch/${tabId}`, title: `Example video ${tabId}` }; },
    async executeScript(tabId, options) {
      executeCalls.push({ tabId, options });
      return [true];
    }
  }
};

const source = path.join(__dirname, "..", "src", "main", "extension", "xdm-firefox");
require(path.join(source, "detector-core.js"));
require(path.join(source, "candidate-store.js"));
require(path.join(source, "network-observer.js"));

assert.strictEqual(events.before.listeners.length, 1);
assert.strictEqual(events.sent.listeners.length, 1, "final sent-header listener must be installed");
assert.strictEqual(events.headers.listeners.length, 1);
assert.strictEqual(events.message.listeners.length, 1, "page observation receiver registered synchronously");

(async () => {
  events.before.listeners[0]({
    tabId: 7,
    requestId: "r1",
    requestHeaders: [
      { name: "User-Agent", value: "IronFox test" },
      { name: "Referer", value: "https://page.example/watch/7" },
      { name: "Authorization", value: "Bearer <redacted>" },
      { name: "Accept-Language", value: "en-GB,en;q=0.9" }
    ]
  });

  events.headers.listeners[0]({
    tabId: 7,
    frameId: 4,
    requestId: "r1",
    url: "https://cdn.example/token?id=42",
    type: "xmlhttprequest",
    responseHeaders: [
      { name: "Content-Type", value: "video/mp4" },
      { name: "Content-Length", value: "5000000" }
    ]
  });

  await new Promise(resolve => setTimeout(resolve, 750));
  assert.ok(executeCalls.some(call => call.tabId === 7 && String(call.options.code || "").includes("offerNetwork")));
  let diagnostics = storageState.xdmNetworkDiagnosticsV1;
  assert.ok(diagnostics && diagnostics["7"]);
  assert.strictEqual(diagnostics["7"].reason, "xhr-media-mime");
  assert.strictEqual(diagnostics["7"].frameCount, 1);
  assert.strictEqual(handoffInputs.length, 0, "network detection must not build an unselected capture session");
  const firstChooser = await events.message.listeners[0]({ type: "xdmGetLogicalCandidatesV2", tabId: 7 }, {});
  assert.ok(firstChooser.candidates.length > 0, "picker must expose privileged request evidence");
  const firstId = firstChooser.candidates[0].logicalMediaId;
  const firstSend = await events.message.listeners[0]({ type: "xdmSendLogicalCandidatesV2", tabId: 7, logicalMediaIds: [firstId] }, {});
  assert.strictEqual(firstSend.ok, true, firstSend.error || "selected handoff failed");
  assert.strictEqual(handoffInputs.length, 1, "one explicit selection produces exactly one handoff");
  assert.strictEqual(handoffInputs[0].candidates.length, 1);
  assert.strictEqual(handoffInputs[0].candidates[0].headers["accept-language"], undefined, "proposed headers must not become executable without final sent-header evidence");
  assert.strictEqual(handoffInputs[0].candidates[0].browserHandoff.proposedHeaders.headers["accept-language"], "en-GB,en;q=0.9", "Accept-Language remains available as proposed audit context");

  const firstTab7DispatchCount = executeCalls.filter(call => call.tabId === 7).length;
  events.headers.listeners[0]({
    tabId: 7,
    frameId: 4,
    requestId: "r1-audio",
    url: "https://cdn.example/audio.m4a",
    type: "media",
    responseHeaders: [
      { name: "Content-Type", value: "audio/mp4" },
      { name: "Content-Length", value: "1000000" }
    ]
  });
  await new Promise(resolve => setTimeout(resolve, 650));
  assert.ok(
    executeCalls.filter(call => call.tabId === 7).length > firstTab7DispatchCount,
    "session handoff refreshes when candidate count grows even if the best candidate stays unchanged"
  );

  const messageListener = events.message.listeners[0];
  const beforeForged = executeCalls.length;
  messageListener({
    type: "xdmPageObservationV1",
    observation: {
      source: "fetch-response",
      responseUrl: "https://forged.example/master.m3u8",
      contentType: "application/vnd.apple.mpegurl",
      requestHeaders: { authorization: "Bearer forged-page-secret" },
      bodyExcerpt: "https://forged.example/master.m3u8"
    }
  }, { tab: { id: 10 }, frameId: 0, url: "https://page.example/watch/10" });
  await new Promise(resolve => setTimeout(resolve, 650));
  assert.strictEqual(executeCalls.length, beforeForged, "page-world observation without privileged webRequest evidence must not dispatch");

  events.before.listeners[0]({
    tabId: 8, requestId: "r8-media", requestHeaders: [
      { name: "Authorization", value: "Bearer privileged-header" },
      { name: "Referer", value: "https://embed.example/player" }
    ]
  });
  events.headers.listeners[0]({
    tabId: 8, frameId: 9, requestId: "r8-media",
    url: "https://media.example/master.m3u8?token=abc", type: "xmlhttprequest",
    responseHeaders: [{ name: "Content-Type", value: "application/vnd.apple.mpegurl" }]
  });
  messageListener({
    type: "xdmPageObservationV1",
    observation: {
      source: "fetch-response", requestType: "fetch",
      requestUrl: "https://api.example/player/config",
      responseUrl: "https://media.example/master.m3u8?token=abc",
      contentType: "application/vnd.apple.mpegurl",
      requestHeaders: { authorization: "Bearer forged-page-secret" },
      bodyExcerpt: JSON.stringify({ source: "https://media.example/master.m3u8?token=abc" })
    }
  }, { tab: { id: 8 }, frameId: 9, url: "https://embed.example/player" });

  await new Promise(resolve => setTimeout(resolve, 700));
  const injectedForTab8 = executeCalls.filter(call => call.tabId === 8)
    .map(call => String(call.options.code || "")).join("\n");
  assert.ok(injectedForTab8.includes("offerNetwork") &&
    injectedForTab8.includes("xdm-detected-media.m3u8"),
    "privileged request evidence must offer an opaque media hint, not the signed URL");
  assert.ok(!injectedForTab8.includes("token=abc") &&
    !injectedForTab8.includes("Bearer privileged-header") &&
    !injectedForTab8.includes("Authorization") && !injectedForTab8.includes("Cookie"),
    "the page-injected offer must never contain credentials or request headers");
  diagnostics = storageState.xdmNetworkDiagnosticsV1;
  assert.ok(diagnostics && diagnostics["8"]);
  assert.ok(!JSON.stringify(diagnostics["8"]).includes("forged-page-secret"), "page-supplied headers never become privileged diagnostics/handoff evidence");
  assert.ok(!diagnostics["8"].url.includes("token=abc"));

  events.before.listeners[0]({ tabId: 12, requestId: "r12-video", requestHeaders: [{ name: "Referer", value: "https://page.example/watch/12" }] });
  events.headers.listeners[0]({
    tabId: 12,
    frameId: 0,
    requestId: "r12-video",
    url: "https://cdn.example/video/playback.mp4",
    type: "media",
    responseHeaders: [{ name: "Content-Type", value: "video/mp4" }]
  });
  messageListener({
    type: "xdmFramePlaybackV1",
    candidate: {
      url: "https://cdn.example/video/playback.mp4",
      durationMs: 321000,
      thumbnailUrl: "https://img.example/video-poster.jpg",
      reason: "frame-video-playback"
    }
  }, { tab: { id: 12, url: "https://page.example/watch/12", title: "Example video 12" }, frameId: 0, url: "https://page.example/watch/12" });
  await new Promise(resolve => setTimeout(resolve, 700));
  const chooser12 = await messageListener({ type: "xdmGetLogicalCandidatesV2", tabId: 12 }, {});
  assert.ok(chooser12.candidates.length > 0, "playback-enriched media must be selectable");
  const selection12 = await messageListener({ type: "xdmSendLogicalCandidatesV2", tabId: 12, logicalMediaIds: [chooser12.candidates[0].logicalMediaId] }, {});
  assert.strictEqual(selection12.ok, true, selection12.error || "selected playback send failed");
  const metadataHandoff = handoffInputs.slice().reverse().find(input => input.pageUrl === "https://page.example/watch/12");
  assert.ok(metadataHandoff, "playback-enriched candidate must build a browser capture session");
  assert.strictEqual(metadataHandoff.candidates[0].durationMs, 321000, "playback duration must survive privileged candidate merge");
  assert.strictEqual(metadataHandoff.candidates[0].thumbnailUrl, "https://img.example/video-poster.jpg", "poster artwork must survive privileged candidate merge");
  assert.strictEqual(metadataHandoff.title, "Example video 12", "tab title must remain the extension capture title");

  const beforeSegments = executeCalls.length;
  events.headers.listeners[0]({
    tabId: 9,
    frameId: 0,
    requestId: "r2",
    url: "https://cdn.example/segment_99.m4s",
    type: "xmlhttprequest",
    responseHeaders: [{ name: "Content-Type", value: "video/mp4" }]
  });
  await new Promise(resolve => setTimeout(resolve, 650));
  assert.strictEqual(executeCalls.length, beforeSegments, "segments are ignored");

  const beforeWeakManifest = executeCalls.length;
  events.before.listeners[0]({ tabId: 11, requestId: "r11-manifest", requestHeaders: [{ name: "Accept-Language", value: "pt-BR" }] });
  events.headers.listeners[0]({
    tabId: 11,
    frameId: 0,
    requestId: "r11-manifest",
    url: "https://cdn.example/opaque/master.m3u8?token=weak",
    type: "xmlhttprequest",
    responseHeaders: []
  });
  await new Promise(resolve => setTimeout(resolve, 650));
  assert.strictEqual(executeCalls.length, beforeWeakManifest, "suffix-only manifest evidence stays hidden by default");
  messageListener({
    type: "xdmPageObservationV1",
    observation: {
      source: "fetch-response",
      responseUrl: "https://cdn.example/opaque/master.m3u8?token=weak",
      contentType: "text/plain",
      bodyExcerpt: "#EXTM3U\n#EXT-X-TARGETDURATION:6\n#EXT-X-MEDIA-SEQUENCE:1"
    }
  }, { tab: { id: 11 }, frameId: 0, url: "https://page.example/watch/11" });
  await new Promise(resolve => setTimeout(resolve, 650));
  assert.strictEqual(executeCalls.length, beforeWeakManifest,
    "Untrusted HLS body cannot promote suffix-only HTTP response evidence");
  const chooser11 = await messageListener({ type: "xdmGetLogicalCandidatesV2", tabId: 11 }, {});
  assert.strictEqual(chooser11.candidates.length, 0, "No privileged manifest MIME, no strong picker row");
  assert.strictEqual(handoffInputs.some(input => input.pageUrl === "https://page.example/watch/11"), false,
    "Forged manifest body must not invoke handoff");


  // Parity02: a child media playlist, its many segments, a late master playlist, and a poster
  // must collapse to one logical chooser item. The chooser, not raw requests, controls app launch.
  const tab20 = 20;
  events.before.listeners[0]({ tabId: tab20, requestId: "child", requestHeaders: [{ name: "Referer", value: "https://page.example/watch/20" }] });
  events.headers.listeners[0]({
    tabId: tab20, frameId: 0, requestId: "child",
    url: "https://cdn.example/hls/720p.m3u8?sig=one", type: "xmlhttprequest",
    responseHeaders: [{ name: "Content-Type", value: "application/vnd.apple.mpegurl" }]
  });
  const childBody = ["#EXTM3U", "#EXT-X-TARGETDURATION:6", ...Array.from({ length: 25 }, (_, i) => `segment-${i + 1}.ts`)].join("\n");
  messageListener({ type: "xdmPageObservationV1", observation: {
    responseUrl: "https://cdn.example/hls/720p.m3u8?sig=one", contentType: "application/vnd.apple.mpegurl", bodyExcerpt: childBody
  }}, { tab: { id: tab20, url: "https://page.example/watch/20", title: "Parity video" }, frameId: 0, url: "https://page.example/watch/20" });

  events.before.listeners[0]({ tabId: tab20, requestId: "master", requestHeaders: [{ name: "Referer", value: "https://page.example/watch/20" }] });
  events.headers.listeners[0]({
    tabId: tab20, frameId: 0, requestId: "master",
    url: "https://cdn.example/hls/master.m3u8?sig=master-one", type: "xmlhttprequest",
    responseHeaders: [{ name: "Content-Type", value: "application/vnd.apple.mpegurl" }]
  });
  const masterBody = "#EXTM3U\n#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID=\"subs\",URI=\"subs/en.m3u8\"\n#EXT-X-STREAM-INF:BANDWIDTH=2000000,SUBTITLES=\"subs\"\n720p.m3u8?sig=one";
  messageListener({ type: "xdmPageObservationV1", observation: {
    responseUrl: "https://cdn.example/hls/master.m3u8?sig=master-one", contentType: "application/vnd.apple.mpegurl", bodyExcerpt: masterBody
  }}, { tab: { id: tab20, url: "https://page.example/watch/20", title: "Parity video" }, frameId: 0, url: "https://page.example/watch/20" });

  const chooser = await messageListener({ type: "xdmGetLogicalCandidatesV2", tabId: tab20 }, {});
  assert.strictEqual(chooser.logicalCandidateCount, 1, "master + child must become one logical media item");
  assert.strictEqual(chooser.candidates.length, 1);
  assert.strictEqual(chooser.candidates[0].manifestRole, "master");
  assert.ok(chooser.candidates[0].variantCount >= 1, "master retains child variant relationship");
  assert.ok(chooser.candidates[0].trackCount >= 1, "master retains subtitle/audio track relationship");
  assert.ok(chooser.candidates[0].segmentCount >= 25, "child segments remain internal evidence on the logical item");
  assert.ok(!chooser.candidates[0].url.includes("master-one"), "chooser URL is credential-redacted/canonicalized");
  assert.ok(!chooser.candidates[0].url.includes("sig="), "canonical chooser URL removes volatile signing parameters entirely");

  // Verified HLS body promotes retained privileged evidence: the child playlist
  // body and later master playlist are linked only because matching privileged
  // webRequest responses advertised a real manifest MIME in the same frame.
  // Tab 11 above verifies an untrusted body without such MIME never promotes.
  assert.ok(chooser.candidates[0].variantCount >= 1 &&
    chooser.candidates[0].trackCount >= 1 &&
    chooser.candidates[0].segmentCount >= 25,
    "verified HLS body promotes retained privileged evidence");
  assert.ok(!JSON.stringify(chooser.candidates).includes("sig=master-one"),
    "privileged HLS body must not expose signed URL tokens to chooser data");

  const beforeChooserLaunch = executeCalls.length;
  const chosenId = chooser.candidates[0].logicalMediaId;
  const multiSelection = await messageListener({ type: "xdmSendLogicalCandidatesV2", tabId: tab20, logicalMediaIds: [chosenId, "forged-second-id"] }, {});
  assert.strictEqual(multiSelection.ok, false, "Multi-select must be rejected");
  assert.match(multiSelection.error, /exactly one/i);
  assert.strictEqual(executeCalls.length, beforeChooserLaunch, "rejected multi-select must never launch a native link");
  const sendResult = await messageListener({ type: "xdmSendLogicalCandidatesV2", tabId: tab20, logicalMediaIds: [chosenId] }, {});
  assert.strictEqual(sendResult.ok, true);
  assert.strictEqual(sendResult.sentCount, 1);
  assert.ok(executeCalls.slice(beforeChooserLaunch).some(call => String(call.options.code || "").includes("location.href")), "explicit chooser submission launches XDM");

  // Signed request refreshes from several observers must not multiply chooser rows.
  for (let i = 0; i < 120; i += 1) {
    const signed = `https://cdn.example/hls/master.m3u8?sig=rotate-${i}`;
    events.before.listeners[0]({ tabId: tab20, requestId: `refresh-${i}`, requestHeaders: [] });
    events.headers.listeners[0]({ tabId: tab20, frameId: 0, requestId: `refresh-${i}`, url: signed, type: "xmlhttprequest", responseHeaders: [{ name: "Content-Type", value: "application/vnd.apple.mpegurl" }] });
  }
  const stressedChooser = await messageListener({ type: "xdmGetLogicalCandidatesV2", tabId: tab20 }, {});
  assert.strictEqual(stressedChooser.logicalCandidateCount, 1, "rotating signed requests stay one logical media item");
  assert.ok(stressedChooser.candidates[0].observationCount >= 100, "raw observation volume is tracked independently from logical row count");


  // Accept-Language must survive privileged request capture. Test both
  // onBeforeSendHeaders (proposed / audit only) and onSendHeaders (final /
  // executable), with deliberately different values to catch unsafe promotion.
  const langTab = 31;
  const langUrl = "https://cdn.example/lang/sample.mp4?sig=final-lang";
  const langRequest = {
    tabId: langTab, frameId: 0, requestId: "p07-hf05-language-final",
    url: langUrl, documentUrl: "https://page.example/watch/31"
  };
  events.before.listeners[0]({ ...langRequest, requestHeaders: [
    { name: "Accept-Language", value: "en-GB,en;q=0.9" },
    { name: "Authorization", value: "Bearer proposed-only" }
  ] });
  events.sent.listeners[0]({ ...langRequest, requestHeaders: [
    { name: "Accept-Language", value: "pt-BR,pt;q=0.8" },
    { name: "Authorization", value: "Bearer final-sent-only" }
  ] });
  events.headers.listeners[0]({ ...langRequest, type: "media", responseHeaders: [
    { name: "Content-Type", value: "video/mp4" }
  ] });
  const langChooser = await messageListener({ type: "xdmGetLogicalCandidatesV2", tabId: langTab }, {});
  assert.strictEqual(langChooser.candidates.length, 1,
    "matching webRequest response must retain one selectable media candidate");
  const langSend = await messageListener({
    type: "xdmSendLogicalCandidatesV2", tabId: langTab,
    logicalMediaIds: [langChooser.candidates[0].logicalMediaId]
  }, {});
  assert.strictEqual(langSend.ok, true, langSend.error || "final-header selection failed");
  const langHandoff = handoffInputs.slice().reverse().find(
    input => input.pageUrl === "https://page.example/watch/31");
  assert.ok(langHandoff && langHandoff.candidates.length === 1,
    "explicit user selection must create exactly one privileged XDM capture");
  const langCandidate = langHandoff.candidates[0];
  assert.strictEqual(langCandidate.headers["accept-language"], "pt-BR,pt;q=0.8",
    "only final sent Accept-Language is executable");
  assert.strictEqual(langCandidate.headers.authorization, "Bearer final-sent-only",
    "pre-send Authorization must never override final sent evidence");
  assert.strictEqual(langCandidate.browserHandoff.finalHeaders.kind, "FinalSent");
  assert.strictEqual(langCandidate.browserHandoff.finalHeaders.headers["accept-language"], "pt-BR,pt;q=0.8");
  assert.strictEqual(langCandidate.browserHandoff.proposedHeaders.headers["accept-language"], "en-GB,en;q=0.9",
    "proposed Accept-Language remains audit-only and cannot replace final evidence");
  assert.notStrictEqual(langCandidate.headers.authorization, "Bearer proposed-only");
  await new Promise(resolve => setTimeout(resolve, 650));
  const offers31 = executeCalls.filter(call => call.tabId === langTab &&
    String(call.options.code || "").includes("offerNetwork"))
    .map(call => String(call.options.code || "")).join("\n");
  assert.ok(!offers31.includes("Bearer final-sent-only") &&
    !offers31.includes("Bearer proposed-only") &&
    !offers31.includes("pt-BR,pt;q=0.8"),
    "page-injected media offer must not expose replay headers");

  console.log("Phase 38 background smoke tests passed");
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
