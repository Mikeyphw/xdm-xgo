#!/usr/bin/env python3
"""1DM-style media locator parity with MP01 app-paired encrypted Firefox capture."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent.parent
errors = []

def read(rel):
    p = ROOT / rel
    if not p.is_file():
        errors.append(f"missing file: {rel}")
        return ""
    return p.read_text(encoding="utf-8", errors="replace")

def need(text, token, label):
    if token not in text: errors.append(f"{label}: missing {token}")

def forbid(text, token, label):
    if token in text: errors.append(f"{label}: forbidden {token}")

handoff = read("browser-extension/src/main/extension/xdm-firefox/handoff.js")
config = read("browser-extension/src/main/extension/xdm-firefox/generated-config.template.js")
detector = read("browser-extension/src/main/extension/xdm-firefox/detector-core.js")
observer = read("browser-extension/src/main/extension/xdm-firefox/network-observer.js")
page_sniffer = read("browser-extension/src/main/extension/xdm-firefox/page-sniffer.js")
store = read("browser-extension/src/main/extension/xdm-firefox/candidate-store.js")
contract = read("browser-integration/src/main/kotlin/com/mikeyphw/xdm/android/browser/XdmBrowserDeepLinkContract.kt")
parser = read("browser-integration/src/main/kotlin/com/mikeyphw/xdm/android/browser/XdmBrowserDeepLinkParser.kt")
payload = read("browser-integration/src/main/kotlin/com/mikeyphw/xdm/android/browser/XdmBrowserDeepLinkPayload.kt")
export_models = read("app/src/main/kotlin/com/mikeyphw/xdm/android/BrowserExtensionExportModels.kt")
legacy = read("app/src/main/kotlin/com/mikeyphw/xdm/android/BrowserCaptureEnvelopeManager.kt")
locator = read("app/src/main/kotlin/com/mikeyphw/xdm/android/MediaLocatorActivity.kt")
view_model = read("app/src/main/kotlin/com/mikeyphw/xdm/android/MainViewModel.kt")
screen = read("app/src/main/kotlin/com/mikeyphw/xdm/android/ui/media/MediaInboxScreen.kt")
media_classifier = read("media/src/main/kotlin/com/mikeyphw/xdm/android/media/MediaInboxContract.kt")
media_engine = read("media/src/main/kotlin/com/mikeyphw/xdm/android/media/MediaSniffingEngine.kt")
release_test = read("browser-extension/tests/test_release_gate.js")
detector_test = read("browser-extension/tests/test_detector.js")
background_test = read("browser-extension/tests/test_background.js")
parser_test = read("browser-integration/src/test/kotlin/com/mikeyphw/xdm/android/browser/XdmBrowserDeepLinkParserTest.kt")
phase5_extension_test = read("browser-extension/src/test/kotlin/com/mikeyphw/xdm/android/browserextension/BugHuntPhase5BrowserExtensionContractTest.kt")
parity_test = read("app/src/test/kotlin/com/mikeyphw/xdm/android/MediaLocatorParityContractTest.kt")
workflow = (REPO / ".github/workflows/android.yml").read_text(encoding="utf-8", errors="replace")
project_manifest = read("PROJECT_MANIFEST.json")

# MP01: v3 still names the detection/model generation, but browser media capture
# MUST use app-instance-paired encrypted v2 transport. v3 capture navigation is
# categorically rejected. Public URLs may still use the v1 Add review.
for token in ('CurrentVersion = 3', 'EncryptedCaptureVersion = 2'):
    need(contract, token, "deep-link version contract")
for token in ('params.set("v"', 'params.set("url"', 'sanitizeHeaderBag',
              'pairedCaptureConfig', 'crypto.subtle', 'RSA-OAEP', 'AES-GCM',
              '://capture?v=2&sid=', '&kid=', '&ek=', '&iv=', '&ct='):
    need(handoff, token, "paired encrypted-v2 Firefox capture")
need(config, '@@CAPTURE_PAIRING_CONFIG@@', "app-paired extension export template")
for token in ('params.set("headers"', 'params.set("proposedHeaders"',
              'params.set("finalHeaders"', 'params.set("candidates"'):
    forbid(handoff, token, "plaintext credential or candidate navigation")
for token in ('contentLength:', 'durationMs:', 'thumbnailUrl:'):
    need(handoff, token, "media metadata preserved inside encrypted envelope")
need(parser, 'EncryptedCaptureVersion -> parseEncryptedCaptureEnvelope', "encrypted capture parser")
need(parser, 'XdmBrowserDeepLinkContract.CurrentVersion ->', "legacy v3 capture rejection")
need(parser, 'XdmBrowserDeepLinkRejection.UnsafeEnvelope', "legacy plaintext capture rejection")
need(payload, 'hasEncryptedCaptureEnvelope', "encrypted capture model")
forbid(export_models, 'appVersion != metadata.appVersion', "XPI staleness")
need(legacy, 'Legacy v2 browser capture key no longer matches this app install.', "legacy-key migration guidance")

# Repository-level signed publication must also be keyless; otherwise CI would still require retired RSA inputs.
for token in ('XDM_CAPTURE_KEY_ID', 'XDM_CAPTURE_PUBLIC_KEY_SPKI', 'XDM_CAPTURE_OAEP_HASH', 'Require browser capture release key inputs'):
    forbid(workflow, token, "signed-release keyless-v3 cutover")
need(project_manifest, '"browser_release_gate"', "project manifest browser release truth")
need(project_manifest, 'direct-v3 keyless', "project manifest keyless release truth")

# Replay context and optional metadata promised by v3.
for token in ('"accept-language"', '"authorization"', '"cookie"', '"referer"', '"user-agent"', '"range"'):
    need(handoff, token, "v3 replay header allowlist")
    need(parser, token, "Android v3 replay header allowlist")
need(observer, '"accept-language"', "privileged webRequest header capture")
need(page_sniffer, '"accept-language"', "page-side visible header capture")
# Preserve metadata and final-sent-header evidence inside ciphertext, never
# via the Android URI query. The executable crypto round trip is tested in Node.
secure_test = read("browser-extension/tests/test_secure_handoff.js")
need(release_test, 'assert(!safe.includes("headers="))', "public Add privacy regression")
need(release_test, 'assert.equal(unsigned,"")', "unpaired signed-capture fail-closed regression")
for token in ('json.candidates[0].url,sensitive',
              'json.candidates[0].finalHeaders.authorization',
              'RSA-OAEP', 'AES-GCM', 'xdm-capture-v2|forged'):
    need(secure_test, token, "encrypted capture confidentiality/integrity regression")
need(parser_test, 'extensionCaptureParsesOptionalSizeDurationAndThumbnailMetadata', "metadata parser regression")
need(phase5_extension_test, 'SerializesOnlySanitizedAllowlistedReplayContext', "Phase-5 evidence retention regression")
need(phase5_extension_test, 'assertFalse(handoff.contains("params.set(\\"headers\\""))', "Phase-5 plaintext navigation rejection")
forbid(phase5_extension_test, 'assertTrue(handoff.contains("params.set(\\"headers\\""))', "retired plaintext-v3 test assertion")

# False-positive controls and evidence promotion.
for token in ('HARD_NON_MEDIA_MIME_RE', 'possible-manifest-extension', 'manifestByMime', 'manifestByExtension'):
    need(detector, token, "browser response classifier")
need(observer, 'visibleCandidateSnapshot', "visible-vs-internal candidate separation")
need(observer, 'analysis.manifestBody', "manifest body promotion")
need(observer, 'reason: analysis.hlsBody ? "hls-body" : "dash-body"', "manifest promotion reason")
need(store, 'mergedQuality', "strong-candidate downgrade prevention")
for token in ('JSON response must beat a misleading .mp4 suffix', 'manifest suffix alone must not auto-offer', 'later weak observations must not downgrade promoted evidence'):
    need(detector_test, token, "detector regression")
for token in ('suffix-only manifest evidence stays hidden by default', 'verified HLS body promotes retained privileged evidence', 'Accept-Language must survive privileged request capture'):
    need(background_test, token, "background evidence regression")

# App/live locator follows the same evidence boundary.
for token in (
    "document.querySelectorAll('video,audio,source')",
    'window.fetch = async function',
    'XMLHttpRequest',
    'MutationObserver',
    "/^(video|audio|fetch|xmlhttprequest)$/.test(initiator)",
    'MediaSniffingEngine()',
    'saveMediaCaptureWithVariants',
    'candidate.variants',
    'MediaRequestHandoffStore.rememberCapture',
    'ACTION_INTERNAL_MEDIA_CAPTURE_READY',
):
    need(locator, token, "live media locator")
forbid(locator, 'ExternalHandoffReviewActivity::class.java', "obsolete locator deep-link reparse path")
forbid(locator, 'MEDIA_EXT.test(entry.name)', "live performance-resource false-positive path")
for token in ('hardNonMediaMime -> MediaSourceKind.Unknown', 'application/json', 'text/html', 'image/'):
    need(media_classifier, token, "app media classifier")
for token in ('structuredMediaValuePattern', 'mediaTagPattern'):
    need(media_engine, token, "app media evidence extraction")
for token in ('cssUrlPattern.findAll', 'htmlAttributePattern.findAll'):
    forbid(media_engine, token, "generic app-side resource scraping")

capture = view_model.split('private suspend fun executeCaptureMediaCommand', 1)[-1].split('private suspend fun openExternalAddDraft', 1)[0]
need(capture, 'AutomationRejectionReason.NoMediaDetected', "app final media authority")
need(capture, 'Non-media capture ignored', "false-positive feedback")
forbid(capture, 'openExternalAddDraft', "media rejection fallback")
need(screen, 'Static inspection does not run page JavaScript.', "truthful static/live locator copy")
need(screen, 'Live locator can observe media loaded by the page.', "truthful live-locator capability copy")
need(parity_test, 'browserAndAppKeepWeakEvidenceInternalUntilCorroboratedAndNeverFallbackToGenericDownload', "Android parity contract")

if errors:
    print("1DM media locator / XPI v3 validation failed:", file=sys.stderr)
    for error in errors: print(f"- {error}", file=sys.stderr)
    raise SystemExit(1)
print("1DM media locator / XPI v3 validation passed")
