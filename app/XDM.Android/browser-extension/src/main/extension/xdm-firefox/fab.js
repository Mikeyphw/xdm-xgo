(() => {
  if (globalThis.XdmLauncherUiV3) {
    globalThis.XdmLauncherUiV2 = globalThis.XdmLauncherUiV3;
    globalThis.XdmLauncherUiV1 = globalThis.XdmLauncherUiV3;
    return;
  }

  const HOST_ID = "__xdm_media_fab_host";
  const FAB_TTL_MS = 5 * 60 * 1000;
  const GET_LOGICAL_CANDIDATES_TYPE = "xdmGetLogicalCandidatesV2";
  const SEND_XDM_TYPE = "xdmSendLogicalCandidatesV2";
  const SEND_1DM_TYPE = "xdmSendLogicalCandidatesTo1DmV1";
  const CONFIG = globalThis.XdmExtensionConfig || {};
  const FALLBACK_THEME = Object.freeze({
    background: "#090B0F",
    surface: "#101318",
    raisedSurface: "#161A21",
    strongSurface: "#1C212A",
    text: "#E8EDF5",
    mutedText: "#ABB4C2",
    primary: "#7DB8FF",
    onPrimary: "#003259",
    primaryContainer: "#183B59",
    onPrimaryContainer: "#D2E8FF",
    outline: "#333A46",
    separator: "#252B35",
    success: "#79D49A",
    error: "#FFB4AB",
    fabSizePx: 56,
    fabCornerRadiusPx: 18,
    fabEdgeInsetPx: 16,
    fabActionGapPx: 10,
    motionFastMs: 140,
    motionStandardMs: 220
  });

  let host = null;
  let shadow = null;
  let expiryTimer = null;
  let current = null;
  let expanded = false;
  let listenersInstalled = false;
  let pickerOpen = false;
  let pickerLoading = false;
  let pickerCandidates = [];
  let selectedLogicalId = "";
  let pickerStatus = "";
  let pickerStatusKind = "";

  function clampNumber(value, fallback, minimum, maximum) {
    const number = Number(value);
    return Number.isFinite(number) ? Math.min(maximum, Math.max(minimum, number)) : fallback;
  }

  function safeColor(value, fallback) {
    return /^#[0-9a-f]{6}$/i.test(String(value || "")) ? String(value) : fallback;
  }

  function theme() {
    const value = CONFIG.theme && typeof CONFIG.theme === "object" ? CONFIG.theme : {};
    const colors = {};
    for (const key of [
      "background", "surface", "raisedSurface", "strongSurface", "text", "mutedText",
      "primary", "onPrimary", "primaryContainer", "onPrimaryContainer", "outline",
      "separator", "success", "error"
    ]) colors[key] = safeColor(value[key], FALLBACK_THEME[key]);
    return Object.freeze(Object.assign(colors, {
      fabSizePx: clampNumber(value.fabSizePx, FALLBACK_THEME.fabSizePx, 48, 80),
      fabCornerRadiusPx: clampNumber(value.fabCornerRadiusPx, FALLBACK_THEME.fabCornerRadiusPx, 0, 40),
      fabEdgeInsetPx: clampNumber(value.fabEdgeInsetPx, FALLBACK_THEME.fabEdgeInsetPx, 8, 40),
      fabActionGapPx: clampNumber(value.fabActionGapPx, FALLBACK_THEME.fabActionGapPx, 4, 24),
      motionFastMs: clampNumber(value.motionFastMs, FALLBACK_THEME.motionFastMs, 0, 1000),
      motionStandardMs: clampNumber(value.motionStandardMs, FALLBACK_THEME.motionStandardMs, 0, 1500)
    }));
  }

  function make(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function iconSvg() {
    return '<svg aria-hidden="true" viewBox="0 0 24 24" width="27" height="27" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M12 3v10.25m0 0 4-4m-4 4-4-4M5 15.5v3A1.5 1.5 0 0 0 6.5 20h11a1.5 1.5 0 0 0 1.5-1.5v-3" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/><path d="m17.1 4.4 2.5 2.5m0-2.5-2.5 2.5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>';
  }

  function css(tokens) {
    return `
      :host{all:initial;position:fixed;right:max(${tokens.fabEdgeInsetPx}px,calc(env(safe-area-inset-right) + 12px));bottom:max(${tokens.fabEdgeInsetPx}px,calc(env(safe-area-inset-bottom) + 12px));z-index:2147483647;pointer-events:none;contain:style;font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color-scheme:dark}
      *,*::before,*::after{box-sizing:border-box}
      button,input,summary{font:inherit}
      .xdm-shell{display:flex;flex-direction:column;align-items:flex-end;gap:${tokens.fabActionGapPx}px;pointer-events:none;isolation:isolate}
      .xdm-menu{display:flex;flex-direction:column;align-items:stretch;gap:8px;min-width:168px;padding:8px;border-radius:${Math.min(tokens.fabCornerRadiusPx,16)}px;background:${tokens.surface};color:${tokens.text};box-shadow:0 12px 34px rgba(0,0,0,.42);opacity:0;transform:translateY(8px) scale(.96);transform-origin:bottom right;visibility:hidden;pointer-events:none;transition:opacity ${tokens.motionFastMs}ms ease,transform ${tokens.motionStandardMs}ms cubic-bezier(.2,.8,.2,1),visibility 0s linear ${tokens.motionStandardMs}ms}
      .xdm-shell[data-expanded="true"] .xdm-menu{opacity:1;transform:translateY(0) scale(1);visibility:visible;pointer-events:auto;transition-delay:0s}
      .xdm-choice{display:flex;align-items:center;justify-content:center;min-height:48px;padding:10px 14px;border:0;border-radius:12px;background:${tokens.raisedSurface};color:${tokens.text};font:700 13px/1.2 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;text-decoration:none;text-align:center;-webkit-tap-highlight-color:transparent;touch-action:manipulation}
      .xdm-choice-primary{background:${tokens.primaryContainer};color:${tokens.onPrimaryContainer}}
      .xdm-fab{position:relative;display:grid;place-items:center;width:${tokens.fabSizePx}px;height:${tokens.fabSizePx}px;min-width:48px;min-height:48px;margin:0;padding:0;border:0;border-radius:${tokens.fabCornerRadiusPx}px;background:${tokens.primaryContainer};color:${tokens.onPrimaryContainer};box-shadow:0 8px 24px rgba(0,0,0,.38);text-decoration:none;cursor:pointer;pointer-events:auto;-webkit-tap-highlight-color:transparent;touch-action:manipulation;transition:transform ${tokens.motionFastMs}ms ease,background ${tokens.motionFastMs}ms ease,box-shadow ${tokens.motionFastMs}ms ease}
      .xdm-fab:hover{background:${tokens.strongSurface};box-shadow:0 10px 28px rgba(0,0,0,.46)}
      .xdm-fab:active{transform:scale(.94)}
      .xdm-fab:focus-visible,.xdm-choice:focus-visible,.xdm-picker-button:focus-visible,.xdm-picker-close:focus-visible,.xdm-media-row:focus-within{outline:3px solid ${tokens.primary};outline-offset:3px}
      .xdm-badge{position:absolute;top:-6px;right:-6px;display:grid;place-items:center;min-width:21px;height:21px;padding:0 6px;border-radius:999px;background:${tokens.primary};color:${tokens.onPrimary};font:800 11px/1 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;box-shadow:0 2px 8px rgba(0,0,0,.4)}
      .xdm-kind{position:absolute;left:-7px;top:-8px;min-width:28px;padding:4px 6px;border-radius:999px;background:${tokens.strongSurface};color:${tokens.text};font:800 9px/1 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;letter-spacing:.35px;text-transform:uppercase;box-shadow:0 2px 8px rgba(0,0,0,.35)}
      .xdm-sr{position:absolute!important;width:1px!important;height:1px!important;padding:0!important;margin:-1px!important;overflow:hidden!important;clip:rect(0,0,0,0)!important;white-space:nowrap!important;border:0!important}

      .xdm-picker-backdrop{position:fixed;inset:0;z-index:2147483647;display:flex;align-items:flex-end;justify-content:center;padding:max(12px,env(safe-area-inset-top)) max(12px,env(safe-area-inset-right)) max(12px,env(safe-area-inset-bottom)) max(12px,env(safe-area-inset-left));background:rgba(0,0,0,.62);backdrop-filter:blur(4px);pointer-events:auto}
      .xdm-picker{width:min(760px,100%);max-height:min(82vh,760px);display:flex;flex-direction:column;overflow:hidden;border:1px solid ${tokens.outline};border-radius:22px;background:${tokens.background};color:${tokens.text};box-shadow:0 24px 70px rgba(0,0,0,.6)}
      .xdm-picker-header{display:flex;align-items:flex-start;justify-content:space-between;gap:14px;padding:18px 18px 12px;border-bottom:1px solid ${tokens.separator};background:${tokens.surface}}
      .xdm-picker-title{margin:0;font:800 18px/1.2 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:${tokens.text}}
      .xdm-picker-subtitle{margin:5px 0 0;color:${tokens.mutedText};font:500 12px/1.35 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
      .xdm-picker-close{flex:0 0 auto;width:38px;height:38px;border:0;border-radius:12px;background:${tokens.raisedSurface};color:${tokens.text};font:800 22px/1 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;cursor:pointer}
      .xdm-picker-list{display:flex;flex-direction:column;gap:9px;overflow:auto;padding:12px 12px 6px;overscroll-behavior:contain}
      .xdm-media-row{display:grid;grid-template-columns:auto 1fr;gap:12px;align-items:start;padding:13px;border:1px solid ${tokens.separator};border-radius:16px;background:${tokens.surface};cursor:pointer;-webkit-tap-highlight-color:transparent}
      .xdm-media-row[data-selected="true"]{border-color:${tokens.primary};background:${tokens.primaryContainer}}
      .xdm-media-radio{width:20px;height:20px;margin:2px 0 0;accent-color:${tokens.primary}}
      .xdm-media-copy{min-width:0}
      .xdm-media-title{display:block;color:${tokens.text};font:800 14px/1.25 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
      .xdm-media-meta{margin-top:5px;color:${tokens.onPrimaryContainer};font:650 12px/1.35 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
      .xdm-media-source{margin-top:4px;color:${tokens.mutedText};font:500 11px/1.3 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
      .xdm-media-details{margin-top:9px;color:${tokens.mutedText};font:500 11px/1.35 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
      .xdm-media-details>summary{cursor:pointer;color:${tokens.primary};font-weight:750}
      .xdm-details-body{display:grid;gap:4px;margin-top:8px;padding:9px;border-radius:10px;background:${tokens.raisedSurface};overflow-wrap:anywhere}
      .xdm-details-line b{color:${tokens.text}}
      .xdm-picker-empty{padding:28px 18px;color:${tokens.mutedText};text-align:center;font:600 13px/1.45 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
      .xdm-picker-status{min-height:18px;padding:4px 16px 0;color:${tokens.mutedText};font:650 12px/1.3 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
      .xdm-picker-status[data-kind="ok"]{color:${tokens.success}}
      .xdm-picker-status[data-kind="error"]{color:${tokens.error}}
      .xdm-picker-footer{display:grid;grid-template-columns:1fr 1fr;gap:10px;padding:12px 12px max(12px,env(safe-area-inset-bottom));border-top:1px solid ${tokens.separator};background:${tokens.surface}}
      .xdm-picker-button{min-height:50px;border:0;border-radius:14px;background:${tokens.raisedSurface};color:${tokens.text};font:800 13px/1.2 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;cursor:pointer}
      .xdm-picker-button-primary{background:${tokens.primaryContainer};color:${tokens.onPrimaryContainer}}
      .xdm-picker-button:disabled{opacity:.42;cursor:default}
      .xdm-picker-loading{padding:30px;color:${tokens.mutedText};text-align:center;font:700 13px/1.4 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
      @media (min-width:680px){.xdm-picker-backdrop{align-items:center}.xdm-picker{max-height:min(84vh,800px)}}
      @media (prefers-reduced-motion:reduce){.xdm-menu,.xdm-fab{transition:none!important}}
    `;
  }

  function installListeners() {
    if (listenersInstalled) return;
    listenersInstalled = true;
    document.addEventListener("fullscreenchange", mount, true);
    document.addEventListener("keydown", event => {
      if (event.key !== "Escape") return;
      if (pickerOpen) closePicker();
      else hide();
    }, true);
  }

  function ensureHost() {
    if (host && host.isConnected !== false) return host;
    const existing = document.getElementById(HOST_ID);
    if (existing) existing.remove();
    host = document.createElement("div");
    host.id = HOST_ID;
    host.dataset.xdmMediaFab = "v3";
    shadow = host.attachShadow({ mode: "closed" });
    installListeners();
    mount();
    return host;
  }

  function mount() {
    if (!host) return;
    const parent = document.fullscreenElement || document.body || document.documentElement;
    if (parent && host.parentNode !== parent) parent.appendChild(host);
  }

  function safeTarget(value) {
    return value === "1dm" || value === "ask" ? value : "xdm";
  }

  function safeKind(value) {
    const kind = String(value || "").toLowerCase();
    if (kind === "hls" || kind === "dash") return kind.toUpperCase();
    if (kind === "video" || kind === "audio") return kind.toUpperCase();
    return "";
  }

  function safeCount(value) {
    const count = Math.floor(Number(value || 1));
    return Number.isFinite(count) ? Math.max(1, Math.min(99, count)) : 1;
  }

  function nativeLink(label, href, primary = false) {
    if (!href) return null;
    const link = make("a", primary ? "xdm-choice xdm-choice-primary" : "xdm-choice", label);
    link.href = href;
    link.rel = "external noopener";
    link.dataset.xdmNativeLink = "true";
    link.addEventListener("click", () => setTimeout(hide, 900));
    return link;
  }

  function describe(state) {
    if (state.pickerRequired) {
      const count = state.candidateCount > 1 ? `${state.candidateCount} detected media items` : "detected media";
      return `Choose ${count}`;
    }
    const destination = state.target === "1dm" ? "1DM+" : state.target === "ask" ? "app choices" : "XDM";
    const kind = state.kind ? `${state.kind} ` : "";
    const count = state.candidateCount > 1 ? `, ${state.candidateCount} candidates` : "";
    return `Open detected ${kind}media in ${destination}${count}`;
  }

  function formatBytes(value) {
    const bytes = Number(value || 0);
    if (!(bytes > 0)) return "";
    const units = ["B", "KB", "MB", "GB", "TB"];
    let amount = bytes;
    let index = 0;
    while (amount >= 1024 && index < units.length - 1) { amount /= 1024; index += 1; }
    return `${amount >= 10 || index === 0 ? amount.toFixed(0) : amount.toFixed(1)} ${units[index]}`;
  }

  function formatDuration(ms) {
    const totalSeconds = Math.round(Number(ms || 0) / 1000);
    if (!(totalSeconds > 0)) return "";
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const seconds = totalSeconds % 60;
    return hours > 0
      ? `${hours}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`
      : `${minutes}:${String(seconds).padStart(2, "0")}`;
  }

  function formatBandwidth(value) {
    const number = Number(value || 0);
    if (!(number > 0)) return "";
    return number >= 1000000 ? `${(number / 1000000).toFixed(number >= 10000000 ? 0 : 1)} Mbps` : `${Math.round(number / 1000)} kbps`;
  }

  function hostFor(value) {
    try { return new URL(String(value || "")).hostname.replace(/^www\./, ""); } catch (_) { return ""; }
  }

  function bestVariant(candidate) {
    const variants = Array.isArray(candidate && candidate.variantInfo) ? candidate.variantInfo : [];
    if (!variants.length) return null;
    return variants.slice().sort((a, b) => {
      const pixelsA = Number(a && a.width || 0) * Number(a && a.height || 0);
      const pixelsB = Number(b && b.width || 0) * Number(b && b.height || 0);
      if (pixelsA !== pixelsB) return pixelsB - pixelsA;
      return Number(b && (b.averageBandwidth || b.bandwidth) || 0) - Number(a && (a.averageBandwidth || a.bandwidth) || 0);
    })[0];
  }

  function extensionFor(candidate) {
    const url = String(candidate && candidate.url || "");
    try {
      const match = new URL(url).pathname.match(/\.(mp4|m4v|webm|mkv|mov|avi|flv|mpeg|mpg|ogv|mp3|m4a|aac|flac|wav|ogg|opus)$/i);
      if (match) return match[1].toUpperCase();
    } catch (_) {}
    const mime = String(candidate && candidate.contentType || "").split(";", 1)[0].toLowerCase();
    if (mime.startsWith("video/")) return mime.slice(6).toUpperCase();
    if (mime.startsWith("audio/")) return mime.slice(6).toUpperCase();
    return "";
  }

  function candidateMeta(candidate) {
    const parts = [];
    const kind = String(candidate && candidate.streamKind || "media").toUpperCase();
    if (kind) parts.push(kind);
    const ext = extensionFor(candidate);
    if (ext && ext !== kind) parts.push(ext);
    const best = bestVariant(candidate);
    if (best && best.width && best.height) parts.push(`${best.width}×${best.height}`);
    const bandwidth = formatBandwidth(best && (best.averageBandwidth || best.bandwidth));
    if (bandwidth) parts.push(bandwidth);
    const duration = formatDuration(candidate && candidate.durationMs);
    if (duration) parts.push(duration);
    const size = formatBytes(candidate && candidate.contentLength);
    if (size) parts.push(size);
    if (Number(candidate && candidate.variantCount || 0) > 1) parts.push(`${candidate.variantCount} variants`);
    if (Number(candidate && candidate.trackCount || 0) > 0) parts.push(`${candidate.trackCount} tracks`);
    if (candidate && candidate.encryptedAes128) parts.push("AES-128");
    if (candidate && candidate.protectedMedia) parts.push("protected");
    if (candidate && candidate.lowLatency) parts.push("LL-HLS");
    return parts.join(" · ");
  }

  function detailLine(label, value) {
    if (value === "" || value == null || value === false) return null;
    const line = make("div", "xdm-details-line");
    const key = make("b", "", `${label}: `);
    const val = make("span", "", String(value));
    line.append(key, val);
    return line;
  }

  function displayFilename(candidate) {
    const handoff = globalThis.XdmHandoffV1;
    if (handoff && typeof handoff.cleanFilename === "function") {
      return handoff.cleanFilename(document.title || candidate.title || "Detected media", candidate.url, candidate.contentType || "");
    }
    return document.title || candidate.title || "Detected media";
  }

  function candidateRow(candidate, index) {
    const id = String(candidate.logicalMediaId || candidate.stableMediaId || `candidate-${index}`);
    const row = make("div", "xdm-media-row");
    row.dataset.selected = String(id === selectedLogicalId);
    const radio = make("input", "xdm-media-radio");
    radio.type = "radio";
    radio.name = "xdmLogicalMediaCandidate";
    radio.value = id;
    radio.checked = id === selectedLogicalId;
    radio.setAttribute("aria-label", `Select ${candidate.title || `detected media ${index + 1}`}`);
    radio.addEventListener("change", () => {
      if (!radio.checked) return;
      selectedLogicalId = id;
      pickerStatus = "";
      pickerStatusKind = "";
      render();
    });

    const copy = make("div", "xdm-media-copy");
    const title = make("div", "xdm-media-title", candidate.title || `Detected media ${index + 1}`);
    const meta = make("div", "xdm-media-meta", candidateMeta(candidate) || "Media metadata unavailable");
    const sourceParts = [hostFor(candidate.url), candidate.source, candidate.requestType].filter(Boolean);
    const source = make("div", "xdm-media-source", sourceParts.join(" · "));
    const details = make("details", "xdm-media-details");
    const detailsSummary = make("summary", "", "Media metadata");
    const body = make("div", "xdm-details-body");
    const best = bestVariant(candidate);
    const lines = [
      detailLine("Suggested filename", displayFilename(candidate)),
      detailLine("Type", String(candidate.streamKind || "media").toUpperCase()),
      detailLine("MIME", candidate.contentType),
      detailLine("Resolution", best && best.width && best.height ? `${best.width}×${best.height}` : ""),
      detailLine("Bitrate", formatBandwidth(best && (best.averageBandwidth || best.bandwidth))),
      detailLine("Codecs", best && best.codecs),
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
      detailLine("Page", candidate.pageUrl || location.href),
      detailLine("Frame", candidate.frameUrl),
      detailLine("Media URL", candidate.url),
    ].filter(Boolean);
    body.append(...lines);
    details.append(detailsSummary, body);
    copy.append(title, meta);
    if (source.textContent) copy.append(source);
    copy.append(details);
    row.append(radio, copy);
    row.addEventListener("click", event => {
      if (event.target === radio || event.target.closest("details")) return;
      selectedLogicalId = id;
      pickerStatus = "";
      pickerStatusKind = "";
      render();
    });
    return row;
  }

  async function refreshPickerCandidates() {
    pickerLoading = true;
    pickerStatus = "Detecting media…";
    pickerStatusKind = "";
    render();
    try {
      const snapshot = await browser.runtime.sendMessage({ type: GET_LOGICAL_CANDIDATES_TYPE });
      pickerCandidates = Array.isArray(snapshot && snapshot.candidates) ? snapshot.candidates : [];
      if (!pickerCandidates.some(candidate => String(candidate.logicalMediaId || candidate.stableMediaId || "") === selectedLogicalId)) {
        selectedLogicalId = "";
      }
      if (current) current = Object.freeze(Object.assign({}, current, { candidateCount: safeCount(Math.max(1, pickerCandidates.length)) }));
      pickerStatus = pickerCandidates.length
        ? `${pickerCandidates.length} media item${pickerCandidates.length === 1 ? "" : "s"} detected. Choose exactly one.`
        : "No media is currently available. Start or resume playback, then reopen the picker.";
      pickerStatusKind = pickerCandidates.length ? "" : "error";
    } catch (error) {
      pickerCandidates = [];
      selectedLogicalId = "";
      pickerStatus = `Could not read detected media: ${error && error.message ? error.message : String(error)}`;
      pickerStatusKind = "error";
    } finally {
      pickerLoading = false;
      render();
    }
  }

  async function sendSelected(target) {
    if (!selectedLogicalId) {
      pickerStatus = "Choose one media item first.";
      pickerStatusKind = "error";
      render();
      return;
    }
    pickerLoading = true;
    pickerStatus = `Sending selected media to ${target === "1dm" ? "1DM+" : "XDM"}…`;
    pickerStatusKind = "";
    render();
    try {
      const result = await browser.runtime.sendMessage({
        type: target === "1dm" ? SEND_1DM_TYPE : SEND_XDM_TYPE,
        logicalMediaIds: [selectedLogicalId]
      });
      if (!result || result.ok !== true) throw new Error(result && result.error || "Media handoff failed");
      pickerStatus = `Sent selected media to ${target === "1dm" ? "1DM+" : "XDM"}.`;
      pickerStatusKind = "ok";
      pickerOpen = false;
    } catch (error) {
      pickerStatus = error && error.message ? error.message : String(error);
      pickerStatusKind = "error";
    } finally {
      pickerLoading = false;
      render();
    }
  }

  function pickerOverlay() {
    if (!pickerOpen) return null;
    const backdrop = make("div", "xdm-picker-backdrop");
    backdrop.setAttribute("role", "presentation");
    backdrop.addEventListener("click", event => {
      if (event.target === backdrop) closePicker();
    });
    const picker = make("section", "xdm-picker");
    picker.setAttribute("role", "dialog");
    picker.setAttribute("aria-modal", "true");
    picker.setAttribute("aria-label", "Choose detected media");
    const header = make("div", "xdm-picker-header");
    const heading = make("div");
    heading.append(
      make("h2", "xdm-picker-title", "Choose media"),
      make("p", "xdm-picker-subtitle", "Select one detected item, inspect its metadata, then send it to XDM or 1DM+.")
    );
    const close = make("button", "xdm-picker-close", "×");
    close.type = "button";
    close.setAttribute("aria-label", "Close media picker");
    close.addEventListener("click", closePicker);
    header.append(heading, close);

    const list = make("div", "xdm-picker-list");
    if (pickerLoading && !pickerCandidates.length) {
      list.append(make("div", "xdm-picker-loading", "Reading detected media…"));
    } else if (!pickerCandidates.length) {
      list.append(make("div", "xdm-picker-empty", "No media detected yet. Start or resume playback and tap the floating button again."));
    } else {
      pickerCandidates.forEach((candidate, index) => list.append(candidateRow(candidate, index)));
    }

    const status = make("div", "xdm-picker-status", pickerStatus);
    status.dataset.kind = pickerStatusKind;
    const footer = make("div", "xdm-picker-footer");
    const xdm = make("button", "xdm-picker-button xdm-picker-button-primary", "Send to XDM");
    const oneDm = make("button", "xdm-picker-button", "Send to 1DM+");
    xdm.type = oneDm.type = "button";
    xdm.disabled = oneDm.disabled = pickerLoading || !selectedLogicalId;
    xdm.addEventListener("click", () => sendSelected("xdm"));
    oneDm.addEventListener("click", () => sendSelected("1dm"));
    footer.append(xdm, oneDm);
    picker.append(header, list, status, footer);
    backdrop.append(picker);
    return backdrop;
  }

  function openPicker() {
    pickerOpen = true;
    expanded = false;
    pickerStatus = "";
    pickerStatusKind = "";
    render();
    refreshPickerCandidates();
  }

  function closePicker() {
    pickerOpen = false;
    pickerLoading = false;
    pickerStatus = "";
    pickerStatusKind = "";
    render();
  }

  function render() {
    if (!current) return false;
    ensureHost();
    mount();
    const tokens = theme();
    shadow.replaceChildren();
    const style = make("style");
    style.textContent = css(tokens);
    const shell = make("div", "xdm-shell");
    shell.dataset.expanded = String(expanded);
    const menu = make("div", "xdm-menu");
    menu.setAttribute("role", "menu");
    menu.setAttribute("aria-hidden", String(!expanded));

    const xdmLink = nativeLink("Open in XDM", current.links.xdm, true);
    const oneDmLink = nativeLink("Open in 1DM+", current.links.oneDm, false);
    if (xdmLink) { xdmLink.setAttribute("role", "menuitem"); menu.appendChild(xdmLink); }
    if (oneDmLink) { oneDmLink.setAttribute("role", "menuitem"); menu.appendChild(oneDmLink); }

    const target = safeTarget(current.target);
    let fab;
    if (current.pickerRequired) {
      fab = make("button", "xdm-fab");
      fab.type = "button";
      fab.setAttribute("aria-haspopup", "dialog");
      fab.setAttribute("aria-expanded", String(pickerOpen));
      fab.addEventListener("click", () => {
        if (pickerOpen) closePicker();
        else openPicker();
      });
    } else if (target === "ask") {
      fab = make("button", "xdm-fab");
      fab.type = "button";
      fab.setAttribute("aria-haspopup", "menu");
      fab.setAttribute("aria-expanded", String(expanded));
      fab.addEventListener("click", () => {
        expanded = !expanded;
        render();
      });
    } else {
      const href = target === "1dm" ? current.links.oneDm : current.links.xdm;
      if (!href) return false;
      fab = make("a", "xdm-fab");
      fab.href = href;
      fab.rel = "external noopener";
      fab.dataset.xdmNativeLink = "true";
      fab.addEventListener("click", () => setTimeout(hide, 900));
    }
    const label = describe(Object.assign({}, current, { target }));
    fab.setAttribute("aria-label", label);
    fab.title = label;
    const icon = make("span");
    icon.innerHTML = iconSvg();
    fab.appendChild(icon);
    fab.appendChild(make("span", "xdm-sr", label));

    if (current.candidateCount > 1) {
      const badge = make("span", "xdm-badge", current.candidateCount >= 99 ? "99+" : String(current.candidateCount));
      badge.setAttribute("aria-hidden", "true");
      fab.appendChild(badge);
    }
    if (current.kind) {
      const kind = make("span", "xdm-kind", current.kind);
      kind.setAttribute("aria-hidden", "true");
      fab.appendChild(kind);
    }

    if (!current.pickerRequired && target === "ask") shell.appendChild(menu);
    shell.appendChild(fab);
    shadow.append(style, shell);
    const overlay = pickerOverlay();
    if (overlay) shadow.appendChild(overlay);
    host.dataset.target = current.pickerRequired ? "picker" : target;
    host.dataset.candidateCount = String(current.candidateCount);
    host.dataset.streamKind = current.kind.toLowerCase();
    return true;
  }

  function scheduleExpiry() {
    if (expiryTimer) clearTimeout(expiryTimer);
    expiryTimer = setTimeout(() => {
      if (!pickerOpen) hide();
      else scheduleExpiry();
    }, FAB_TTL_MS);
  }

  function normalize(input = {}) {
    const links = input.links && typeof input.links === "object" ? input.links : {};
    return Object.freeze({
      target: safeTarget(input.target),
      links: Object.freeze({ xdm: String(links.xdm || ""), oneDm: String(links.oneDm || "") }),
      candidateCount: safeCount(input.candidateCount),
      kind: safeKind(input.streamKind || input.kind),
      url: String(input.url || ""),
      label: String(input.label || "Media ready"),
      pickerRequired: Boolean(input.pickerRequired || input.chooserRequired)
    });
  }

  function show(input = {}) {
    current = normalize(input);
    expanded = !current.pickerRequired && current.target === "ask" && Boolean(input.expanded);
    const rendered = render();
    if (rendered) scheduleExpiry();
    return rendered;
  }

  function update(input = {}) {
    if (!current) return show(input);
    current = normalize(Object.assign({}, current, input, {
      links: Object.assign({}, current.links, input.links || {})
    }));
    const rendered = render();
    if (rendered) scheduleExpiry();
    return rendered;
  }

  function hide() {
    if (expiryTimer) clearTimeout(expiryTimer);
    expiryTimer = null;
    expanded = false;
    pickerOpen = false;
    pickerLoading = false;
    pickerCandidates = [];
    selectedLogicalId = "";
    pickerStatus = "";
    pickerStatusKind = "";
    current = null;
    if (host) host.remove();
    host = null;
    shadow = null;
    return true;
  }

  function state() {
    return current ? Object.freeze({
      target: current.target,
      candidateCount: current.candidateCount,
      kind: current.kind,
      expanded,
      pickerRequired: current.pickerRequired,
      pickerOpen,
      hostId: HOST_ID
    }) : null;
  }

  const API = Object.freeze({ show, update, hide, state, openPicker, closePicker, hostId: HOST_ID });
  globalThis.XdmLauncherUiV3 = API;
  globalThis.XdmLauncherUiV2 = API;
  globalThis.XdmLauncherUiV1 = API;
})();
