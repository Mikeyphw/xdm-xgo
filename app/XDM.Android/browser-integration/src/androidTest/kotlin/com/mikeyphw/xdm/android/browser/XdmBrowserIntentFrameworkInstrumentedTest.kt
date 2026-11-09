package com.mikeyphw.xdm.android.browser

import android.content.Intent
import android.net.Uri
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.mikeyphw.xdm.android.model.AutomationCommandAction
import java.net.URLEncoder
import java.nio.charset.StandardCharsets
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

/** XP02B: real Android framework Uri/Intent transport through the production parser.
 * This isolated Android library has no app, Go engine, JNI, aria2 or FFmpeg runtime.
 */
@RunWith(AndroidJUnit4::class)
class XdmBrowserIntentFrameworkInstrumentedTest {
    private fun encoded(text: String): String = URLEncoder.encode(text, StandardCharsets.UTF_8.name())
    private fun delivered(uri: String): String = Intent(Intent.ACTION_VIEW, Uri.parse(uri)).dataString!!
    private fun addLink(scheme: String = XdmBrowserDeepLinkContract.ReleaseScheme): String =
        "$scheme://add?v=1&url=${encoded("https://example.test/release.apk")}" 

    @Test fun debugSchemeAddIntentRoundTrip() {
        val uri = delivered(addLink(XdmBrowserDeepLinkContract.DebugScheme))
        val result = XdmBrowserDeepLinkParser.parseDetailed(uri, XdmBrowserDeepLinkContract.DebugScheme)
        assertTrue(result is XdmBrowserDeepLinkParseResult.Accepted)
        val payload = (result as XdmBrowserDeepLinkParseResult.Accepted).payload
        assertEquals(AutomationCommandAction.PromptAddDownload, payload.action)
        assertEquals("https://example.test/release.apk", payload.url)
    }

    @Test fun releaseSchemeCannotEnterDebugReceiver() {
        val result = XdmBrowserDeepLinkParser.parseDetailed(
            delivered(addLink()), XdmBrowserDeepLinkContract.DebugScheme,
        )
        assertEquals(XdmBrowserDeepLinkRejection.VariantMismatch, (result as XdmBrowserDeepLinkParseResult.Rejected).reason)
    }

    @Test fun releaseSchemeResolvesOnlyReleaseParser() {
        val result = XdmBrowserDeepLinkParser.parseDetailed(delivered(addLink()), XdmBrowserDeepLinkContract.ReleaseScheme)
        assertTrue(result is XdmBrowserDeepLinkParseResult.Accepted)
        assertNull(XdmBrowserDeepLinkParser.parse(delivered(addLink(XdmBrowserDeepLinkContract.DebugScheme)), XdmBrowserDeepLinkContract.ReleaseScheme))
    }

    @Test fun v2EncryptedCaptureHasNoPlaintextUrl() {
        val uri = delivered("xdmdownload://capture?v=2&sid=session-7&kid=key-7&ek=QUJDREVGR0g&iv=QUJDREVGR0hJSktM&ct=QUJDREVGR0hJSktMTU5PUA")
        val result = XdmBrowserDeepLinkParser.parseDetailed(uri, XdmBrowserDeepLinkContract.ReleaseScheme)
        val payload = (result as XdmBrowserDeepLinkParseResult.Accepted).payload
        assertTrue(payload.hasEncryptedCaptureEnvelope)
        assertNull(payload.url)
        assertNull(payload.rawHeaders)
    }

    @Test fun v3PlaintextCaptureIsRejectedEvenWithCandidateContext() {
        // MP01: browser navigation must never carry plaintext capture candidates,
        // including signed URLs and executable Authorization/Cookie headers.
        val candidates = "[{\"url\":\"https://example.test/clip.mp4\"}]"
        for (scheme in listOf(XdmBrowserDeepLinkContract.ReleaseScheme, XdmBrowserDeepLinkContract.DebugScheme)) {
            val uri = delivered("$scheme://capture?v=3&url=${encoded("https://example.test/clip.mp4")}&candidates=${encoded(candidates)}&sid=browser-session-8")
            val result = XdmBrowserDeepLinkParser.parseDetailed(uri, scheme)
            assertEquals(XdmBrowserDeepLinkRejection.UnsafeEnvelope, (result as XdmBrowserDeepLinkParseResult.Rejected).reason)
            assertNull(XdmBrowserDeepLinkParser.parse(uri, scheme))

            val credentialed = delivered("$scheme://capture?v=3&url=${encoded("https://example.test/clip.mp4?token=secret")}&finalHeaders=${encoded("Authorization: Bearer private\nCookie: sid=secret")}")
            val privateResult = XdmBrowserDeepLinkParser.parseDetailed(credentialed, scheme)
            assertEquals(XdmBrowserDeepLinkRejection.UnsafeEnvelope, (privateResult as XdmBrowserDeepLinkParseResult.Rejected).reason)
            assertNull(XdmBrowserDeepLinkParser.parse(credentialed, scheme))
        }
    }

    @Test fun duplicateUrlParameterFailsClosed() {
        val uri = delivered(addLink() + "&url=${encoded("https://example.test/other.apk")}")
        assertEquals(
            XdmBrowserDeepLinkRejection.MissingMediaUrl,
            (XdmBrowserDeepLinkParser.parseDetailed(uri, XdmBrowserDeepLinkContract.ReleaseScheme)
                as XdmBrowserDeepLinkParseResult.Rejected).reason,
        )
    }

    @Test fun unsafeNestedUrlFailsClosed() {
        for (unsafe in listOf("javascript:alert(1)", "content://provider/secret", "https://user:pass@example.test/file.apk")) {
            val uri = delivered("xdmdownload://add?v=1&url=${encoded(unsafe)}")
            assertEquals(
                XdmBrowserDeepLinkRejection.UnsafeMediaUrl,
                (XdmBrowserDeepLinkParser.parseDetailed(uri, XdmBrowserDeepLinkContract.ReleaseScheme)
                    as XdmBrowserDeepLinkParseResult.Rejected).reason,
            )
        }
    }

    @Test fun unknownHostFailsClosed() {
        val uri = delivered("xdmdownload://unknown?v=1&url=${encoded("https://example.test/a")}")
        assertEquals(
            XdmBrowserDeepLinkRejection.UnsupportedAction,
            (XdmBrowserDeepLinkParser.parseDetailed(uri, XdmBrowserDeepLinkContract.ReleaseScheme)
                as XdmBrowserDeepLinkParseResult.Rejected).reason,
        )
    }

    @Test fun oversizedEnvelopeRejected() {
        val uri = delivered("xdmdownload://add?v=1&url=" + "x".repeat(XdmBrowserDeepLinkContract.MaxDeepLinkBytes))
        assertEquals(
            XdmBrowserDeepLinkRejection.PayloadTooLarge,
            (XdmBrowserDeepLinkParser.parseDetailed(uri, XdmBrowserDeepLinkContract.ReleaseScheme)
                as XdmBrowserDeepLinkParseResult.Rejected).reason,
        )
    }

    @Test fun uriAuthorityCredentialsAndFragmentsAreRejected() {
        for (raw in listOf(
            "xdmdownload://user:pass@add?v=1&url=${encoded("https://example.test/a")}",
            "xdmdownload://add:443?v=1&url=${encoded("https://example.test/a")}",
            addLink() + "#fragment",
        )) {
            val result = XdmBrowserDeepLinkParser.parseDetailed(delivered(raw), XdmBrowserDeepLinkContract.ReleaseScheme)
            assertEquals(XdmBrowserDeepLinkRejection.UnsafeEnvelope, (result as XdmBrowserDeepLinkParseResult.Rejected).reason)
        }
    }
}
