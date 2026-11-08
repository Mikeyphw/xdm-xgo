package com.mikeyphw.xdm.android

import android.os.Build
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.mikeyphw.xdm.android.engine.BridgeProtocolException
import com.mikeyphw.xdm.android.engine.JniNativeXdmCore
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test
import org.junit.runner.RunWith

/** Verifies the real x86_64 APK loads Android/amd64 Go JNI, not ARM64 translation. */
@RunWith(AndroidJUnit4::class)
class XgoX86JniSmokeTest {
    @Test
    fun installedX86CoreLoadsAndInvokesNativeCreate() {
        assertEquals("x86_64", Build.SUPPORTED_ABIS.first())
        // Native create must cross JNI. An empty configuration should be rejected
        // safely by the Go engine rather than linking the wrong architecture.
        val outcome = runCatching {
            val handle = JniNativeXdmCore.create(byteArrayOf())
            JniNativeXdmCore.shutdown(handle)
        }
        val failure = outcome.exceptionOrNull()
        assertFalse("JNI must not be missing", failure is UnsatisfiedLinkError)
        assertFalse("JNI bridge class must load", failure is ExceptionInInitializerError)
        assertFalse("Go JNI must not crash on empty input", failure is LinkageError)
        if (failure != null && failure !is BridgeProtocolException) {
            throw AssertionError("Unexpected engine JNI failure", failure)
        }
    }
}
