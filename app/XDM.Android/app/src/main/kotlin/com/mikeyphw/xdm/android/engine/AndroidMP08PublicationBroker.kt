package com.mikeyphw.xdm.android.engine

import android.content.ContentValues
import android.content.Context
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import android.system.Os
import android.system.OsConstants
import android.util.Base64
import com.mikeyphw.xdm.android.media.ffmpeg.EmbeddedFfmpegRuntime
import com.mikeyphw.xdm.android.scheduler.MediaRequestHandoffStore
import java.io.File
import java.io.FileOutputStream
import java.security.MessageDigest
import java.nio.file.Files
import java.util.UUID
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import org.json.JSONArray
import org.json.JSONObject

/**
 * MP08B2 typed Android readback and MediaStore visibility publisher.
 * No caller paths, URI, command arguments, URLs or credentials are accepted.
 * A successful Android reply is NOT DownloadReady: Go's MP08Host must independently
 * hash the staged AND published bytes and validate FFprobe before completion.
 *
 * MediaStore IS_PENDING creates a visibility-atomic publication boundary on API 29+.
 * A private transaction receipt is fsynced before exposing a row; interrupted
 * rows are deleted on recovery, never treated as completed by implication.
 */
internal class AndroidMP08PublicationBroker(
    context: Context,
    private val runtime: EmbeddedFfmpegRuntime,
) {
    private val app = context.applicationContext
    private val resolver = app.contentResolver
    private val root = File(app.filesDir, "xgo-mp08b-stage")
    private val verified = File(root, "verified")
    private val pending = File(root, "publication-txn")
    private val published = File(root, "publication-receipts")
    private val mutex = Mutex()
    private val healthy: Boolean = runCatching { recoverPending() }.getOrDefault(false)

    suspend fun execute(request: JSONObject): JSONObject = mutex.withLock {
        if (!healthy || Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) return@withLock refused("mp08_publication_recovery_unavailable")
        val capture = request.optString("capture_id")
        val destination = request.optString("destination_key")
        if (request.optInt("schema_version", -1) != 1 || capture.isBlank() || capture.length > 256 ||
            !safeName.matches(destination) || request.has("path") || request.has("uri") ||
            request.has("headers") || request.has("argv") || request.has("url") ||
            request.has("body_base64")) return@withLock refused("mp08_publication_request_invalid")
        val captureHash = hex(capture.toByteArray())
        val handoff = MediaRequestHandoffStore.forCapture(capture)
        val browserAuthorized = handoff != null && handoff.expiresAtEpochMs > System.currentTimeMillis()
        val liveCandidate = runCatching {
            val receiptFile = File(verified, "$captureHash-$destination.receipt.json")
            if (!receiptFile.isFile || Files.isSymbolicLink(receiptFile.toPath()) ||
                !safeFile(receiptFile, verified) || receiptFile.length() > 16_384L) false else {
                val receipt = JSONObject(receiptFile.readText(Charsets.UTF_8))
                receipt.optString("source") in setOf("hls_live", "dash_live") &&
                    receipt.optString("status") == "verified_app_private" &&
                    receipt.optString("capture_hash") == captureHash &&
                    receipt.optString("destination_key") == destination
            }
        }.getOrDefault(false)
        // A browser token is only for NETWORK access. This path reads
        // app-private, independently verified staged media, never a URL.
        if (!browserAuthorized && !liveCandidate) return@withLock refused("mp08_capture_authorization_missing")
        try {
            when (request.optString("action")) {
                "probe_staged" -> probeStaged(request, captureHash, destination)
                "read_staged" -> readStaged(request, captureHash, destination)
                "publish_verified" -> publishVerified(request, captureHash, destination)
                "read_published" -> readPublished(request, captureHash, destination)
                else -> refused("mp08_publication_action_invalid")
            }
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (_: Throwable) {
            refused("mp08_publication_verification_failed")
        }
    }

    private data class Candidate(val file: File, val digest: String, val bytes: Long)

    private fun candidate(request: JSONObject, captureHash: String, destination: String, fullHash: Boolean): Candidate {
        require(safeDirectory(root) && safeDirectory(verified))
        val file = File(verified, "$captureHash-$destination.mp4")
        val receiptFile = File(verified, "$captureHash-$destination.receipt.json")
        require(safeFile(file, verified) && safeFile(receiptFile, verified))
        require(receiptFile.length() in 1..65536)
        val receipt = JSONObject(receiptFile.readText(Charsets.UTF_8))
        val digest = receipt.getString("hash")
        val bytes = receipt.getLong("bytes")
        require(receipt.optString("status") == "verified_app_private" &&
            receipt.optString("capture_hash") == captureHash && receipt.optString("destination_key") == destination &&
            !receipt.optBoolean("download_ready", true) && !receipt.optBoolean("media_store_published", true) &&
            safeDigest.matches(digest) && bytes in 1024..MaxPublishBytes && file.length() == bytes &&
            request.optString("sha256") == digest && request.optLong("bytes") == bytes)
        if (fullHash) require(hashFile(file) == digest)
        return Candidate(file, digest, bytes)
    }

    private suspend fun probeStaged(req: JSONObject, hash: String, name: String): JSONObject {
        val candidate = candidate(req, hash, name, true)
        val probe = runtime.probe(candidate.file.absolutePath).getOrNull() ?: return refused("mp08_ffprobe_failed")
        val duration = probe.durationSeconds?.takeIf { it.isFinite() && it > 0 }?.let { (it * 1000).toLong() }
            ?: return refused("mp08_ffprobe_duration_invalid")
        val formats = probe.formatName.orEmpty().split(',')
        if ("mp4" !in formats || probe.videoStreams.isEmpty() || probe.streams.size !in 1..16) return refused("mp08_ffprobe_stream_invalid")
        val streams = JSONArray()
        for (stream in probe.streams) {
            val kind = stream.codecType ?: return refused("mp08_ffprobe_stream_invalid")
            if (kind !in setOf("video", "audio", "subtitle")) return refused("mp08_ffprobe_stream_invalid")
            streams.put(JSONObject().put("kind", kind).put("codec", stream.codecName.orEmpty()))
        }
        return JSONObject().put("ok", true).put("download_ready", false).put("probe", JSONObject()
            .put("container", "mp4").put("duration_ms", duration).put("size", candidate.bytes).put("streams", streams))
    }

    private fun readStaged(req: JSONObject, hash: String, name: String): JSONObject {
        val candidate = candidate(req, hash, name, false)
        return readChunk(req, candidate.file, candidate.bytes)
    }

    private fun publishVerified(req: JSONObject, captureHash: String, name: String): JSONObject {
        val candidate = candidate(req, captureHash, name, true)
        require(safeDirectory(root) && safeDirectory(pending) && safeDirectory(published))
        val receiptFile = File(published, "$captureHash-$name.json")
        if (receiptFile.exists()) {
            val record = committed(req, captureHash, name) ?: return refused("mp08_publication_receipt_conflict")
            if (!verifyMediaStore(record.getString("uri"), candidate.bytes, candidate.digest)) return refused("mp08_published_readback_failed")
            return successPublished(record)
        }
        val publicationID = UUID.randomUUID().toString().replace("-", "")
        val txFile = File(pending, "$captureHash-$name.json")
        if (txFile.exists()) return refused("mp08_unreconciled_publication")
        var uri: android.net.Uri? = null
        var committed = false
        writeReceipt(txFile, JSONObject().put("capture_hash", captureHash).put("destination_key", name)
            .put("publication_id", publicationID).put("status", "prepared"))
        try {
            val values = ContentValues().apply {
                put(MediaStore.MediaColumns.DISPLAY_NAME, "$name.mp4")
                put(MediaStore.MediaColumns.MIME_TYPE, "video/mp4")
                put(MediaStore.MediaColumns.RELATIVE_PATH, "${Environment.DIRECTORY_DOWNLOADS}/XDM/")
                put(MediaStore.MediaColumns.IS_PENDING, 1)
            }
            uri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
                ?: return refused("mp08_media_store_insert_failed")
            val uriText = uri.toString()
            require(uriText.startsWith("content://") && !uriText.contains('?') && !uriText.contains('#'))
            writeReceipt(txFile, JSONObject().put("capture_hash", captureHash).put("destination_key", name)
                .put("publication_id", publicationID).put("uri", uriText).put("status", "pending"))
            resolver.openFileDescriptor(uri, "w")?.use { pfd ->
                FileOutputStream(pfd.fileDescriptor).use { output ->
                    candidate.file.inputStream().use { input ->
                        val buffer = ByteArray(64 * 1024)
                        while (true) {
                            val n = input.read(buffer)
                            if (n < 0) break
                            if (n > 0) output.write(buffer, 0, n)
                        }
                    }
                    output.fd.sync()
                }
            } ?: return refused("mp08_media_store_write_failed")
            if (!verifyMediaStore(uriText, candidate.bytes, candidate.digest)) return refused("mp08_pending_readback_failed")
            val visible = ContentValues().apply { put(MediaStore.MediaColumns.IS_PENDING, 0) }
            if (resolver.update(uri, visible, null, null) != 1) return refused("mp08_media_store_commit_failed")
            writeReceipt(txFile, JSONObject().put("capture_hash", captureHash).put("destination_key", name)
                .put("publication_id", publicationID).put("uri", uriText).put("status", "visible_uncommitted"))
            if (!verifyMediaStore(uriText, candidate.bytes, candidate.digest)) return refused("mp08_published_readback_failed")
            val receipt = JSONObject().put("capture_hash", captureHash).put("destination_key", name)
                .put("publication_id", publicationID).put("uri", uriText).put("sha256", candidate.digest)
                .put("bytes", candidate.bytes).put("status", "published_verified").put("visibility_committed", true)
            writeReceipt(receiptFile, receipt)
            committed = true
            if (!txFile.delete()) return refused("mp08_transaction_cleanup_failed")
            syncDirectory(pending)
            return successPublished(receipt)
        } finally {
            if (!committed && uri != null) {
                // Do not expose a partial/broken output. A delete failure leaves
                // an explicit transaction record for startup reconciliation.
                if (resolver.delete(uri, null, null) == 1) {
                    txFile.delete()
                    syncDirectory(pending)
                }
            }
        }
    }

    private fun successPublished(receipt: JSONObject): JSONObject = JSONObject().put("ok", true)
        .put("publication_id", receipt.getString("publication_id")).put("uri", receipt.getString("uri"))
        .put("sha256", receipt.getString("sha256")).put("size", receipt.getLong("bytes"))
        .put("atomic", true) // IS_PENDING visibility commit, not a filesystem rename
        .put("download_ready", false)

    private fun readPublished(req: JSONObject, captureHash: String, name: String): JSONObject {
        val record = committed(req, captureHash, name) ?: return refused("mp08_published_receipt_missing")
        val bytes = record.getLong("bytes")
        val uri = android.net.Uri.parse(record.getString("uri"))
        val start = req.optLong("offset", -1L)
        val count = req.optInt("max_bytes", -1)
        if (start !in 0..bytes || count !in 1..MaxChunkBytes || start + count > bytes + MaxChunkBytes) return refused("mp08_read_range_invalid")
        if (start == bytes) return JSONObject().put("ok", true).put("offset", start).put("body_base64", "").put("eof", true).put("download_ready", false)
        // Seek on the provider-backed fd. Reopening from byte zero for each
        // chunk would be quadratic on multi-hundred-MiB videos.
        val data = resolver.openFileDescriptor(uri, "r")?.use { pfd ->
            java.io.FileInputStream(pfd.fileDescriptor).use { input ->
                input.channel.position(start) // nonseekable providers fail closed
                val target = minOf(count.toLong(), bytes - start).toInt()
                val chunk = ByteArray(target)
                var off = 0
                while (off < target) {
                    val n = input.read(chunk, off, target - off)
                    if (n <= 0) error("short published read")
                    off += n
                }
                chunk
            }
        } ?: error("published read refused")
        return JSONObject().put("ok", true).put("offset", start)
            .put("body_base64", Base64.encodeToString(data, Base64.NO_WRAP))
            .put("eof", start + data.size == bytes).put("download_ready", false)
    }

    private fun committed(req: JSONObject, captureHash: String, name: String): JSONObject? {
        val file = File(published, "$captureHash-$name.json")
        if (!safeFile(file, published) || file.length() !in 1..65536) return null
        val record = runCatching { JSONObject(file.readText()) }.getOrNull() ?: return null
        if (record.optString("status") != "published_verified" || !record.optBoolean("visibility_committed") ||
            record.optString("capture_hash") != captureHash || record.optString("destination_key") != name ||
            !safeName.matches(record.optString("publication_id")) ||
            (req.optString("action") != "publish_verified" && req.optString("publication_id") != record.optString("publication_id")) ||
            req.optString("sha256") != record.optString("sha256") ||
            req.optLong("bytes") != record.optLong("bytes") || !safeDigest.matches(record.optString("sha256")) ||
            record.optLong("bytes") !in 1024..MaxPublishBytes ||
            !record.optString("uri").startsWith("content://") ||
            android.net.Uri.parse(record.optString("uri")).authority != MediaStore.AUTHORITY ||
            record.optString("uri").contains('?') || record.optString("uri").contains('#')) return null
        return record
    }

    private fun readChunk(req: JSONObject, file: File, bytes: Long): JSONObject {
        val offset = req.optLong("offset", -1L)
        val count = req.optInt("max_bytes", -1)
        if (offset !in 0..bytes || count !in 1..MaxChunkBytes) return refused("mp08_read_range_invalid")
        if (offset == bytes) return JSONObject().put("ok", true).put("offset", offset).put("body_base64", "")
            .put("eof", true).put("download_ready", false)
        val size = minOf(count.toLong(), bytes - offset).toInt()
        val buffer = ByteArray(size)
        java.io.RandomAccessFile(file, "r").use { input ->
            input.seek(offset)
            input.readFully(buffer)
        }
        return JSONObject().put("ok", true).put("offset", offset)
            .put("body_base64", Base64.encodeToString(buffer, Base64.NO_WRAP))
            .put("eof", offset + size == bytes).put("download_ready", false)
    }

    private fun verifyMediaStore(uriText: String, expected: Long, hash: String): Boolean = runCatching {
        val uri = android.net.Uri.parse(uriText)
        require(uri.scheme == "content" && uri.authority == MediaStore.AUTHORITY)
        var count = 0L
        val digest = MessageDigest.getInstance("SHA-256")
        resolver.openInputStream(uri)?.use { input ->
            val buffer = ByteArray(64 * 1024)
            while (true) {
                val n = input.read(buffer)
                if (n < 0) break
                if (n > 0) { count += n; require(count <= expected); digest.update(buffer, 0, n) }
            }
        } ?: return@runCatching false
        count == expected && "sha256:" + digest.digest().joinToString("") { "%02x".format(it) } == hash
    }.getOrDefault(false)

    private fun recoverPending(): Boolean = runCatching {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) return@runCatching false
        for (dir in listOf(root, pending, published)) {
            if (!dir.exists() && !dir.mkdirs()) return@runCatching false
            if (!safeDirectory(dir)) return@runCatching false
        }
        val entries = pending.listFiles() ?: return@runCatching false
        for (entry in entries) {
            if (!safeFile(entry, pending) || !entry.name.matches(Regex("[0-9a-f]{64}-[A-Za-z0-9_-]{1,96}\\.json")) || entry.length() !in 1..65536)
                return@runCatching false
            val record = JSONObject(entry.readText())
            val publication = File(published, entry.name)
            val completed = safeFile(publication, published) && publication.length() in 1..65536
            val raw = record.optString("uri")
            if (!completed && raw.isNotBlank()) {
                val uri = android.net.Uri.parse(raw)
                if (uri.scheme != "content" || uri.authority != MediaStore.AUTHORITY ||
                    resolver.delete(uri, null, null) != 1) return@runCatching false
            }
            if (!entry.delete()) return@runCatching false
        }
        syncDirectory(pending)
        true
    }.getOrDefault(false)

    private fun hashFile(file: File): String {
        val md = MessageDigest.getInstance("SHA-256")
        file.inputStream().use { input ->
            val buffer = ByteArray(64 * 1024)
            while (true) { val n = input.read(buffer); if (n < 0) break; if (n > 0) md.update(buffer, 0, n) }
        }
        return "sha256:" + md.digest().joinToString("") { "%02x".format(it) }
    }
    private fun hex(bytes: ByteArray): String = MessageDigest.getInstance("SHA-256")
        .digest(bytes).joinToString("") { "%02x".format(it) }
    private fun safeDirectory(dir: File): Boolean = runCatching {
        val base = app.filesDir.canonicalPath + File.separator
        dir.isDirectory && !Files.isSymbolicLink(dir.toPath()) && dir.canonicalPath.startsWith(base)
    }.getOrDefault(false)
    private fun safeFile(file: File, parent: File): Boolean = safeDirectory(parent) && file.isFile &&
        !Files.isSymbolicLink(file.toPath()) && file.canonicalFile.parentFile == parent.canonicalFile
    private fun writeReceipt(target: File, record: JSONObject) {
        require(safeDirectory(target.parentFile!!))
        val tmp = File.createTempFile(".mp08-", ".txn", target.parentFile)
        try {
            FileOutputStream(tmp).use { it.write(record.toString().toByteArray(Charsets.UTF_8)); it.fd.sync() }
            Os.rename(tmp.absolutePath, target.absolutePath)
            syncDirectory(target.parentFile!!)
        } finally { tmp.delete() }
    }
    private fun syncDirectory(dir: File) {
        require(safeDirectory(dir))
        val fd = Os.open(dir.absolutePath, OsConstants.O_RDONLY, 0)
        try { Os.fsync(fd) } finally { Os.close(fd) }
    }
    private fun refused(code: String): JSONObject = JSONObject().put("ok", false)
        .put("error_code", code).put("download_ready", false)

    private companion object {
        const val MaxPublishBytes = 512L * 1024 * 1024
        const val MaxChunkBytes = 64 * 1024
        val safeName = Regex("^[A-Za-z0-9_-]{1,96}$")
        val safeDigest = Regex("sha256:[0-9a-f]{64}")
    }
}
