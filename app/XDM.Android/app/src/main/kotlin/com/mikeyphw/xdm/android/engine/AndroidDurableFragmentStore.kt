package com.mikeyphw.xdm.android.engine

import android.content.Context
import android.system.Os
import android.system.OsConstants
import android.util.Base64
import com.mikeyphw.xdm.android.scheduler.MediaRequestHandoffStore
import java.io.File
import java.io.FileOutputStream
import java.security.MessageDigest
import org.json.JSONArray
import org.json.JSONObject

/**
 * MP05 — app-private, read-back-verified segment persistence for Go's typed
 * JNI platform requests. Comparison-only until MP06/08 real execution and
 * final publication gates qualify. Never receives URLs, cookies or keys.
 * The single Go engine serializes its broker operations; this synchronized
 * writer supplies a second generation fence across concurrent JNI requests.
 */
internal class AndroidDurableFragmentStore(context: Context) {
    private val root = File(context.applicationContext.filesDir, "xgo-fragments-mp05").apply { mkdirs() }
    private val parts = File(root, "parts").apply { mkdirs() }
    private val journal = File(root, "journal-v1.json")
    // Crash recovery must run before accepting any new fragment receipt.
    // Failure is sticky for this process: do not silently discard a bad journal.
    private val startupHealthy: Boolean = runCatching { reconcile().optBoolean("ok", false) }.getOrDefault(false)

    @Synchronized
    fun execute(payload: JSONObject): JSONObject = runCatching {
        if (!startupHealthy) return@runCatching refused("fragment_recovery_unavailable")
        when (payload.optString("action")) {
            "write" -> write(payload)
            "verify" -> verify(payload)
            "reconcile" -> reconcile()
            "read_chunk" -> readChunk(payload)
            "discard_capture" -> discardCapture(payload)
            "inventory" -> inventory(payload)
            else -> refused("unsupported_fragment_action")
        }
    }.getOrElse { refused("fragment_store_io_error") }

    private fun write(request: JSONObject): JSONObject {
        val capture = request.optString("capture_id")
        if (capture.isBlank() || capture.length > 256) return refused("capture_required")
        // A fragment cannot be admitted for a capture that no longer owns an
        // encrypted, unexpired paired handoff. No raw header is ever requested.
        val handoff = MediaRequestHandoffStore.forCapture(capture) ?: return refused("capture_session_missing")
        if (handoff.expiresAtEpochMs <= System.currentTimeMillis()) return refused("capture_session_expired")
        val id = request.optString("fragment_id")
        val generation = request.optLong("generation")
        val role = request.optString("role")
        val expected = request.optLong("expected_length")
        val digest = request.optString("hash")
        if (!id.matches(Regex("fragment_[0-9a-f]{64}")) || generation <= 0L ||
            role !in setOf("media", "video", "audio", "subtitle", "init") ||
            expected <= 0 || expected > MaxFragmentBytes || !digest.matches(Regex("sha256:[0-9a-f]{64}"))) {
            return refused("fragment_request_invalid")
        }
        val encoded = request.optString("body_base64")
        if (encoded.length > ((MaxFragmentBytes + 2) / 3 * 4) + 8) return refused("fragment_too_large")
        val bytes = runCatching { Base64.decode(encoded, Base64.NO_WRAP) }.getOrNull() ?: return refused("fragment_encoding_invalid")
        if (bytes.size.toLong() != expected || hash(bytes) != digest) return refused("fragment_integrity_mismatch")
        val name = "${hash(capture.toByteArray(Charsets.UTF_8)).removePrefix("sha256:")}-$id-g$generation.part"
        val ref = "parts/$name"
        val identity = request.optJSONObject("identity") ?: return refused("fragment_identity_required")
        val protocol = identity.optString("protocol")
        val timeline = identity.optString("timeline_key")
        val resource = identity.optString("resource_id")
        if (protocol !in setOf("hls", "dash") || timeline.length !in 4..256 ||
            resource.length !in 8..256 || listOf(timeline,resource).any { it.contains("://") || it.any { c -> c.code == 0 } })
            return refused("fragment_identity_invalid")
        val trackRole = request.optString("track_role")
        if (trackRole.isNotEmpty() && trackRole !in setOf("video", "audio")) return refused("fragment_track_invalid")
        val current = readJournal()
        val key = "${hash(capture.toByteArray(Charsets.UTF_8))}:$id"
        val prior = current.optJSONObject(key)
        if (prior != null) {
            val oldGeneration = prior.optLong("generation")
            if (generation < oldGeneration) return refused("stale_fragment_generation")
            if (generation == oldGeneration) {
                return if (prior.optString("hash") == digest && prior.optLong("length") == expected &&
                    prior.optString("role") == role && checkReceipt(prior)) accepted(prior)
                else refused("fragment_generation_conflict")
            }
        }
        if (!root.isDirectory || !parts.isDirectory || !canonicalChild(parts) || !canonicalChild(root)) return refused("unsafe_fragment_directory")
        val used = parts.listFiles()?.sumOf { if (it.isFile) it.length() else MaxQuotaBytes } ?: return refused("fragment_directory_unavailable")
        if (used < 0 || used > MaxQuotaBytes || expected > MaxQuotaBytes - used) return refused("fragment_quota_exceeded")
        val target = File(parts, name)
        if (target.exists()) return refused("fragment_target_collision")
        atomicFile(target, bytes)
        val receipt = JSONObject().put("fragment_id", id).put("generation", generation)
            .put("hash", digest).put("length", expected).put("role", role)
            .put("identity", identity).put("track_role", trackRole)
            .put("artifact_ref", ref).put("capture_hash", hash(capture.toByteArray(Charsets.UTF_8)))
        current.put(key, receipt)
        // Only this atomic journal replacement makes the file a committed artifact.
        atomicFile(journal, current.toString().toByteArray(Charsets.UTF_8))
        return if (checkReceipt(receipt)) accepted(receipt) else refused("fragment_readback_failed")
    }

    private fun verify(request: JSONObject): JSONObject {
        val capture = request.optString("capture_id")
        val id = request.optString("fragment_id")
        if (capture.isBlank() || !id.matches(Regex("fragment_[0-9a-f]{64}"))) return refused("fragment_request_invalid")
        val key = "${hash(capture.toByteArray(Charsets.UTF_8))}:$id"
        val receipt = readJournal().optJSONObject(key) ?: return refused("fragment_receipt_missing")
        if (request.optLong("generation") != receipt.optLong("generation") ||
            request.optString("hash") != receipt.optString("hash") ||
            request.optLong("expected_length") != receipt.optLong("length") || !checkReceipt(receipt)) {
            return refused("fragment_readback_failed")
        }
        return accepted(receipt)
    }

    private fun readChunk(request: JSONObject): JSONObject {
        val accepted = verify(request)
        if (!accepted.optBoolean("ok", false)) return refused("readback_unverified")
        val capture = request.optString("capture_id")
        val id = request.optString("fragment_id")
        val key = "${hash(capture.toByteArray(Charsets.UTF_8))}:$id"
        val receipt = readJournal().optJSONObject(key) ?: return refused("fragment_missing")
        val offset = request.optLong("offset", -1L)
        val length = request.optLong("length", -1L)
        val total = receipt.optLong("length")
        if (offset < 0L || length !in 1L..65536L || offset > total || length > total - offset)
            return refused("read_range_invalid")
        val file = File(root, receipt.getString("artifact_ref"))
        val bytes = ByteArray(length.toInt())
        java.io.RandomAccessFile(file, "r").use { handle ->
            handle.seek(offset)
            handle.readFully(bytes)
        }
        return JSONObject().put("ok", true).put("body_base64", Base64.encodeToString(bytes, Base64.NO_WRAP))
            .put("length", length)
    }

    private fun inventory(request: JSONObject): JSONObject {
        val capture = request.optString("capture_id")
        val role = request.optString("track_role")
        if (capture.isBlank() || capture.length > 256 || role !in setOf("video", "audio", "all"))
            return refused("inventory_scope_invalid")
        val prefix = hash(capture.toByteArray(Charsets.UTF_8)) + ":"
        val journalData = readJournal()
        val rows = JSONArray()
        val keys = journalData.keys()
        while (keys.hasNext()) {
            val key = keys.next()
            if (!key.startsWith(prefix)) continue
            val rec = journalData.optJSONObject(key) ?: return refused("inventory_corrupt")
            if (role != "all" && rec.optString("track_role") != role) continue
            if (rows.length() >= 4096 || !checkReceipt(rec) || rec.optJSONObject("identity") == null)
                return refused("inventory_unverified")
            rows.put(rec)
        }
        return JSONObject().put("ok", true).put("records", rows)
    }

    private fun discardCapture(request: JSONObject): JSONObject {
        val capture = request.optString("capture_id")
        if (capture.isBlank() || capture.length > 256) return refused("capture_required")
        val prefix = hash(capture.toByteArray(Charsets.UTF_8)) + ":"
        val rows = readJournal()
        val names = mutableListOf<String>()
        val keys = mutableListOf<String>()
        val scan = rows.keys()
        while (scan.hasNext()) {
            val key = scan.next()
            if (!key.startsWith(prefix)) continue
            val rec = rows.optJSONObject(key) ?: return refused("cleanup_corrupt")
            if (!checkReceipt(rec)) return refused("cleanup_unverified")
            names += rec.optString("artifact_ref")
            keys += key
        }
        if (!canonicalChild(parts)) return refused("cleanup_unsafe")
        for (name in names) {
            val target = File(root,name)
            if (java.nio.file.Files.isSymbolicLink(target.toPath()) ||
                target.canonicalFile.parentFile != parts.canonicalFile) return refused("cleanup_unsafe")
        }
        // Journal-first tombstone; after a crash, reconcile removes orphans.
        keys.forEach { rows.remove(it) }
        atomicFile(journal, rows.toString().toByteArray(Charsets.UTF_8))
        for (name in names) {
            val target = File(root,name)
            if (target.exists() && !target.delete()) return refused("cleanup_failed")
        }
        syncDirectory(parts)
        val owner = hash(capture.toByteArray(Charsets.UTF_8)).removePrefix("sha256:")
        val remaining = parts.listFiles()?.count { it.name.startsWith("$owner-fragment_") }
            ?: return refused("cleanup_unavailable")
        if (remaining != 0) return refused("cleanup_incomplete")
        return JSONObject().put("ok",true).put("status","discarded_verified").put("remaining",0)
    }

    private fun reconcile(): JSONObject {
        val entries = readJournal()
        val live = mutableSetOf<String>()
        var corrupt = 0
        val keys = entries.keys()
        while (keys.hasNext()) {
            val key = keys.next()
            val receipt = entries.optJSONObject(key) ?: continue
            if (checkReceipt(receipt)) live += receipt.optString("artifact_ref").removePrefix("parts/")
            else { entries.remove(key); corrupt++ }
        }
        atomicFile(journal, entries.toString().toByteArray(Charsets.UTF_8))
        parts.listFiles()?.forEach { file ->
            if (!file.isFile || !file.name.endsWith(".part")) return refused("unsafe_fragment_directory")
            if (file.name !in live && !file.delete()) return refused("fragment_cleanup_failed")
        }
        syncDirectory(parts)
        return JSONObject().put("ok", true).put("status", "reconciled").put("corrupt", corrupt)
    }

    private fun checkReceipt(item: JSONObject): Boolean {
        val ref = item.optString("artifact_ref")
        if (!ref.matches(Regex("parts/[0-9a-f]{64}-fragment_[0-9a-f]{64}-g[0-9]+\\.part"))) return false
        val file = File(root, ref)
        if (!canonicalChild(parts) || java.nio.file.Files.isSymbolicLink(file.toPath()) ||
            file.canonicalFile.parentFile != parts.canonicalFile || !file.isFile ||
            file.length() != item.optLong("length")) return false
        return file.inputStream().use { input ->
            val md = MessageDigest.getInstance("SHA-256")
            val buffer = ByteArray(64 * 1024)
            var n: Int
            do { n = input.read(buffer); if (n > 0) md.update(buffer, 0, n) } while (n >= 0)
            "sha256:" + md.digest().joinToString("") { "%02x".format(it) } == item.optString("hash")
        }
    }

    private fun readJournal(): JSONObject {
        if (!journal.exists()) return JSONObject()
        require(journal.length() <= 32L * 1024L * 1024L)
        return JSONObject(journal.readText(Charsets.UTF_8))
    }

    private fun atomicFile(target: File, bytes: ByteArray) {
        require(target.parentFile == parts || target.parentFile == root)
        val temp = File.createTempFile(".mp05-", ".stage", target.parentFile)
        try {
            FileOutputStream(temp).use { output ->
                output.write(bytes)
                output.fd.sync()
            }
            Os.rename(temp.absolutePath, target.absolutePath)
            syncDirectory(target.parentFile!!)
        } finally { if (temp.exists()) temp.delete() }
    }
    private fun canonicalChild(dir: File): Boolean =
        dir.canonicalFile.path.startsWith(root.parentFile!!.canonicalPath + File.separator) &&
            !java.nio.file.Files.isSymbolicLink(dir.toPath())
    private fun syncDirectory(dir: File) {
        // Only app-private, existing, non-symlink directories are eligible.
        require(dir.isDirectory && canonicalChild(dir)) { "unsafe_fragment_directory" }
        // Android SDK exposes O_RDONLY for directory handles; keep the directory fsync.
        val fd = Os.open(dir.absolutePath, OsConstants.O_RDONLY, 0)
        try { Os.fsync(fd) } finally { Os.close(fd) }
    }
    private fun hash(bytes: ByteArray): String = "sha256:" + MessageDigest.getInstance("SHA-256")
        .digest(bytes).joinToString("") { "%02x".format(it) }
    private fun accepted(receipt: JSONObject): JSONObject = JSONObject().put("ok", true)
        .put("fragment_id", receipt.getString("fragment_id"))
        .put("generation", receipt.getLong("generation"))
        .put("hash", receipt.getString("hash"))
        .put("expected_length", receipt.getLong("length"))
        .put("artifact_ref", receipt.getString("artifact_ref"))
    private fun refused(code: String): JSONObject = JSONObject().put("ok", false).put("error_code", code)
    private companion object {
        const val MaxFragmentBytes = 2 * 1024 * 1024
        const val MaxQuotaBytes = 512L * 1024L * 1024L
    }
}
