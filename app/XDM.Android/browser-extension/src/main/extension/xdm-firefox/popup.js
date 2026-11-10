const defaults = {
  enabled: true,
  autoDetectPlayingVideos: true,
  defaultTarget: (globalThis.XdmExtensionConfig && globalThis.XdmExtensionConfig.defaultTarget) || "xdm",
  showPossibleMediaCandidates: false,
  siteMode: "all",
  blacklist: [],
  whitelist: []
};

let activeTab = null;
const NETWORK_STATUS_KEY = "xdmNetworkStatusV1";
const NETWORK_DIAGNOSTICS_KEY = "xdmNetworkDiagnosticsV1";
const BRIDGE_FILES = ["bridge-selftest.js", "generated-config.js", "handoff.js", "fab.js", "frame-bridge.js"];
let diagnosticTimer = null;

let logicalCandidates = [];
let selectedLogicalCandidateId = "";
let logicalSendInFlight = false;
let logicalSentKey = "";

function selectedLogicalId() {
  return selectedLogicalCandidateId;
}

function selectedCandidate() {
  const id = selectedLogicalId();
  return logicalCandidates.find(candidate => String(candidate.logicalMediaId || candidate.stableMediaId || "") === id) || null;
}

function updateSendSelectedButton() {
  const xdmButton = document.getElementById("sendSelectedMedia");
  const oneDmButton = document.getElementById("sendSelectedMedia1Dm");
  const candidate = selectedCandidate();
  const enabled = Boolean(activeTab && candidate) && !logicalSendInFlight;
  if (xdmButton) {
    xdmButton.textContent = "Send to XDM";
    xdmButton.disabled = !enabled || Boolean(activeTab && logicalSentKey === `${activeTab.id}|xdm|${selectedLogicalId()}`);
  }
  if (oneDmButton) {
    oneDmButton.textContent = "Send to 1DM+";
    oneDmButton.disabled = !enabled || Boolean(activeTab && logicalSentKey === `${activeTab.id}|1dm|${selectedLogicalId()}`);
  }

  document.querySelectorAll("#logicalMediaCandidates .candidate-row").forEach(row => {
    const input = row.querySelector('input[type="radio"]');
    row.dataset.selected = String(Boolean(input && input.checked));
  });
}

function formatBytes(value) {
  const bytes = Number(value || 0);
  if (!Number.isFinite(bytes) || bytes <= 0) return "";
  const units = ["B", "KiB", "MiB", "GiB", "TiB"];
  let size = bytes;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) { size /= 1024; unit += 1; }
  return `${size >= 100 || unit === 0 ? Math.round(size) : size.toFixed(1)} ${units[unit]}`;
}

function formatDuration(value) {
  const ms = Number(value || 0);
  if (!Number.isFinite(ms) || ms <= 0) return "";
  const total = Math.round(ms / 1000);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  if (hours) return `${hours}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

function hostFor(value) {
  try { return new URL(value).hostname.replace(/^www\./, ""); } catch (_) { return ""; }
}

function extensionFor(candidate) {
  const disposition = String(candidate && candidate.contentDisposition || "");
  const dispositionMatch = disposition.match(/filename\*?=(?:UTF-8''|["'])?[^;"']*?(\.[A-Za-z0-9]{2,8})(?:["';]|$)/i);
  if (dispositionMatch) return dispositionMatch[1].toLowerCase();
  try {
    const match = new URL(candidate && candidate.url || "").pathname.match(/(\.[A-Za-z0-9]{2,8})$/);
    if (match) return match[1].toLowerCase();
  } catch (_) {}
  const mime = String(candidate && candidate.contentType || "").split(";", 1)[0].trim().toLowerCase();
  const map = {
    "video/mp4": ".mp4", "video/webm": ".webm", "video/x-matroska": ".mkv",
    "video/quicktime": ".mov", "audio/mpeg": ".mp3", "audio/mp4": ".m4a",
    "audio/aac": ".aac", "audio/ogg": ".ogg", "audio/opus": ".opus",
    "application/vnd.apple.mpegurl": ".m3u8", "application/x-mpegurl": ".m3u8",
    "application/dash+xml": ".mpd"
  };
  return map[mime] || (candidate && candidate.streamKind === "hls" ? ".m3u8" : candidate && candidate.streamKind === "dash" ? ".mpd" : "");
}

function cleanDisplayFilename(title, candidate) {
  const handoff = globalThis.XdmHandoffV1;
  if (handoff && typeof handoff.cleanFilename === "function") {
    return handoff.cleanFilename(title || "Detected media", candidate && candidate.url || "", candidate && candidate.contentType || "");
  }
  const base = String(title || "Detected media")
    .replace(/[\\/:*?"<>|\u0000-\u001f]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/[. ]+$/g, "") || "Detected media";
  const ext = extensionFor(candidate);
  return ext && !base.toLowerCase().endsWith(ext) ? `${base}${ext}` : base;
}

function bestVariant(candidate) {
  const variants = Array.isArray(candidate && candidate.variantInfo) ? candidate.variantInfo : [];
  return variants.reduce((best, item) => {
    const pixels = Number(item && item.width || 0) * Number(item && item.height || 0);
    const bestPixels = Number(best && best.width || 0) * Number(best && best.height || 0);
    const bandwidth = Number(item && (item.averageBandwidth || item.bandwidth) || 0);
    const bestBandwidth = Number(best && (best.averageBandwidth || best.bandwidth) || 0);
    return !best || pixels > bestPixels || (pixels === bestPixels && bandwidth > bestBandwidth) ? item : best;
  }, null);
}

function formatBandwidth(value) {
  const bps = Number(value || 0);
  if (!Number.isFinite(bps) || bps <= 0) return "";
  return bps >= 1_000_000 ? `${(bps / 1_000_000).toFixed(bps >= 10_000_000 ? 0 : 1)} Mbps` : `${Math.round(bps / 1000)} kbps`;
}

function candidateMeta(candidate) {
  const parts = [];
  const kind = String(candidate.streamKind || "media").toUpperCase();
  if (kind) parts.push(kind);
  const mime = String(candidate.contentType || "").split(";", 1)[0].trim();
  parts.push(candidate.quality === "strong" ? "Strong evidence" : "Possible · review");
  if (mime) parts.push(mime.replace(/^application\//, "").replace(/^video\//, "").replace(/^audio\//, "").toUpperCase());

  const best = bestVariant(candidate);
  const width = Number(best && best.width || candidate.width || 0);
  const height = Number(best && best.height || candidate.height || 0);
  if (width && height) parts.push(`${width}×${height}`);
  const bandwidth = formatBandwidth(best && (best.averageBandwidth || best.bandwidth) || candidate.bandwidth);
  if (bandwidth) parts.push(bandwidth);

  const duration = formatDuration(candidate.durationMs);
  if (duration) parts.push(duration);
  const size = formatBytes(candidate.contentLength);
  if (size) parts.push(size);
  if (candidate.manifestRole === "master") parts.push("master playlist");
  if (Number(candidate.variantCount || 0) > 0) parts.push(`${candidate.variantCount} variant${candidate.variantCount === 1 ? "" : "s"}`);
  if (Number(candidate.trackCount || 0) > 0) parts.push(`${candidate.trackCount} track${candidate.trackCount === 1 ? "" : "s"}`);
  if (candidate.encryptedAes128) parts.push("AES-128");
  if (candidate.protectedMedia) parts.push("protected");
  if (candidate.lowLatency) parts.push("LL-HLS");
  return parts.join(" · ");
}

function detailLine(label, value) {
  if (!value) return null;
  const line = document.createElement("div");
  line.className = "candidate-detail-line";
  const key = document.createElement("b");
  key.textContent = `${label}: `;
  const val = document.createElement("span");
  val.textContent = String(value);
  line.append(key, val);
  return line;
}

function renderLogicalCandidates(snapshot) {
  logicalCandidates = Array.isArray(snapshot && snapshot.candidates) ? snapshot.candidates : [];
  if (selectedLogicalCandidateId && !logicalCandidates.some(candidate => String(candidate.logicalMediaId || candidate.stableMediaId || "") === selectedLogicalCandidateId)) {
    selectedLogicalCandidateId = "";
  }
  const list = document.getElementById("logicalMediaCandidates");
  const summary = document.getElementById("logicalMediaSummary");
  const count = document.getElementById("logicalMediaCount");
  if (!list || !summary || !count) return;
  count.textContent = String(logicalCandidates.length);
  list.replaceChildren();

  if (!logicalCandidates.length) {
    summary.textContent = "No media detected on this tab yet. Start playback, then refresh or rescan.";
  } else {
    const raw = Number(snapshot.rawObservationCount || 0);
    const suppressed = Number(snapshot.suppressedSegmentCount || 0);
    summary.textContent = `${logicalCandidates.length} media item${logicalCandidates.length === 1 ? "" : "s"}. Choose exactly one to send.${raw ? ` ${raw} network/page observations grouped.` : ""}${suppressed ? ` ${suppressed} segment observation${suppressed === 1 ? "" : "s"} kept internal.` : ""}`;

    logicalCandidates.forEach((candidate, index) => {
      const id = String(candidate.logicalMediaId || candidate.stableMediaId || `candidate-${index}`);
      const row = document.createElement("div");
      row.className = "candidate-row";
      row.dataset.selected = String(id === selectedLogicalCandidateId);

      const radio = document.createElement("input");
      radio.type = "radio";
      radio.name = "logicalMediaCandidate";
      radio.id = `logical-media-${index}`;
      radio.value = id;
      radio.checked = id === selectedLogicalCandidateId;
      radio.addEventListener("change", () => {
        if (!radio.checked) return;
        selectedLogicalCandidateId = id;
        updateSendSelectedButton();
      });

      const copy = document.createElement("div");
      copy.className = "candidate-copy";
      const title = document.createElement("label");
      title.className = "candidate-title";
      title.htmlFor = radio.id;
      title.textContent = candidate.title || `Detected media ${index + 1}`;

      const meta = document.createElement("div");
      meta.className = "candidate-meta";
      meta.textContent = candidateMeta(candidate) || "Media metadata unavailable";

      const source = document.createElement("div");
      source.className = "candidate-source";
      const host = hostFor(candidate.url);
      const sourceParts = [host, candidate.source, candidate.requestType].filter(Boolean);
      source.textContent = sourceParts.join(" · ");

      const details = document.createElement("details");
      details.className = "candidate-details";
      const detailsSummary = document.createElement("summary");
      detailsSummary.textContent = "Media metadata";
      const detailsBody = document.createElement("div");
      detailsBody.className = "candidate-details-body";

      const suggestedTitle = activeTab && activeTab.title ? activeTab.title : candidate.title;
      const best = bestVariant(candidate);
      const resolution = best && best.width && best.height ? `${best.width}×${best.height}` : "";
      const codecs = best && best.codecs ? best.codecs : candidate.codecs || "";
      const lines = [
        detailLine("Suggested filename", cleanDisplayFilename(suggestedTitle, candidate)),
        detailLine("Type", candidate.streamKind ? String(candidate.streamKind).toUpperCase() : "Media"),
        detailLine("MIME", candidate.contentType),
        detailLine("Resolution", resolution),
        detailLine("Bitrate", formatBandwidth(best && (best.averageBandwidth || best.bandwidth) || candidate.bandwidth)),
        detailLine("Codecs", codecs),
        detailLine("Duration", formatDuration(candidate.durationMs)),
        detailLine("Size", formatBytes(candidate.contentLength)),
        detailLine("Variants", Number(candidate.variantCount || 0) || ""),
        detailLine("Tracks", Number(candidate.trackCount || 0) || ""),
        detailLine("Segments observed", Number(candidate.segmentCount || 0) || ""),
        detailLine("Source", candidate.source),
        detailLine("Request type", candidate.requestType),
        detailLine("Quality", candidate.quality),
        detailLine("Confidence", Number(candidate.confidence || 0) > 0 ? candidate.confidence : ""),
        detailLine("Evidence", candidate.reason),
        detailLine("Page", candidate.pageUrl || (activeTab && activeTab.url)),
        detailLine("Frame", candidate.frameUrl),
        detailLine("Media URL", candidate.url),
      ].filter(Boolean);
      detailsBody.append(...lines);
      details.append(detailsSummary, detailsBody);

      copy.append(title, meta);
      if (source.textContent) copy.append(source);
      copy.append(details);
      row.append(radio, copy);
      row.addEventListener("click", event => {
        if (event.target.closest("details") || event.target === radio || event.target.closest("label")) return;
        selectedLogicalCandidateId = id;
        radio.checked = true;
        updateSendSelectedButton();
      });
      list.append(row);
    });
  }
  updateSendSelectedButton();
}

async function refreshLogicalCandidates() {
  const refresh = document.getElementById("refreshCapturedMedia");
  if (!activeTab || typeof activeTab.id !== "number") { renderLogicalCandidates({ candidates: [] }); return; }
  if (refresh) refresh.disabled = true;
  try {
    const snapshot = await browser.runtime.sendMessage({ type: "xdmGetLogicalCandidatesV2", tabId: activeTab.id });
    renderLogicalCandidates(snapshot || { candidates: [] });
  } catch (error) {
    renderLogicalCandidates({ candidates: [] });
    setStatus(`Could not read captured media: ${error && error.message ? error.message : String(error)}`, "error");
  } finally {
    if (refresh) refresh.disabled = !activeTab;
  }
}

async function sendSelectedLogicalCandidate(target) {
  if (!activeTab || typeof activeTab.id !== "number" || logicalSendInFlight) return;
  const id = selectedLogicalId();
  const sendKey = `${activeTab.id}|${target}|${id}`;
  if (id && logicalSentKey === sendKey) return;
  if (!id) {
    setStatus("Choose one media item first.", "error");
    return;
  }
  const isOneDm = target === "1dm";
  const button = document.getElementById(isOneDm ? "sendSelectedMedia1Dm" : "sendSelectedMedia");
  logicalSendInFlight = true;
  updateSendSelectedButton();
  if (button) button.disabled = true;
  try {
    const result = await browser.runtime.sendMessage({
      type: isOneDm ? "xdmSendLogicalCandidatesTo1DmV1" : "xdmSendLogicalCandidatesV2",
      tabId: activeTab.id,
      logicalMediaIds: [id]
    });
    if (!result || result.ok !== true) throw new Error(result && result.error || `${isOneDm ? "1DM+" : "XDM"} handoff failed`);
    logicalSentKey = sendKey;
    setStatus(`Sent the selected media item to ${isOneDm ? "1DM+" : "XDM"}.`, "ok");
  } catch (error) {
    setStatus(error && error.message ? error.message : String(error), "error");
  } finally {
    logicalSendInFlight = false;
    updateSendSelectedButton();
  }
}

async function sendSelectedLogicalCandidates() { return sendSelectedLogicalCandidate("xdm"); }
async function sendSelectedLogicalCandidatesToOneDm() { return sendSelectedLogicalCandidate("1dm"); }

function setStatus(message, kind = "") {
  const node = document.getElementById("status");
  node.textContent = message;
  node.className = `status ${kind}`.trim();
}

function setHealth(id, text, ok = null) {
  const node = document.getElementById(id);
  if (!node) return;
  node.textContent = text;
  node.className = ok === true ? "ok" : ok === false ? "error" : "";
}

async function getSettings() {
  const result = await browser.storage.local.get("settings");
  return Object.assign({}, defaults, result.settings || {});
}

async function saveSettings() {
  const mode = document.getElementById("siteMode").value;
  const entries = document.getElementById("siteList").value
    .split(/\r?\n|,/)
    .map(value => value.trim().toLowerCase().replace(/^https?:\/\//, "").replace(/\/.*$/, ""))
    .filter(Boolean);
  const current = await getSettings();
  const next = Object.assign({}, current, {
    enabled: document.getElementById("enabled").checked,
    autoDetectPlayingVideos: document.getElementById("autoDetect").checked,
    showPossibleMediaCandidates: document.getElementById("showPossible").checked,
    defaultTarget: document.getElementById("defaultTarget").value,
    siteMode: mode
  });
  if (mode === "blacklist") next.blacklist = [...new Set(entries)];
  if (mode === "whitelist") next.whitelist = [...new Set(entries)];
  await browser.storage.local.set({ settings: next });
  setStatus("Saved. Reload existing video tabs so the updated detector can attach.", "ok");
}

function updateList(settings) {
  const mode = document.getElementById("siteMode").value;
  const values = mode === "whitelist" ? settings.whitelist : settings.blacklist;
  document.getElementById("siteList").value = mode === "all" ? "" : (values || []).join("\n");
  document.getElementById("siteCard").style.opacity = mode === "all" ? ".82" : "1";
}

function hostAllowedBySiteMode(tabUrl, settings) {
  if (!settings || settings.enabled === false) return false;
  if (settings.siteMode === "all") return true;
  let host = "";
  try { host = new URL(tabUrl).hostname.toLowerCase().replace(/^www\./, ""); } catch (_) { return false; }
  const list = settings.siteMode === "whitelist" ? settings.whitelist : settings.blacklist;
  const matched = (Array.isArray(list) ? list : []).some(item => {
    const domain = String(item || "").trim().toLowerCase().replace(/^www\./, "");
    return domain && (host === domain || host.endsWith(`.${domain}`));
  });
  return settings.siteMode === "whitelist" ? matched : !matched;
}

function validHttpUrl(value) {
  try {
    const url = new URL(value);
    return /^https?:$/.test(url.protocol) ? url.href : "";
  } catch (_) {
    return "";
  }
}

async function executeTopFrame(tabId, details) {
  return browser.tabs.executeScript(tabId, Object.assign({ allFrames: false, runAt: "document_idle" }, details));
}

async function executeAllFramesBestEffort(tabId, details) {
  try {
    return await browser.tabs.executeScript(tabId, Object.assign({ allFrames: true, runAt: "document_idle" }, details));
  } catch (_) {
    return [];
  }
}

async function ensureBridge(tabId) {
  // The top frame is the only frame that can mount the visible FAB. It is required.
  for (const file of BRIDGE_FILES) {
    await executeTopFrame(tabId, { file });
  }

  // Iframes feed the detector, but some pages intentionally block extension access.
  // Their failures must not poison the top-page manual FAB path.
  for (const file of BRIDGE_FILES) {
    await executeAllFramesBestEffort(tabId, { file });
  }
}

async function runBridgeSelfTest(tabId) {
  await executeTopFrame(tabId, { file: "bridge-selftest.js" });
  const results = await executeTopFrame(tabId, {
    code: `(() => {
      const test = globalThis.__xdmBridgeSelfTestV1;
      return test && typeof test.probe === "function" ? test.probe() : { ok: false, hostMounted: false, shadowMounted: false, lastError: "bridge-selftest.js did not load" };
    })();`
  });
  return results && results[0] && typeof results[0] === "object" ? results[0] : { ok: false, lastError: "Self-test returned no result" };
}

function describeHealth(health) {
  const status = health && typeof health === "object" ? health : {};
  setHealth("bridgeState", status.hasBridge ? "Loaded" : "Missing", status.hasBridge === true);
  setHealth("handoffState", status.hasHandoff ? "Loaded" : "Missing", status.hasHandoff === true);
  setHealth("fabState", status.hasFab ? "Loaded" : "Missing", status.hasFab === true);
  setHealth("hostState", status.hasBody ? (status.hostPresent ? "Mounted" : "Ready") : "No root", status.hasBody === true);
  const sniffer = status.pageSnifferState || "unknown";
  const snifferDetail = status.pageSnifferError ? `${sniffer}: ${status.pageSnifferError}` : sniffer;
  setHealth("snifferState", snifferDetail, sniffer === "active" || sniffer === "loaded" ? true : sniffer === "failed" ? false : null);
  setHealth("offerState", `${Number(status.topFrameOffersAttempted || 0)} tried · ${Number(status.fabShowSuccesses || 0)} shown`, Number(status.fabShowFailures || 0) === 0 ? true : false);
  return status;
}

async function readBridgeHealth(tabId) {
  const results = await executeTopFrame(tabId, {
    code: `(() => {
      const bridge = globalThis.__xdmInPageBridgeV1;
      return bridge && typeof bridge.health === "function" ? bridge.health() : { hasBridge: false, lastError: "frame-bridge.js did not load" };
    })();`
  });
  return results && results[0] && typeof results[0] === "object" ? results[0] : { hasBridge: false, lastError: "Bridge health returned no result" };
}

async function showLauncher(input) {
  if (!activeTab || typeof activeTab.id !== "number") throw new Error("No active webpage tab is available.");
  if (!/^https?:/i.test(activeTab.url || "")) throw new Error("Open a normal HTTP or HTTPS webpage first.");

  const settings = await getSettings();
  if (!hostAllowedBySiteMode(activeTab.url || "", settings)) throw new Error("This site is disabled by XDM site-mode settings.");
  const selfTest = await runBridgeSelfTest(activeTab.id);
  setHealth("selfTestState", selfTest.ok ? "Passed" : (selfTest.lastError || "Failed"), selfTest.ok === true);
  if (!selfTest.ok) throw new Error(`Page host self-test failed: ${selfTest.lastError || "launcher host could not mount"}`);

  await ensureBridge(activeTab.id);
  const payload = JSON.stringify(input || {});
  const code = `(() => {
    const bridge = globalThis.__xdmInPageBridgeV1;
    if (!bridge) return { shown: false, health: { hasBridge: false, lastError: "frame-bridge.js did not load" } };
    if (typeof bridge.showManualWithDiagnostics === "function") return bridge.showManualWithDiagnostics(${payload});
    return { shown: Boolean(bridge.showManual(${payload})), health: typeof bridge.health === "function" ? bridge.health() : { hasBridge: true } };
  })();`;
  const results = await executeTopFrame(activeTab.id, { code });
  const report = results && results[0] && typeof results[0] === "object" ? results[0] : { shown: false, health: { lastError: "The page launcher returned no diagnostic report" } };
  const health = describeHealth(report.health || {});
  if (report.shown !== true) throw new Error(health.lastError || "The page launcher could not be created.");
  setStatus("Themed FAB added to the webpage. Close this panel, then tap it.", "ok");
}

async function handle(action) {
  try {
    if (action === "page") {
      await showLauncher({ url: activeTab.url, title: activeTab.title || "Web page", label: "Send page" });
    } else if (action === "probe") {
      await showLauncher({ mode: "probe", force: true });
    } else if (action === "manual") {
      const url = validHttpUrl(document.getElementById("manualUrl").value.trim());
      if (!url) throw new Error("Enter a complete HTTP or HTTPS URL.");
      await showLauncher({ url, title: activeTab && activeTab.title ? activeTab.title : "Download", label: "Send URL" });
    }
  } catch (error) {
    setStatus(error && error.message ? error.message : String(error), "error");
  }
}

async function refreshBridgeDiagnostics() {
  if (!activeTab || typeof activeTab.id !== "number" || !/^https?:/i.test(activeTab.url || "")) return;
  try {
    describeHealth(await readBridgeHealth(activeTab.id));
  } catch (error) {
    setHealth("bridgeState", error && error.message ? error.message : String(error), false);
  }
}

async function refreshDiagnostics() {
  const detectorNode = document.getElementById("detectorState");
  const mediaNode = document.getElementById("lastDetectedMedia");
  if (!detectorNode || !mediaNode) return;
  try {
    const result = await browser.storage.local.get([NETWORK_STATUS_KEY, NETWORK_DIAGNOSTICS_KEY]);
    const status = result[NETWORK_STATUS_KEY] || {};
    if (status.active) {
      detectorNode.textContent = "Network observer active";
      detectorNode.className = "host ok";
    } else if (status.lastError) {
      detectorNode.textContent = `Observer error: ${status.lastError}`;
      detectorNode.className = "host error";
    } else {
      detectorNode.textContent = "Network observer has not started";
      detectorNode.className = "host error";
    }

    const all = result[NETWORK_DIAGNOSTICS_KEY] || {};
    const diagnostic = activeTab && typeof activeTab.id === "number" ? all[String(activeTab.id)] : null;
    if (diagnostic && diagnostic.url) {
      const age = Math.max(0, Math.round((Date.now() - Number(diagnostic.at || 0)) / 1000));
      const stats = `${Number(diagnostic.webResponses || 0)} net · ${Number(diagnostic.pageResponses || 0)} page · ${Number(diagnostic.bodyCandidates || 0)} body · ${Number(diagnostic.frameCount || 0)} frame(s)`;
      const quality = diagnostic.quality === "possible" ? "Possible media" : "High confidence";
      mediaNode.textContent = `${quality} · ${diagnostic.reason || "media"} · ${age}s ago · ${stats} · ${diagnostic.url}`;
      mediaNode.title = `${diagnostic.url}\n${stats}`;
    } else {
      mediaNode.textContent = "No media response captured on this tab yet";
      mediaNode.removeAttribute("title");
    }
    await refreshBridgeDiagnostics();
  } catch (error) {
    detectorNode.textContent = error && error.message ? error.message : String(error);
    detectorNode.className = "host error";
  }
}

(async () => {
  try {
    const settings = await getSettings();
    document.getElementById("enabled").checked = settings.enabled !== false;
    document.getElementById("autoDetect").checked = settings.autoDetectPlayingVideos !== false;
    document.getElementById("showPossible").checked = settings.showPossibleMediaCandidates === true;
    document.getElementById("defaultTarget").value = settings.defaultTarget || "xdm";
    document.getElementById("siteMode").value = settings.siteMode || "all";
    updateList(settings);

    const tabs = await browser.tabs.query({ active: true, currentWindow: true });
    activeTab = tabs[0] || null;
    if (activeTab && /^https?:/i.test(activeTab.url || "")) {
      document.getElementById("currentHost").textContent = new URL(activeTab.url).hostname;
      document.getElementById("sendPage").disabled = false;
      document.getElementById("appTest").disabled = false;
      document.getElementById("rescan").disabled = false;
      document.getElementById("refreshCapturedMedia").disabled = false;
    } else {
      document.getElementById("currentHost").textContent = "Open a normal webpage to use the bridge";
    }
    await refreshDiagnostics();
    await refreshLogicalCandidates();
    diagnosticTimer = setInterval(async () => { await refreshDiagnostics(); await refreshLogicalCandidates(); }, 1200);
  } catch (error) {
    setStatus(error && error.message ? error.message : String(error), "error");
  }
})();

document.getElementById("manualUrl").addEventListener("input", event => {
  document.getElementById("sendManual").disabled = !validHttpUrl(event.target.value.trim()) || !activeTab;
});
document.getElementById("siteMode").addEventListener("change", async () => updateList(await getSettings()));
document.getElementById("save").addEventListener("click", saveSettings);
document.getElementById("sendPage").addEventListener("click", () => handle("page"));
document.getElementById("appTest").addEventListener("click", () => handle("probe"));
document.getElementById("sendManual").addEventListener("click", () => handle("manual"));

window.addEventListener("unload", () => {
  if (diagnosticTimer) clearInterval(diagnosticTimer);
});

document.getElementById("rescan").addEventListener("click", async () => {
  try {
    if (!activeTab || typeof activeTab.id !== "number") throw new Error("No active webpage tab is available.");
    await ensureBridge(activeTab.id);
    const results = await browser.tabs.executeScript(activeTab.id, {
      code: `(() => { const bridge = globalThis.__xdmInPageBridgeV1; return bridge ? bridge.rescan() : false; })();`,
      allFrames: true,
      runAt: "document_idle"
    });
    if (!results || !results.some(Boolean)) throw new Error("No page detector was reachable.");
    const health = await readBridgeHealth(activeTab.id);
    describeHealth(health);
    setStatus("Rescan requested. Start or resume the video, then watch for the themed page FAB.", "ok");
    await refreshDiagnostics();
  } catch (error) {
    setStatus(error && error.message ? error.message : String(error), "error");
  }
});

document.getElementById("refreshCapturedMedia").addEventListener("click", refreshLogicalCandidates);
document.getElementById("sendSelectedMedia").addEventListener("click", sendSelectedLogicalCandidates);
document.getElementById("sendSelectedMedia1Dm").addEventListener("click", sendSelectedLogicalCandidatesToOneDm);
