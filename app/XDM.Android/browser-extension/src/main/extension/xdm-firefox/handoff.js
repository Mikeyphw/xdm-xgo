(() => {
  const CONFIG = globalThis.XdmExtensionConfig || {};
  if (globalThis.XdmHandoffV1) return;

  const TARGETS = Object.freeze({ XDM: "xdm", ONE_DM: "1dm", ASK: "ask" });
  const HEADER_ALLOWLIST = new Set(["authorization", "cookie", "referer", "user-agent", "origin", "accept", "accept-language", "range"]);
  const MAX_HEADER_BLOCK = 12 * 1024;
  const HANDOFF_LIFETIME_MS = 10 * 60 * 1000;

  function randomNonce() {
    const bytes = new Uint8Array(18);
    if (globalThis.crypto && typeof globalThis.crypto.getRandomValues === "function") globalThis.crypto.getRandomValues(bytes);
    else for (let i = 0; i < bytes.length; i += 1) bytes[i] = Math.floor(Math.random() * 256);
    return Array.from(bytes).map(value => value.toString(16).padStart(2, "0")).join("");
  }

  function senderProof(input = {}) {
    const createdAt = Math.max(1, Math.trunc(Number(input.pageObservationCreatedAt || Date.now())));
    const expiresAt = Math.max(createdAt + 1, Math.trunc(Number(input.pageObservationExpiresAt || createdAt + HANDOFF_LIFETIME_MS)));
    return Object.freeze({
      nonce: String(input.pageObservationNonce || randomNonce()).replace(/[^A-Za-z0-9._:-]/g, "").slice(0, 256),
      createdAt,
      expiresAt,
    });
  }

  function safeHttpUrl(value) {
    const raw = String(value || "").trim();
    if (!raw) return "";
    try {
      const base = globalThis.document && document.baseURI ? document.baseURI : (globalThis.location && location.href ? location.href : undefined);
      const url = new URL(raw, base);
      return /^(?:https?|ftp):$/.test(url.protocol) && !url.username && !url.password ? url.href : "";
    } catch (_) { return ""; }
  }

  function encodeSchemeData(value) { return encodeURI(String(value || "")).replace(/#/g, "%23"); }

  function cleanFilename(title, url, mimeType = "") {
    let suffix = "";
    try {
      const match = new URL(url).pathname.match(/\.(m3u8|mpd|mp4|m4v|webm|mkv|mov|avi|flv|mpeg|mpg|ogv|mp3|m4a|aac|flac|wav|ogg|opus)$/i);
      if (match && !/^(m3u8|mpd)$/i.test(match[1])) suffix = `.${match[1].toLowerCase()}`;
    } catch (_) {}
    if (!suffix) {
      const type = String(mimeType || "").split(";", 1)[0].toLowerCase();
      if (type === "video/mp4") suffix = ".mp4";
      else if (type === "audio/mpeg") suffix = ".mp3";
      else if (type === "audio/mp4") suffix = ".m4a";
    }
    const documentTitle = globalThis.document && document.title ? document.title : "";
    const base = String(title || documentTitle || "download")
      .replace(/[\\/:*?"<>|\u0000-\u001f]+/g, " ").replace(/\s+/g, " ").trim().slice(0, 140) || "download";
    return `${base}${suffix}`.slice(0, 160);
  }

  function mediaKind(url, mimeType) {
    const type = String(mimeType || "").split(";", 1)[0].toLowerCase();
    if (type.startsWith("video/")) return "video";
    if (type.startsWith("audio/")) return "audio";
    if (/\.m3u8(?:$|[?#])/i.test(url)) return "hls";
    if (/\.mpd(?:$|[?#])/i.test(url)) return "dash";
    return "media";
  }

  function validScheme(value) {
    const scheme = String(value || CONFIG.xdmScheme || "xdmdownload").toLowerCase();
    return /^[a-z][a-z0-9+.-]{1,40}$/.test(scheme) ? scheme : "";
  }

  function cleanText(value, limit) {
    return String(value || "").replace(/[\u0000-\u001f\u007f]/g, " ").trim().slice(0, limit);
  }

  function sanitizeHeaderBag(value) {
    const result = {};
    for (const [rawName, rawValue] of Object.entries(value && typeof value === "object" ? value : {})) {
      const name = String(rawName || "").trim().toLowerCase();
      if (!HEADER_ALLOWLIST.has(name)) continue;
      const headerValue = String(rawValue == null ? "" : rawValue).replace(/[\r\n\u0000-\u001f\u007f]+/g, " ").trim().slice(0, 8192);
      if (headerValue) result[name] = headerValue;
    }
    return result;
  }

  function headerBlock(value) {
    const lines = Object.entries(sanitizeHeaderBag(value)).slice(0, 24).map(([name, headerValue]) => `${name}: ${headerValue}`);
    let result = "";
    for (const line of lines) {
      const next = result ? `${result}\n${line}` : line;
      if (next.length > MAX_HEADER_BLOCK) break;
      result = next;
    }
    return result;
  }

  function candidateHeaderBags(candidate = {}) {
    const handoff = candidate.browserHandoff && typeof candidate.browserHandoff === "object" ? candidate.browserHandoff : {};
    const proposed = handoff.proposedHeaders && typeof handoff.proposedHeaders === "object" ? handoff.proposedHeaders.headers : candidate.headers;
    const finalSent = handoff.finalHeaders && typeof handoff.finalHeaders === "object" ? handoff.finalHeaders.headers : null;
    const proposedHeaders = headerBlock(proposed || {});
    const finalHeaders = headerBlock(finalSent || {});
    return {
      proposedHeaders,
      finalHeaders,
      // XAR10: executable raw headers require final sent-header evidence; proposed
      // pre-send headers remain audit context and must not replay as runtime authority.
      rawHeaders: finalHeaders,
      finalHeadersReady: Boolean(finalHeaders),
    };
  }

  // Public-only fallback: never put signed query strings or credential-bearing
  // media references in browser navigation. Encrypted capture handles those.
  function publicUrl(raw) {
    const value = safeHttpUrl(raw);
    if (!value || !/^https?:/i.test(value)) return "";
    const uri = new URL(value);
    if (uri.search || uri.hash || uri.username || uri.password) return "";
    if (/\b(?:token|sig|signature|auth|jwt|secret|session|key|credential)\b/i.test(uri.pathname)) return "";
    return value;
  }

  function hasCredentialHeader(input = {}) {
    const handoff = input.browserHandoff && typeof input.browserHandoff === "object" ? input.browserHandoff : {};
    return [input.headers, handoff.proposedHeaders && handoff.proposedHeaders.headers,
      handoff.finalHeaders && handoff.finalHeaders.headers].some(bag =>
      Object.keys(sanitizeHeaderBag(bag || {})).some(name => name === "authorization" || name === "cookie"));
  }

  function buildXdmAdd(input = {}) {
    const url = publicUrl(input.url); const scheme = validScheme(input.scheme);
    if (!url || !scheme) return "";
    const params = new URLSearchParams(); params.set("v", "1"); params.set("url", url);
    const pageUrl = publicUrl(input.pageUrl || ""); if (pageUrl) params.set("page", pageUrl);
    const title = cleanText(input.title, 240); if (title) params.set("title", title);
    const filename = cleanFilename(input.title, url, input.mimeType); if (filename) params.set("filename", filename);
    const mime = String(input.mimeType || "").split(";", 1)[0].trim().toLowerCase().slice(0, 120); if (mime) params.set("mime", mime);
    return `${scheme}://add?${params.toString()}`;
  }

  function buildXdmCapture(input = {}) {
    // Unpaired browsers may send only a non-secret URL to the normal Add review.
    // Authenticated/signed media MUST use buildCaptureSession() with XPI pairing.
    if (hasCredentialHeader(input)) return "";
    return buildXdmAdd(input);
  }

    function compactSessionCandidate(candidate = {}, fallbackPageUrl = "", fallbackTitle = "", revision = 0) {
    const url = safeHttpUrl(candidate.url);
    if (!url) return null;
    const handoff = candidate.browserHandoff && typeof candidate.browserHandoff === "object" ? candidate.browserHandoff : {};
    const proposed = handoff.proposedHeaders && typeof handoff.proposedHeaders === "object" ? handoff.proposedHeaders.headers : candidate.headers;
    const finalSent = handoff.finalHeaders && typeof handoff.finalHeaders === "object" ? handoff.finalHeaders.headers : null;
    const evidence = Array.isArray(candidate.evidence)
      ? candidate.evidence.map(item => cleanText(item, 48)).filter(Boolean).slice(0, 8)
      : [];
    const result = {
      url,
      pageUrl: safeHttpUrl(candidate.pageUrl || candidate.tabUrl || fallbackPageUrl),
      frameUrl: safeHttpUrl(candidate.frameUrl || ""),
      title: cleanText(candidate.title || fallbackTitle, 240),
      contentType: String(candidate.contentType || candidate.mimeType || "").split(";", 1)[0].trim().toLowerCase().slice(0, 120),
      contentLength: Math.max(0, Math.trunc(Number(candidate.contentLength || 0))),
      durationMs: Math.max(0, Math.trunc(Number(candidate.durationMs || 0))),
      thumbnailUrl: safeHttpUrl(candidate.thumbnailUrl || ""),
      thumbnailProvenance: cleanText(candidate.thumbnailProvenance || "Unknown", 32).replace(/[^A-Za-z]/g, "") || "Unknown",
      stableMediaId: String(candidate.stableMediaId || "").trim().replace(/[^A-Za-z0-9._:-]/g, "").slice(0, 160),
      requestId: cleanText(candidate.requestId || handoff.requestId || "", 96).replace(/[^A-Za-z0-9._:-]/g, ""),
      requestGeneration: Math.max(0, Math.trunc(Number(candidate.requestGeneration || handoff.requestGeneration || 0))),
      requestFingerprint: String(candidate.requestFingerprint || "").trim().replace(/[^A-Za-z0-9._:-]/g, "").slice(0, 96),
      sessionRevision: Math.max(1, Math.trunc(Number(candidate.sessionRevision || revision || handoff.requestGeneration || 1))),
      evidenceExpiresAtEpochMs: Math.max(0, Math.trunc(Number(candidate.evidenceExpiresAtEpochMs || 0))),
      quality: cleanText(candidate.quality || "strong", 24).toLowerCase() || "strong",
      reason: cleanText(candidate.reason || "browser-media", 96) || "browser-media",
      streamKind: cleanText(candidate.streamKind || mediaKind(url, candidate.contentType), 24).toLowerCase() || "media",
      manifest: Boolean(candidate.manifest || /\.(?:m3u8|mpd)(?:$|[?#])/i.test(url)),
      playbackObserved: Boolean(candidate.playbackObserved),
      evidence,
      canonicalUrl: safeHttpUrl(candidate.canonicalUrl || ""),
      logicalMediaId: String(candidate.logicalMediaId || candidate.stableMediaId || "").trim().replace(/[^A-Za-z0-9._:-]/g, "").slice(0, 160),
      manifestRole: cleanText(candidate.manifestRole || (candidate.manifest ? "media" : "resource"), 24).toLowerCase(),
      confidence: Math.max(0, Math.min(2000, Math.trunc(Number(candidate.confidence || 0)))),
      observationCount: Math.max(1, Math.min(1000000, Math.trunc(Number(candidate.observationCount || 1)))),
      segmentCount: Math.max(0, Math.min(1000000, Math.trunc(Number(candidate.segmentCount || 0)))),
      encryptedAes128: Boolean(candidate.encryptedAes128),
      protectedMedia: Boolean(candidate.protectedMedia),
      lowLatency: Boolean(candidate.lowLatency),
      variantInfo: (candidate.variantInfo || []).slice(0, 32).map(item => ({
        url: safeHttpUrl(item && item.url),
        bandwidth: Math.max(0, Math.trunc(Number(item && (item.averageBandwidth || item.bandwidth) || 0))),
        width: Math.max(0, Math.trunc(Number(item && item.width || 0))),
        height: Math.max(0, Math.trunc(Number(item && item.height || 0))),
        codecs: cleanText(item && item.codecs || "", 160),
        audioGroup: cleanText(item && item.audioGroup || "", 80),
        subtitleGroup: cleanText(item && item.subtitleGroup || "", 80),
      })).filter(item => item.url),
      trackInfo: (candidate.trackInfo || []).slice(0, 32).map(item => ({
        url: safeHttpUrl(item && item.url),
        type: cleanText(item && item.type || "track", 24).toLowerCase(),
        groupId: cleanText(item && item.groupId || "", 80),
        name: cleanText(item && item.name || "", 120),
        language: cleanText(item && item.language || "", 48),
        default: Boolean(item && item.default),
      })).filter(item => item.url),
      proposedHeaders: sanitizeHeaderBag(proposed || {}),
      // Only onSendHeaders evidence tied to this exact request may authorize replay.
      finalHeaders: (
        handoff.requestId && String(handoff.requestId) === String(candidate.requestId || "") &&
        Number(handoff.requestGeneration || 0) > 0 &&
        Number(handoff.requestGeneration) === Number(candidate.requestGeneration || 0) &&
        handoff.finalHeaders && handoff.finalHeaders.kind === "FinalSent" &&
        Math.abs(Date.now() - Number(handoff.requestGeneration)) <= 45 * 1000
      ) ? sanitizeHeaderBag(finalSent || {}) : {},
    };
    for (const key of ["pageUrl", "frameUrl", "title", "contentType", "thumbnailUrl", "stableMediaId", "requestId", "requestFingerprint", "canonicalUrl", "logicalMediaId"]) {
      if (!result[key]) delete result[key];
    }
    if (!result.contentLength) delete result.contentLength;
    if (!result.durationMs) delete result.durationMs;
    if (!result.evidence.length) delete result.evidence;
    if (!result.variantInfo.length) delete result.variantInfo;
    if (!result.trackInfo.length) delete result.trackInfo;
    if (!Object.keys(result.proposedHeaders).length) delete result.proposedHeaders;
    if (!Object.keys(result.finalHeaders).length) delete result.finalHeaders;
    return result;
  }

  function base64Url(bytes) {
    let binary = "";
    for (let offset = 0; offset < bytes.length; offset += 8192) {
      binary += String.fromCharCode(...bytes.subarray(offset, offset + 8192));
    }
    return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
  }

  function unbase64Url(raw) {
    const text = String(raw || "").replace(/-/g, "+").replace(/_/g, "/");
    const binary = atob(text + "=".repeat((4 - text.length % 4) % 4));
    return Uint8Array.from(binary, char => char.charCodeAt(0));
  }

  function pairedCaptureConfig() {
    const kid = String(CONFIG.captureKeyId || "");
    const spki = String(CONFIG.capturePublicKeySpkiBase64Url || "");
    return /^[a-f0-9]{24}$/.test(kid) && /^[A-Za-z0-9_-]{350,1500}$/.test(spki) &&
      CONFIG.captureOaepHash === "SHA-1" ? { kid, spki } : null;
  }

  async function buildCaptureSession(input = {}) {
    const requested = (Array.isArray(input.candidates) ? input.candidates : [])
      .map(candidate => compactSessionCandidate(candidate, input.pageUrl, input.title, input.revision))
      .filter(Boolean).slice(0, 24);
    const primary = requested[0] || compactSessionCandidate(input, input.pageUrl, input.title, input.revision);
    if (!primary) return "";
    const primarySource = (Array.isArray(input.candidates) ? input.candidates : [])
      .find(item => item && safeHttpUrl(item.url)) || input;
    const scheme = validScheme(input.scheme);
    if (!scheme) return "";
    const pairing = pairedCaptureConfig();
    if (!pairing) {
      // An unpaired/keyless XPI can only use the normal public URL Add review.
      // Never silently downgrade a credential-bearing media capture to plaintext.
      return buildXdmCapture(Object.assign({}, primarySource, { scheme,
        pageUrl: input.pageUrl || primary.pageUrl, title: input.title || primary.title }));
    }
    if (!globalThis.crypto || !globalThis.crypto.subtle || !globalThis.crypto.getRandomValues) {
      throw new Error("Encrypted media handoff requires WebCrypto. Reopen the paired XPI.");
    }
    const subtle = globalThis.crypto.subtle;
    const sessionId = String(input.sessionId || ("browser-" + randomNonce()))
      .replace(/[^A-Za-z0-9._:-]/g, "").slice(0, 96);
    const revision = Math.max(1, Math.trunc(Number(input.revision || primary.sessionRevision || Date.now())));
    const createdAt = Date.now(), expiresAt = createdAt + HANDOFF_LIFETIME_MS;
    const spkiKey = await subtle.importKey("spki", unbase64Url(pairing.spki),
      { name: "RSA-OAEP", hash: "SHA-1" }, false, ["encrypt"]);
    const contentKey = globalThis.crypto.getRandomValues(new Uint8Array(32));
    const aesKey = await subtle.importKey("raw", contentKey, { name: "AES-GCM" }, false, ["encrypt"]);
    const wrappedKey = new Uint8Array(await subtle.encrypt({ name: "RSA-OAEP" }, spkiKey, contentKey));
    const aad = new TextEncoder().encode(`xdm-capture-v2|${sessionId}|${pairing.kid}`);
    const total = Math.max(requested.length, Math.trunc(Number(input.totalCandidateCount || requested.length)));
    const sourceCandidates = requested.length ? requested : [primary];
    for (let count = sourceCandidates.length; count >= 1; count -= 1) {
      const message = {
        v: 1, sid: sessionId, revision, createdAt, expiresAt,
        pageUrl: safeHttpUrl(input.pageUrl || primary.pageUrl),
        title: cleanText(input.title || primary.title, 240),
        totalCandidateCount: Math.max(total, sourceCandidates.length),
        truncated: Boolean(input.truncated || count < sourceCandidates.length || total > count),
        candidates: sourceCandidates.slice(0, count),
      };
      const clear = new TextEncoder().encode(JSON.stringify(message));
      if (clear.length > 56 * 1024) continue;
      // Generate a NEW GCM nonce for every truncation attempt, never reuse IV/key.
      const iv = globalThis.crypto.getRandomValues(new Uint8Array(12));
      const ct = new Uint8Array(await subtle.encrypt({ name: "AES-GCM", iv,
        additionalData: aad, tagLength: 128 }, aesKey, clear));
      if (ct.length > 60 * 1024) continue;
      const uri = `${scheme}://capture?v=2&sid=${encodeURIComponent(sessionId)}` +
        `&kid=${encodeURIComponent(pairing.kid)}&ek=${base64Url(wrappedKey)}` +
        `&iv=${base64Url(iv)}&ct=${base64Url(ct)}`;
      if (new TextEncoder().encode(uri).length <= 64 * 1024) return uri;
    }
    // Never downgrade or drop all candidates when encrypted payload is oversized.
    return "";
  }

    // Compatibility symbol retained for existing clients. New app-exported XPIs encrypt.
  async function buildEncryptedCaptureSession(input = {}) { return buildCaptureSession(input); }

  function encodeIntentString(value) {
    return encodeURIComponent(String(value || ""));
  }

  function buildOneDm(input = {}) {
    const url = safeHttpUrl(input.url);
    if (!url) return "";

    // 1DM accepts Android intent URI string extras for the suggested filename and
    // referring page. Supplying both title and extra_filename keeps compatibility
    // with the receiver variants present in 1DM+ while preserving the media URL as
    // the actual download target.
    const filename = cleanFilename(input.title, url, input.mimeType || input.contentType);
    const pageUrl = safeHttpUrl(input.pageUrl || input.tabUrl || "");
    const parts = [
      `intent:${encodeSchemeData(url)}#Intent`,
      "scheme=idmdownload",
      "package=idm.internet.download.manager.plus",
    ];
    if (filename) {
      const encodedFilename = encodeIntentString(filename);
      parts.push(`S.title=${encodedFilename}`);
      parts.push(`S.extra_filename=${encodedFilename}`);
      parts.push(`S.com.android.extra.filename=${encodedFilename}`);
    }
    if (pageUrl) parts.push(`S.extra_referer=${encodeIntentString(pageUrl)}`);
    parts.push("end");
    return parts.join(";");
  }
  function buildTargets(input = {}) {
    return Object.freeze({ xdm: buildXdmAdd(input), oneDm: buildOneDm(input), filename: cleanFilename(input.title, input.url, input.mimeType) });
  }

  globalThis.XdmHandoffV1 = Object.freeze({ TARGETS, safeHttpUrl, buildXdmAdd, buildXdmCapture, buildCaptureSession, buildEncryptedCaptureSession, buildOneDm, buildTargets, cleanFilename, mediaKind, sanitizeHeaderBag });
})();
