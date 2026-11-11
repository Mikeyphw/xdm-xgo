package com.mikeyphw.xdm.android

import android.content.ContentValues
import android.content.Context
import android.net.Uri
import android.os.Build
import android.provider.MediaStore
import android.util.Base64
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.mikeyphw.xdm.android.engine.AndroidMP08PublicationBroker
import com.mikeyphw.xdm.android.media.ffmpeg.EmbeddedFfmpegRuntime
import com.mikeyphw.xdm.android.media.ffmpeg.FfmpegPostProcessor
import com.mikeyphw.xdm.android.scheduler.MediaRequestHandoffStore
import java.io.File
import java.security.MessageDigest
import java.util.UUID
import kotlinx.coroutines.runBlocking
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

/**
 * MP08B3: real, app-owned MediaStore publication on API 36, with an additional
 * strict FFmpeg/FFprobe-backed fixture. These tests are NEVER a release claim:
 * Go's independent MP08A published-byte readback is not exercised here.
 */
@RunWith(AndroidJUnit4::class)
class MP08B3MediaStoreAcceptanceInstrumentedTest {
    private lateinit var context: Context
    private lateinit var instrumentationContext: Context
    private lateinit var runtime: EmbeddedFfmpegRuntime
    private lateinit var publisher: AndroidMP08PublicationBroker
    private lateinit var capture: String
    private lateinit var destination: String
    private lateinit var captureHash: String
    private val ownedUris = mutableListOf<Uri>()
    private val fixtureFiles = mutableListOf<File>()

    @Before
    fun setUp() {
        context = InstrumentationRegistry.getInstrumentation().targetContext
        instrumentationContext = InstrumentationRegistry.getInstrumentation().context
        assertEquals("API 36 required", 36, Build.VERSION.SDK_INT)
        capture = "mp08b3-${UUID.randomUUID().toString().replace("-", "")}" // isolated pair
        destination = "mp08b3_${UUID.randomUUID().toString().replace("-", "")}" // safe name
        captureHash = digest(capture.toByteArray())
        assertTrue(MediaRequestHandoffStore.rememberCapture(
            captureId = capture,
            headers = emptyMap(),
            redactedSummary = "MP08B3 local no-credential instrumentation fixture",
            isExpiringUrl = false,
            exactUrl = "https://fixture.example.invalid/mp08b3/local.m3u8",
            expiresAtEpochMs = System.currentTimeMillis() + 10L * 60L * 1000L,
        ))
        runtime = EmbeddedFfmpegRuntime(context)
        publisher = AndroidMP08PublicationBroker(context, runtime)
    }

    @After
    fun cleanUp() {
        ownedUris.forEach { runCatching { context.contentResolver.delete(it, null, null) } }
        MediaRequestHandoffStore.forgetCapture(capture)
        val root = File(context.filesDir, "xgo-mp08b-stage")
        val names = listOf(
            "verified/$captureHash-$destination.mp4",
            "verified/$captureHash-$destination.receipt.json",
            "publication-txn/$captureHash-$destination.json",
            "publication-receipts/$captureHash-$destination.json",
        )
        names.forEach { File(root, it).delete() }
        fixtureFiles.forEach { it.deleteRecursively() }
    }

    private fun digest(bytes: ByteArray): String = MessageDigest.getInstance("SHA-256")
        .digest(bytes).joinToString("") { "%02x".format(it) }

    private fun fixtureBytes(): ByteArray = instrumentationContext.assets
        .open("ffmpeg04/video-only.mp4").use { it.readBytes() }

    private fun publicationFixtureBytes(): ByteArray {
        val video = fixtureBytes()
        if (video.size >= 1024) return video
        require(video.size in 8..1016 &&
            video.copyOfRange(4, 8).contentEquals("ftyp".toByteArray(Charsets.US_ASCII)))
        // ISO BMFF free box: preserves actual media samples while satisfying
        // the production broker's unchanged 1024-byte minimum.
        val freeLength = 1024 - video.size
        val free = ByteArray(freeLength)
        free[0] = (freeLength ushr 24).toByte()
        free[1] = (freeLength ushr 16).toByte()
        free[2] = (freeLength ushr 8).toByte()
        free[3] = freeLength.toByte()
        "free".toByteArray(Charsets.US_ASCII).copyInto(free, 4)
        return video + free
    }

    private fun seedVerifiedCandidate(content: ByteArray = publicationFixtureBytes()): JSONObject {
        require(content.size >= 1024)
        val verified = File(context.filesDir, "xgo-mp08b-stage/verified").apply { mkdirs() }
        val output = File(verified, "$captureHash-$destination.mp4")
        val hash = "sha256:${digest(content)}"
        output.outputStream().use { it.write(content); it.fd.sync() }
        val receipt = JSONObject().put("schema_version", 1)
            .put("capture_hash", captureHash).put("destination_key", destination)
            .put("hash", hash).put("bytes", content.size)
            .put("status", "verified_app_private")
            .put("download_ready", false).put("media_store_published", false)
        File(verified, "$captureHash-$destination.receipt.json")
            .outputStream().use { it.write(receipt.toString().toByteArray()); it.fd.sync() }
        return request("publish_verified", hash, content.size.toLong())
    }

    private fun request(action: String, hash: String, bytes: Long): JSONObject = JSONObject()
        .put("schema_version", 1).put("action", action).put("capture_id", capture)
        .put("destination_key", destination).put("sha256", hash).put("bytes", bytes)

    private fun track(result: JSONObject): Uri {
        assertTrue(result.toString(), result.optBoolean("ok", false))
        assertFalse("Android may never assert DownloadReady", result.optBoolean("download_ready", true))
        assertTrue(result.optBoolean("atomic", false))
        val uri = Uri.parse(result.getString("uri"))
        assertEquals("content", uri.scheme)
        assertEquals(MediaStore.AUTHORITY, uri.authority)
        ownedUris += uri
        return uri
    }

    @Test
    fun b3_01RealMediaStorePublicationReadbackAndIdempotency() = runBlocking {
        val bytes = publicationFixtureBytes()
        val request = seedVerifiedCandidate(bytes)
        val first = publisher.execute(request)
        val uri = track(first)
        assertEquals("sha256:${digest(bytes)}", first.getString("sha256"))
        val visible = context.contentResolver.query(uri, arrayOf(MediaStore.MediaColumns.IS_PENDING), null, null, null)
        visible.use {
            assertNotNull(it)
            assertTrue(it!!.moveToFirst())
            assertEquals(0, it.getInt(0))
        }
        val actual = context.contentResolver.openInputStream(uri)!!.use { it.readBytes() }
        assertArrayEquals(bytes, actual)
        val again = publisher.execute(request)
        assertEquals(first.getString("publication_id"), again.getString("publication_id"))
        assertEquals(first.getString("uri"), again.getString("uri"))
        assertFalse(again.optBoolean("download_ready", true))
        val fresh = AndroidMP08PublicationBroker(context, runtime)
        val chunk = fresh.execute(request("read_published", first.getString("sha256"), bytes.size.toLong())
            .put("publication_id", first.getString("publication_id"))
            .put("offset", 0).put("max_bytes", 64 * 1024))
        assertTrue(chunk.toString(), chunk.optBoolean("ok", false))
        val decoded = Base64.decode(chunk.getString("body_base64"), Base64.NO_WRAP)
        assertArrayEquals(bytes.copyOfRange(0, minOf(bytes.size, 64 * 1024)), decoded)
        assertFalse(chunk.optBoolean("download_ready", true))
    }

    @Test
    fun b3_02NoAuthorizationAndCorruptedCandidateFailClosed() = runBlocking {
        val bytes = publicationFixtureBytes()
        val request = seedVerifiedCandidate(bytes)
        val output = File(context.filesDir, "xgo-mp08b-stage/verified/$captureHash-$destination.mp4")
        output.appendBytes(byteArrayOf(0x7F))
        val tampered = publisher.execute(request)
        assertFalse(tampered.toString(), tampered.optBoolean("ok", true))
        assertFalse(tampered.optBoolean("download_ready", true))
        output.writeBytes(bytes)
        MediaRequestHandoffStore.forgetCapture(capture)
        val unauth = publisher.execute(request)
        assertFalse(unauth.toString(), unauth.optBoolean("ok", true))
        assertFalse(unauth.optBoolean("download_ready", true))
    }

    @Test
    fun b3_03InterruptedPendingMediaStoreRowIsReconciled() = runBlocking {
        val values = ContentValues().apply {
            put(MediaStore.MediaColumns.DISPLAY_NAME, "$destination.mp4")
            put(MediaStore.MediaColumns.MIME_TYPE, "video/mp4")
            put(MediaStore.MediaColumns.IS_PENDING, 1)
        }
        val uri = context.contentResolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
        assertNotNull("requires real MediaStore", uri)
        ownedUris += uri!!
        val txn = File(context.filesDir, "xgo-mp08b-stage/publication-txn/$captureHash-$destination.json")
        txn.parentFile!!.mkdirs()
        val record = JSONObject().put("capture_hash", captureHash)
            .put("destination_key", destination).put("publication_id", UUID.randomUUID().toString().replace("-", ""))
            .put("uri", uri.toString()).put("status", "pending")
        txn.writeText(record.toString())
        val fresh = AndroidMP08PublicationBroker(context, runtime)
        assertFalse("orphan transaction must be removed", txn.exists())
        // The initialized broker must remain usable, but cannot claim success without a candidate.
        val negative = fresh.execute(request("read_published", "sha256:${"0".repeat(64)}", 1024)
            .put("publication_id", "missing")
            .put("offset", 0).put("max_bytes", 16))
        assertFalse(negative.optBoolean("ok", true))
        assertFalse(negative.optBoolean("download_ready", true))
        val row = context.contentResolver.query(uri, arrayOf(MediaStore.MediaColumns._ID), null, null, null)
        row?.use { assertFalse("recovered pending item must not survive", it.moveToFirst()) }
        Unit
    }

    @Test
    fun b3_04RealEmbeddedFfmpegProbeMuxAndMediaStoreRoundTrip() = runBlocking {
        // No Assume/Skip: a missing attested x86 test runtime is NOT acceptance.
        val capability = runtime.capabilities(force = true)
        assertTrue("test ABI has no attested FFmpeg/FFprobe runtime: ${capability.summary}", capability.ready)
        val work = File(context.cacheDir, "mp08b3-$destination").apply { mkdirs() }
        fixtureFiles += work
        val video = File(work, "video.mp4")
        val audio = File(work, "audio.m4a")
        instrumentationContext.assets.open("ffmpeg04/video-only.mp4").use { src -> video.outputStream().use { src.copyTo(it) } }
        instrumentationContext.assets.open("ffmpeg04/audio-only.m4a").use { src -> audio.outputStream().use { src.copyTo(it) } }
        val mux = File(work, "muxed.mp4")
        val result = FfmpegPostProcessor(runtime, File(work, "scratch"))
            .muxTracks(video = video, audio = audio, output = mux, expectedDurationMs = 1_000L)
        assertTrue("real embedded FFmpeg mux rejected: ${result.summary}", result.success)
        assertTrue(mux.isFile && mux.length() >= 1024)
        val probe = runtime.probe(mux.absolutePath).getOrThrow()
        assertEquals(1, probe.videoStreams.size)
        assertEquals(1, probe.audioStreams.size)
        assertTrue(probe.durationSeconds != null && probe.durationSeconds!! >= 0.9)
        val bytes = mux.readBytes()
        val published = publisher.execute(seedVerifiedCandidate(bytes))
        val uri = track(published)
        assertArrayEquals(bytes, context.contentResolver.openInputStream(uri)!!.use { it.readBytes() })
        assertEquals("sha256:${digest(bytes)}", published.getString("sha256"))
    }
}
