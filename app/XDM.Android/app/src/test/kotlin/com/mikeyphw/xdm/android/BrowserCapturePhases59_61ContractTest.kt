package com.mikeyphw.xdm.android

import java.io.File
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class BrowserCapturePhases59_61ContractTest {
    private val root = androidRoot()

    @Test
    fun captureSessionsRemainFirstClassAndNonSecretInMediaInbox() {
        val models = source("core-model/src/main/kotlin/com/mikeyphw/xdm/android/model/BrowserCaptureSessionModels.kt")
        val registry = source("media/src/main/kotlin/com/mikeyphw/xdm/android/media/BrowserCaptureSessionRegistry.kt")
        val viewModel = source("app/src/main/kotlin/com/mikeyphw/xdm/android/MainViewModel.kt")
        val screen = source("app/src/main/kotlin/com/mikeyphw/xdm/android/ui/media/MediaInboxScreen.kt")

        assertTrue(models.contains("data class BrowserCaptureSessionSummary"))
        assertTrue(models.contains("data class BrowserCaptureCandidateSummary"))
        assertTrue(registry.contains("no URLs or request headers"))
        assertFalse(registry.contains("sourceUrl"))
        assertFalse(registry.contains("authorization", ignoreCase = true))
        assertTrue(viewModel.contains("browserCaptureSessionRegistry.record"))
        assertTrue(screen.contains("BrowserCaptureSessionHeader"))
        assertTrue(screen.contains("Browser session values stay private and are used only when a request needs them."))
    }

    @Test
    fun firefoxCaptureUsesPairedEncryptedV2AndRejectsPlaintextV3() {
        val contract = source("browser-integration/src/main/kotlin/com/mikeyphw/xdm/android/browser/XdmBrowserDeepLinkContract.kt")
        val parser = source("browser-integration/src/main/kotlin/com/mikeyphw/xdm/android/browser/XdmBrowserDeepLinkParser.kt")
        val handoff = source("browser-extension/src/main/extension/xdm-firefox/handoff.js")
        val config = source("browser-extension/src/main/extension/xdm-firefox/generated-config.template.js")
        val network = source("browser-extension/src/main/extension/xdm-firefox/network-observer.js")

        assertTrue(contract.contains("EncryptedCaptureVersion = 2"))
        assertTrue(contract.contains("CurrentVersion = 3"))
        assertTrue(parser.contains("EncryptedCaptureVersion -> parseEncryptedCaptureEnvelope"))
        assertTrue(parser.contains("XdmBrowserDeepLinkContract.CurrentVersion ->"))
        assertTrue(parser.contains("XdmBrowserDeepLinkParseResult.Rejected(XdmBrowserDeepLinkRejection.UnsafeEnvelope)"))
        assertTrue(config.contains("@@CAPTURE_PAIRING_CONFIG@@"))
        assertTrue(handoff.contains("const pairing = pairedCaptureConfig()"))
        assertTrue(handoff.contains("subtle.encrypt({ name: \"RSA-OAEP\""))
        assertTrue(handoff.contains("subtle.encrypt({ name: \"AES-GCM\""))
        for (parameter in listOf("://capture?v=2&sid=", "&kid=", "&ek=", "&iv=", "&ct=")) {
            assertTrue(handoff.contains(parameter))
        }
        assertTrue(handoff.contains("if (hasCredentialHeader(input)) return \"\""))
        assertTrue(handoff.contains("return buildXdmAdd(input)"))
        assertTrue(network.contains("await handoff.buildCaptureSession({"))
        for (forbidden in listOf("params.set(\"headers\"", "params.set(\"proposedHeaders\"", "params.set(\"finalHeaders\"", "params.set(\"candidates\"")) {
            assertFalse(handoff.contains(forbidden))
        }
    }

    @Test
    fun firefoxTransfersOnlyOneExplicitlySelectedEvidenceBackedCandidatePerReviewHandoff() {
        val store = source("browser-extension/src/main/extension/xdm-firefox/candidate-store.js")
        val network = source("browser-extension/src/main/extension/xdm-firefox/network-observer.js")
        val handoff = source("browser-extension/src/main/extension/xdm-firefox/handoff.js")
        val detector = source("browser-extension/src/main/extension/xdm-firefox/detector-core.js")
        val pageSniffer = source("browser-extension/src/main/extension/xdm-firefox/page-sniffer.js")
        val screen = source("app/src/main/kotlin/com/mikeyphw/xdm/android/ui/media/MediaInboxScreen.kt")

        assertTrue(store.contains("snapshot(tabId"))
        assertTrue(network.contains("visibleCandidateSnapshot(tabId, MAX_CANDIDATES_PER_TAB)"))
        assertTrue(network.contains("function requireSingleSelectedCandidate(tabId, requestedIds, targetLabel)"))
        assertTrue(network.contains("if (ids.length !== 1)"))
        assertTrue(network.contains("if (selected.length !== 1)"))
        assertTrue(network.contains("const chooserRequired = true;"))
        assertTrue(network.contains("const prebuiltXdmLink = \"\";"))
        assertTrue(network.contains("const prebuiltOneDmLink = \"\";"))
        assertTrue(network.contains("const authoritative = proof && proof.requestFingerprint === selected.requestFingerprint"))
        assertTrue(network.contains("Number(proof.requestGeneration || 0) === Number(selected.requestGeneration || 0)"))
        assertTrue(network.contains("finalHeaders: authoritative ? proof.browserHandoff.finalHeaders : null,"))
        assertTrue(network.contains("headers: authoritative ? proof.headers : {},"))
        assertTrue(network.contains("candidates: [candidate]"))
        assertTrue(network.contains("totalCandidateCount: 1"))
        assertTrue(network.contains("truncated: false"))
        assertFalse(network.contains("visibleCandidates.slice(0, MAX_HANDOFF_CANDIDATES)"))
        assertTrue(network.contains("candidateStore.snapshot(tabId, MAX_CANDIDATES_PER_TAB)"))
        assertTrue(network.contains("const capturedCandidateCount = 0;"))
        assertTrue(handoff.contains(".filter(Boolean).slice(0, 24);"))
        assertTrue(handoff.contains("const sourceCandidates = requested.length ? requested : [primary];"))
        assertTrue(handoff.contains("for (let count = sourceCandidates.length; count >= 1; count -= 1)"))
        assertTrue(handoff.contains("candidates: sourceCandidates.slice(0, count)"))
        assertTrue(handoff.contains("const clear = new TextEncoder().encode(JSON.stringify(message));"))
        assertTrue(handoff.contains("if (clear.length > 56 * 1024) continue;"))
        assertTrue(handoff.contains("if (ct.length > 60 * 1024) continue;"))
        assertTrue(handoff.contains("if (new TextEncoder().encode(uri).length <= 64 * 1024) return uri;"))
        assertFalse(handoff.contains("uri.searchParams.set(\"candidates\""))
        assertTrue(detector.contains("HARD_NON_MEDIA_MIME_RE"))
        assertTrue(pageSniffer.contains("HARD_NON_MEDIA_MIME_RE"))
        assertTrue(screen.contains("XDM kept the highest-confidence results in this handoff."))
    }

    @Test
    fun exportedXpiUsesAppPublicPairingAndKeylessFallbackIsPublicOnly() {
        val viewModel = source("app/src/main/kotlin/com/mikeyphw/xdm/android/MainViewModel.kt")
        val generator = source("browser-extension/src/main/kotlin/com/mikeyphw/xdm/android/browserextension/BrowserExtensionPackageGenerator.kt")
        val buildConfig = source("browser-extension/src/main/kotlin/com/mikeyphw/xdm/android/browserextension/BrowserExtensionBuildConfig.kt")
        val config = source("browser-extension/src/main/extension/xdm-firefox/generated-config.template.js")
        val lifecycleTest = source("browser-extension/tests/test_secure_handoff.js")
        val releaseTest = source("browser-extension/tests/test_release_gate.js")

        assertTrue(viewModel.contains("captureKeyId = browserCaptureEnvelopeManager.keyId"))
        assertTrue(viewModel.contains("capturePublicKeySpkiBase64Url = browserCaptureEnvelopeManager.publicKeySpkiBase64Url"))
        assertTrue(viewModel.contains("captureOaepHash = browserCaptureEnvelopeManager.captureOaepHash"))
        assertTrue(viewModel.contains("Unable to prepare the app-paired Firefox capture key."))
        assertTrue(generator.contains("captureKeyId:"))
        assertTrue(generator.contains("capturePublicKeySpkiBase64Url:"))
        assertTrue(generator.contains("captureOaepHash:"))
        assertTrue(buildConfig.contains("Incomplete app-instance browser pairing"))
        assertTrue(buildConfig.contains("require(paired == 0 || paired == 3)"))
        assertTrue(config.contains("@@CAPTURE_PAIRING_CONFIG@@"))
        assertTrue(lifecycleTest.contains("MP01 app-paired RSA/AES-GCM confidentiality, origin binding and scope: passed"))
        assertTrue(lifecycleTest.contains("json.candidates[0].finalHeaders.authorization"))
        assertTrue(lifecycleTest.contains("xdm-capture-v2|forged|"))
        assertTrue(releaseTest.contains("no keyless credential leaks"))
    }

    private fun source(relative: String): String = File(root, relative).readText()

    private fun androidRoot(): File {
        var cursor = File(System.getProperty("user.dir") ?: ".").canonicalFile
        repeat(8) {
            if (File(cursor, "settings.gradle.kts").isFile && File(cursor, "app/src/main").isDirectory) return cursor
            cursor = cursor.parentFile ?: return@repeat
        }
        error("Unable to locate XDM Android root")
    }
}
