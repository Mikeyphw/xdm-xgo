package com.mikeyphw.xdm.android

import android.os.Build
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.mikeyphw.xdm.android.media.ffmpeg.EmbeddedFfmpegRuntime
import java.io.File
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

/** Exact three real process executions in the optional x86_64 media build.
 * Not Android ARM64, licensed 1DM+, or production-release qualification.
 */
@RunWith(AndroidJUnit4::class)
class XgoX86NativeMediaInstrumentedTest {
    private fun appContext() = InstrumentationRegistry.getInstrumentation().targetContext

    private fun requireX86() {
        assertEquals("real API36 required", 36, Build.VERSION.SDK_INT)
        assertEquals("native x86_64 required; ARM64 translation is not acceptable", "x86_64", Build.SUPPORTED_ABIS.first())
    }

    private fun execute(file: File, option: String, marker: String) {
        requireX86()
        assertTrue("missing packaged native executable: ${file.name}", file.isFile)
        assertTrue("native executable permission missing: ${file.name}", file.canExecute())
        val process = ProcessBuilder(file.absolutePath, option)
            .redirectErrorStream(true).start()
        assertTrue("native runtime timed out: ${file.name}", process.waitFor(20, TimeUnit.SECONDS))
        val text = process.inputStream.bufferedReader().use { it.readText().take(65536) }
        assertEquals("native runtime exited nonzero: ${file.name}", 0, process.exitValue())
        assertTrue("wrong native runtime version: ${file.name}", text.contains(marker, ignoreCase = true))
    }

    @Test
    fun x86_01PinnedFfmpegExecutes() = runBlocking {
        val runtime = EmbeddedFfmpegRuntime(appContext())
        val capability = runtime.capabilities(force = true)
        assertTrue("FFmpeg/FFprobe attestation failed: ${capability.summary}", capability.ready)
        execute(runtime.ffmpegBinary, "-version", "ffmpeg version 9.0.1")
    }

    @Test
    fun x86_02PinnedFfprobeExecutes() {
        val runtime = EmbeddedFfmpegRuntime(appContext())
        execute(runtime.ffprobeBinary, "-version", "ffprobe version 9.0.1")
    }

    @Test
    fun x86_03SourceBuiltAria2Executes() {
        val binary = File(appContext().applicationInfo.nativeLibraryDir, "libaria2c.so")
        execute(binary, "--version", "aria2 version 1.37.0")
    }
}
