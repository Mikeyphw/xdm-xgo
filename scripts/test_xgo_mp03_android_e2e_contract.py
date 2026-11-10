#!/usr/bin/env python3
"""MP03 production Android -> Go -> platform network -> Compose security contracts."""
from __future__ import annotations
from pathlib import Path
import re
import unittest
ROOT=Path(__file__).resolve().parents[1]
APP=ROOT/'app/XDM.Android/app/src/main/kotlin/com/mikeyphw/xdm/android'
RUNTIME=ROOT/'engine/runtime'

class AndroidE2EContract(unittest.TestCase):
    def read(self, rel): return (ROOT/rel).read_text()
    def assert_platform_kind_contract(self, broker):
        # The allowed kind switch can grow without changing the older MP03
        # request kinds. Verify declarations AND the actual allowlist; do not
        # depend on adjacent enum names or exact Go formatting.
        required = {
            "ExternalMediaTool": "external_media_tool",
            "ManifestFetch": "manifest_fetch",
            "MP08Finalization": "mp08_finalization",
        }
        for kind, wire in required.items():
            self.assertRegex(
                broker,
                rf"(?m)^[ \t]*{re.escape(kind)}[ \t]+Kind[ \t]*=[ \t]*\"{re.escape(wire)}\"[ \t]*$",
                f"missing or changed Go platform Kind: {kind}",
            )
        match = re.search(
            r"(?s)\bfunc\s*\(\s*k\s+Kind\s*\)\s+Valid\s*\(\s*\)\s+bool\s*\{\s*switch\s+k\s*\{\s*case\s+([\w,\s]+?):\s*return\s+true\s+default\s*:\s*return\s+false\s*\}",
            broker,
        )
        self.assertIsNotNone(match, "platform Kind.Valid must reject unknown kinds")
        allowed = {kind.strip() for kind in match.group(1).split(",")}
        self.assertTrue(required.keys() <= allowed, f"platform Kind.Valid missing {required.keys() - allowed}")

    def test_platform_kind_contract_rejects_missing_legacy_or_new_wiring(self):
        source = self.read("engine/runtime/platform/broker.go")
        mutations = []
        for kind, wire in (("ManifestFetch", "manifest_fetch"),
                           ("ExternalMediaTool", "external_media_tool"),
                           ("MP08Finalization", "mp08_finalization")):
            changed, count = re.subn(
                rf'(?m)^[ \t]*{re.escape(kind)}[ \t]+Kind[ \t]*=[ \t]*"{re.escape(wire)}"[ \t]*$',
                '', source, count=1)
            self.assertEqual(count, 1, f"missing declaration anchor: {kind}")
            mutations.append(changed)
        switch = re.search(r'(?s)\bfunc\s*\(\s*k\s+Kind\s*\)\s+Valid\s*\(\s*\)\s+bool\s*\{.*?\}', source)
        self.assertIsNotNone(switch, "missing Kind.Valid switch for negative test")
        for kind in ("ExternalMediaTool", "ManifestFetch", "MP08Finalization"):
            changed = switch.group(0).replace(kind, "", 1)
            self.assertNotEqual(changed, switch.group(0), f"missing Kind.Valid member: {kind}")
            mutations.append(source.replace(switch.group(0), changed, 1))
        changed, count = re.subn(r'(?s)(\bdefault\s*:\s*)return\s+false\b', r'\1return true', source, count=1)
        self.assertEqual(count, 1, "missing fail-closed default")
        mutations.append(changed)
        for index, mutation in enumerate(mutations):
            self.assertNotEqual(mutation, source, f"missing negative mutation anchor {index}")
            with self.subTest(index=index), self.assertRaises(AssertionError):
                self.assert_platform_kind_contract(mutation)
    def test_typed_go_platform_contract_is_live(self):
        broker=self.read('engine/runtime/platform/broker.go')
        engine=self.read('engine/runtime/engine.go')
        bridge=self.read('engine/runtime/android_manifest_resolve.go')
        self.assert_platform_kind_contract(broker)
        self.assertIn('e.handlers[AndroidMediaResolveKind] = e.androidMediaResolveHandler',engine)
        for val in ('platform.ManifestFetch', 'ResolveManifestGraph(ctx, root, fetch, policy)',
                    'manifestRoot(input.CaptureID)', 'decodeAndroidManifestFetch(reply.Payload)',
                    'AuthorizedOrigin: origin', 'MaxManifests: 24', 'graph.DownloadReady',
                    'event.Telemetry, "android.media.command_result"'):
            self.assertIn(val,bridge)
        self.assertNotIn('http.Get(',bridge)
        self.assertNotIn('log.Print',bridge)
        self.assertNotIn('event.Durable, "android.media.command_result", result',bridge)
    def test_android_fetch_uses_expiring_encrypted_capture_not_untrusted_go_headers(self):
        source=(APP/'engine/AndroidAuthorizedManifestFetcher.kt').read_text()
        for value in ('MediaRequestHandoffStore.forCapture(id)', 'root != declaredRoot',
                      'parent == null && requested != root', 'handoff.expiresAtEpochMs <= now',
                      'origin(requested) != rootOrigin', 'handoff.cleartextCredentialsApproved',
                      'handoff.privateNetworkApproved', 'connection.instanceFollowRedirects = false',
                      'connection.inputStream.use', 'bytes.size() + count > max',
                      'connection.disconnect()', 'setRequestProperty(name, value)',
                      'val maxRedirects = 5', 'NetworkSecurityPolicy'):
            self.assertIn(value,source)
        for bad in ('Log.', 'println(', 'CookieManager', 'getSharedPreferences(', 'WebView(', 'MediaRequestHandoffStore.remember('):
            self.assertNotIn(bad,source)
        self.assertIn('val allowedHeaders = setOf(',source)
        self.assertNotIn('payload.optJSONObject("headers")',source)
    def test_jni_pump_non_blocking_and_out_of_band_ephemeral_graph(self):
        disp=(APP/'engine/AndroidPlatformRequestDispatcher.kt').read_text()
        service=(APP/'engine/AndroidEngineProcessAuthority.kt').read_text()
        for val in ('request.optString("kind") == "manifest_fetch"', 'mediaToolScope.launch',
                    'manifestFetcher.fetch(payload)', 'bridge.platformReply'):
            self.assertIn(val,disp)
        for val in ('"android.media.resolve_manifest"', '90_000L',
                    'AndroidAuthorizedManifestFetcher(appContext)', 'pendingMediaCommands.remove(result.requestId)?.complete(result)'):
            self.assertIn(val,service)
        self.assertNotIn('GlobalScope',disp+service)
    def test_existing_kotlin_fallback_and_ui_offer_remain(self):
        wire=(APP/'engine/AndroidMediaUiProtocol.kt').read_text()
        client=(APP/'engine/AndroidMediaUiClient.kt').read_text()
        card=(APP/'ui/media/MediaCaptureCard.kt').read_text()
        inbox=(APP/'ui/media/MediaInboxScreen.kt').read_text()
        schema=(APP/'engine/ManifestGraphV1Contract.kt').read_text()
        self.assertIn('manifestGraph = payload.optJSONObject("manifest_graph")?.let(ManifestGraphV1Contract::decode)',wire)
        # MP04 extends the MP03 API with explicit selection and revision fields.
        # Verify the contract independent of Kotlin parameter line wrapping.
        self.assertRegex(client, r'suspend\s+fun\s+resolveManifest\s*\(\s*captureId:\s*String\s*,\s*selection:\s*ManifestSelectionV1Contract\.Request\?\s*=\s*null\s*,\s*expectedRevision:\s*String\?\s*=\s*null')
        self.assertIn('AndroidMediaUiWire.resolvePayload(requestId, captureId, selection, expectedRevision)',client)
        self.assertIn('onInspectManifest: (MediaCaptureRecord) -> Unit',card)
        self.assertIn('Text("Inspect Go manifest")',card)
        self.assertEqual(inbox.count('onInspectManifest = onInspectGoManifest,'),2)
        self.assertIn('Mp03ManifestReviewDialog(',inbox)
        self.assertIn('selection = manifestChoice,',inbox)
        self.assertIn('goManifestClient.resolveManifest(captureId, manifestChoice, revision)',inbox)
        self.assertRegex(inbox, r'items\s*\(\s*graph\.qualities\b')
        self.assertIn('onSelectionChange(selection.copy(videoId = quality.id',inbox)
        self.assertNotIn('quality.transportUrl',inbox)
        self.assertIn('object ManifestGraphV1Contract',schema)
        self.assertIn('download_ready',schema)
        self.assertIn('fun execute(captureId:',client)
        fallback=(APP/'engine/AndroidMediaPlatformBroker.kt').read_text()
        self.assertIn('"finalize_adaptive"',fallback)
        self.assertIn('FfmpegOperation.FinalizeAdaptive(',fallback)
    def test_mp04_selection_preserves_mp03_readonly_security_boundary(self):
        # The MP04 planner is an ephemeral selection preview; no Go completion
        # permission, Android credentials, stored manifest URLs or Kotlin fallback changes.
        wire=(APP/'engine/AndroidMediaUiProtocol.kt').read_text()
        ui=(APP/'ui/media/MediaInboxScreen.kt').read_text()
        runtime=(RUNTIME/'android_manifest_resolve.go').read_text()
        self.assertIn('manifestSelectionPlan = payload.optJSONObject("manifest_selection_plan")?.let(ManifestSelectionV1Contract::decode)',wire)
        self.assertIn('if (selection != null) put("selection", selection.wire())',wire)
        self.assertIn('if (expectedRevision != null)',wire)
        self.assertIn('manifest_changed_refresh_required',runtime)
        self.assertIn('selection_incompatible_or_stale',runtime)
        self.assertIn('manifestSelectionPlan = null',ui)
        self.assertIn('Plan only — not queued, not downloaded, not Complete.',ui)
        self.assertNotIn('quality.transportUrl',ui)
        self.assertNotIn('android.media.execute',ui)
    def test_ci05_and_tests_are_mandatory(self):
        policy=self.read('scripts/ci/xgo_ci_policy.py')
        for name in ('scripts/test_xgo_mp03_android_e2e_contract.py',
                     'scripts/test_xgo_mp03_android_staleness.py',
                     'tests.update(MP03_PYTHON)', 'DEFAULT_INTERVAL = 5',
                     '"engine/runtime/"', 'subprocess.run(["go", "test", "./..."]'):
            self.assertIn(name,policy)
        self.assertIn('func TestMP03AndroidManifestWire',self.read('engine/runtime/android_manifest_resolve_test.go'))
        self.assertIn('func TestMP03AndroidManifestOrigin',self.read('engine/runtime/android_manifest_resolve_test.go'))

if __name__=='__main__':unittest.main(verbosity=2)
