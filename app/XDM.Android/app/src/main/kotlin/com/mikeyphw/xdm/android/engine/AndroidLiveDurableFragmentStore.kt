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
internal class AndroidLiveDurableFragmentStore(context: Context) {
    private val root = File(context.applicationContext.filesDir, "xgo-fragments-mp09").apply { mkdirs() }
    private val parts = File(root, "parts").apply { mkdirs() }
    private val journal = File(root, "journal-v1.json")
    private val sessionJournal = File(root, "session-v1.json")
    // Crash recovery must run before accepting any new fragment receipt.
    // Failure is sticky for this process: do not silently discard a bad journal.
    private var startupHealthy: Boolean = runCatching { reconcile().optBoolean("ok", false) }.getOrDefault(false)

    @Synchronized
    fun execute(payload: JSONObject): JSONObject = runCatching {
        if (!payload.optBoolean("mp09_live", false)) return@runCatching refused("mp09_store_scope_denied")
        val action = payload.optString("action")
        // A damaged but parseable per-capture receipt must never strand an
        // explicit user-discard. All other operations stay fail-closed until
        // reconciliation has verified the store again.
        if (!startupHealthy && action !in setOf("discard_capture", "reconcile"))
            return@runCatching refused("fragment_recovery_unavailable")
        when (payload.optString("action")) {
            "write" -> write(payload)
            "verify" -> verify(payload)
            "reconcile" -> reconcile().also { if (it.optBoolean("ok", false)) startupHealthy = true }
            "read_chunk" -> readChunk(payload)
            "discard_capture" -> discardCapture(payload).also {
                // Recover in-process only after a successful, scoped cleanup.
                if (it.optBoolean("ok", false))
                    startupHealthy = runCatching { reconcile().optBoolean("ok", false) }.getOrDefault(false)
            }
            "inventory" -> inventory(payload)
            "session_begin" -> beginSession(payload)
            "session_read" -> readSession(payload)
            "session_finish" -> finishSession(payload)
            "session_status" -> sessionStatus(payload)
            "session_phase" -> changeSessionPhase(payload)
            else -> refused("unsupported_fragment_action")
        }
    }.getOrElse { refused("fragment_store_io_error") }

    // This journal contains only bounded non-secret session metadata. Raw URLs,
    // headers, cookies and signed query strings are never persisted here.
    private fun sessionJournalRows(): JSONObject {
        if (!sessionJournal.exists()) return JSONObject()
        if (sessionJournal.length() > 512L * 1024L ||
            java.nio.file.Files.isSymbolicLink(sessionJournal.toPath())) error("mp09_session_journal_unsafe")
        val rows = JSONObject(sessionJournal.readText(Charsets.UTF_8))
        if (rows.length() > 128) error("mp09_session_journal_count")
        val keys = rows.keys()
        while (keys.hasNext()) {
            val key = keys.next()
            val row = rows.optJSONObject(key) ?: error("mp09_session_journal_row")
            if (row.optString("capture_hash") != key || !validateSession(row))
                error("mp09_session_journal_integrity")
        }
        return rows
    }

    private fun writeSessionRows(rows: JSONObject) {
        if (rows.length() > 128) error("mp09_session_count_exceeded")
        val bytes = rows.toString().toByteArray(Charsets.UTF_8)
        if (bytes.size > 512 * 1024) error("mp09_session_size_exceeded")
        atomicFile(sessionJournal, bytes)
    }

    private fun sessionSeal(row: JSONObject): String = AndroidMP09SessionJournalGuard.checksum(listOf(
        row.optInt("schema_version", -1).toString(), row.optString("capture_hash"),
        row.optString("binding_sha256"), row.optLong("started_at_epoch_ms", -1L).toString(),
        row.optLong("generation", -1L).toString(), row.optString("phase"), row.optString("protocol"),
        row.optBoolean("require_audio", false).toString(), row.optBoolean("dvr_capable", false).toString(),
        row.optLong("user_limit_ms", -1L).toString(), row.optLong("user_limit_bytes", -1L).toString()))

    private fun sessionCaptureKey(capture: String): String {
        require(capture.matches(Regex("^[A-Za-z0-9_-]{1,96}$")))
        return hash(capture.toByteArray(Charsets.UTF_8))
    }

    private fun validateSession(row: JSONObject): Boolean {
        val fingerprint = row.optString("binding_sha256")
        val protocol = row.optString("protocol")
        val started = row.optLong("started_at_epoch_ms", 0L)
        val names = mutableSetOf<String>()
        val keys = row.keys()
        while (keys.hasNext()) names += keys.next()
        return AndroidMP09SessionJournalGuard.exactFields(names) &&
            row.optInt("schema_version", -1) == AndroidMP09SessionJournalGuard.SCHEMA &&
            row.optString("capture_hash").matches(Regex("sha256:[0-9a-f]{64}")) &&
            fingerprint.matches(Regex("sha256:[0-9a-f]{64}")) &&
            row.optLong("generation", 0L) == 1L &&
            protocol in setOf("hls", "dash") &&
            started in 1_600_000_000_000L..4_100_000_000_000L &&
            row.optLong("user_limit_ms", -1L) in 0L..31_536_000_000L &&
            row.optLong("user_limit_bytes", -1L) in 0L..1_099_511_627_776L &&
            row.optString("session_seal").matches(Regex("sha256:[0-9a-f]{64}")) &&
            row.optString("session_seal") == sessionSeal(row) &&
            // Raw DASH representation IDs can themselves carry opaque
            // private identifiers. Only the SHA-256 source binding is durable.
            !row.has("video_representation_id") && !row.has("audio_representation_id") &&
            row.optString("phase") in setOf("recording", "publishing", "published", "published_clean")
    }

    private fun beginSession(request: JSONObject): JSONObject {
        val capture = request.optString("capture_id")
        val key = runCatching { sessionCaptureKey(capture) }.getOrNull() ?: return refused("session_capture_invalid")
        val handoff = MediaRequestHandoffStore.forCapture(capture) ?: return refused("capture_session_missing")
        if (handoff.expiresAtEpochMs <= System.currentTimeMillis()) return refused("capture_session_expired")
        val item = JSONObject()
            .put("schema_version", AndroidMP09SessionJournalGuard.SCHEMA)
            .put("capture_hash", key)
            .put("binding_sha256", request.optString("binding_sha256"))
            .put("started_at_epoch_ms", request.optLong("started_at_epoch_ms"))
            .put("generation", request.optLong("generation"))
            .put("phase", "recording")
            .put("protocol", request.optString("protocol"))
            .put("require_audio", request.optBoolean("require_audio", true))
            .put("dvr_capable", request.optBoolean("dvr_capable", false))
            .put("user_limit_ms", request.optLong("user_limit_ms", 0L))
            .put("user_limit_bytes", request.optLong("user_limit_bytes", 0L))
        item.put("session_seal", sessionSeal(item))
        if (!validateSession(item) || !item.optBoolean("require_audio")) return refused("session_metadata_invalid")
        if (kotlin.math.abs(System.currentTimeMillis() - item.getLong("started_at_epoch_ms")) > 60_000L)
            return refused("session_start_clock_invalid")
        val journalData = sessionJournalRows()
        val previous = journalData.optJSONObject(key)
        if (previous != null) {
            // Re-recording is a NEW user-confirmed capture, not recovery or
            // an implicit retry. Never reset publishing/published/recording.
            val prefix = "$key:"
            val fragments = readJournal()
            val hasReceipts = fragments.keys().asSequence().any { it.startsWith(prefix) }
            val owner = key.removePrefix("sha256:")
            val emptyParts = parts.listFiles()?.none { it.name.startsWith("$owner-fragment_") } == true
            val freshDestination = request.optString("destination_key")
                .matches(Regex("^[A-Za-z0-9_-]{1,96}$"))
            if (!AndroidMP09SessionPhaseGate.mayStartAfterTerminal(previous.optString("phase"),
                    request.optBoolean("fresh_user_start", false), !hasReceipts && emptyParts, freshDestination))
                return refused("session_already_exists_review_required")
        }
        journalData.put(key, item)
        writeSessionRows(journalData)
        return JSONObject().put("ok", true).put("status", "session_created")
    }

    private fun readSession(request: JSONObject): JSONObject {
        val capture = request.optString("capture_id")
        val key = runCatching { sessionCaptureKey(capture) }.getOrNull() ?: return refused("session_capture_invalid")
        val handoff = MediaRequestHandoffStore.forCapture(capture) ?: return refused("capture_session_missing")
        if (handoff.expiresAtEpochMs <= System.currentTimeMillis()) return refused("capture_session_expired")
        val row = sessionJournalRows().optJSONObject(key) ?: return refused("session_not_found")
        if (row.optString("capture_hash") != key || !validateSession(row)) return refused("session_journal_invalid")
        if (!AndroidMP09SessionPhaseGate.mayResume(row.optString("phase")))
            return refused("session_publication_review_required")
        return JSONObject(row.toString()).put("ok", true).put("status", "recoverable_unverified")
    }

    private fun sessionStatus(request: JSONObject): JSONObject {
        val key = runCatching { sessionCaptureKey(request.optString("capture_id")) }.getOrNull()
            ?: return refused("session_capture_invalid")
        val row = sessionJournalRows().optJSONObject(key)
            ?: return JSONObject().put("ok", true).put("phase", "missing")
        if (row.optString("capture_hash") != key || !validateSession(row))
            return refused("session_journal_invalid")
        return JSONObject().put("ok", true).put("phase", row.optString("phase"))
    }

    private fun changeSessionPhase(request: JSONObject): JSONObject {
        val key = runCatching { sessionCaptureKey(request.optString("capture_id")) }.getOrNull()
            ?: return refused("session_capture_invalid")
        val rows = sessionJournalRows()
        val row = rows.optJSONObject(key) ?: return refused("session_not_found")
        val next = request.optString("phase")
        // 'published_clean' requires post-deletion verification and is never
        // granted through a generic phase command, even on an intact journal.
        if (next == "published_clean") return refused("terminal_phase_requires_verified_cleanup")
        if (row.optString("capture_hash") != key || !validateSession(row) ||
            !AndroidMP09SessionPhaseGate.mayTransition(row.optString("phase"), next))
            return refused("session_phase_transition_denied")
        row.put("phase", next)
        row.put("session_seal", sessionSeal(row))
        rows.put(key, row)
        writeSessionRows(rows)
        return JSONObject().put("ok", true).put("phase", next)
    }

    private fun finishSession(request: JSONObject): JSONObject {
        val key = runCatching { sessionCaptureKey(request.optString("capture_id")) }.getOrNull()
            ?: return refused("session_capture_invalid")
        val rows = sessionJournalRows()
        val row = rows.optJSONObject(key)
            ?: return JSONObject().put("ok", true).put("status", "session_already_finished")
        if (!validateSession(row)) return refused("session_journal_invalid")
        // Never erase a publication fence here. Durable retirement of a
        // recording happens only inside discardCapture, after verified deletion.
        if (row.optString("phase") == "recording") return refused("session_finish_requires_verified_discard")
        return JSONObject().put("ok", true).put("status", "publication_fence_retained")
            .put("phase", row.optString("phase"))
    }

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
        // A journal-first cancellation tombstone can leave orphaned parts
        // after a crash. They cannot be mixed into a new recording.
        val owner = hash(capture.toByteArray(Charsets.UTF_8)).removePrefix("sha256:")
        val bound = (0 until rows.length()).map { rows.getJSONObject(it).optString("artifact_ref") }.toSet()
        val unbound = parts.listFiles()?.count { file ->
            file.name.startsWith("$owner-fragment_") && "parts/${file.name}" !in bound
        } ?: return refused("inventory_directory_unavailable")
        return JSONObject().put("ok", true).put("records", rows)
            .put("unbound_fragments", unbound)
    }

    private fun discardCapture(request: JSONObject): JSONObject {
        val capture = request.optString("capture_id")
        if (!capture.matches(Regex("^[A-Za-z0-9_-]{1,96}$"))) return refused("capture_required")
        val sessionKey = hash(capture.toByteArray(Charsets.UTF_8))
        val rows = readJournal() // A globally malformed journal requires manual review; never rewrite it.
        if (java.nio.file.Files.isSymbolicLink(journal.toPath()) ||
            !root.isDirectory || !parts.isDirectory || !canonicalChild(root) || !canonicalChild(parts))
            return refused("cleanup_unsafe_directory_or_journal")
        val sessions = sessionJournalRows() // Validate every publication fence before deletion.
        val priorSession = sessions.optJSONObject(sessionKey)
        if (sessions.has(sessionKey) && (priorSession == null || !validateSession(priorSession)))
            return refused("session_journal_invalid")
        val phase = priorSession?.optString("phase") ?: "missing"
        if (!AndroidMP09SessionPhaseGate.mayDiscard(phase))
            return refused("publication_review_required")

        // Never use a journal-provided artifact_ref for deletion. A corrupted
        // receipt might point at ANOTHER recording inside the same private dir.
        // Scan real filenames and select only files owned by this capture hash.
        val keys = try {
            AndroidMP09CleanupPlan.ownedJournalKeys(sessionKey, rows.keys().asSequence().toList())
        } catch (_: IllegalArgumentException) { return refused("cleanup_journal_keys_invalid") }
        try {
            AndroidMP09CleanupPlan.ownedFiles(parts, sessionKey)
        } catch (_: Exception) { return refused("cleanup_unsafe_owned_path") }

        // Journal-first retirement: if killed after this atomic update and
        // before unlink/fsync, the next explicit cleanup re-discovers the
        // owner-scoped orphan files from the directory, not from receipts.
        keys.forEach { rows.remove(it) }
        atomicFile(journal, rows.toString().toByteArray(Charsets.UTF_8))
        try {
            AndroidMP09CleanupPlan.deleteOwnedFiles(parts, sessionKey) { syncDirectory(parts) }
        } catch (_: Exception) { return refused("cleanup_failed_retry_explicitly") }

        // The session journal is updated ONLY after the filesystem deletion
        // is verified. Published sessions retain a published_clean tombstone.
        val terminal = AndroidMP09SessionPhaseGate.afterVerifiedDiscard(phase)
        if (phase == "recording" && terminal == "missing") sessions.remove(sessionKey)
        if (phase == "published" && terminal == "published_clean") {
            priorSession!!.put("phase", "published_clean")
            priorSession.put("session_seal", sessionSeal(priorSession))
            sessions.put(sessionKey, priorSession)
        }
        if (phase == "recording" || phase == "published") writeSessionRows(sessions)
        return JSONObject().put("ok", true).put("status", "discarded_verified")
            .put("remaining", 0).put("cleanup_scope", "capture_owned_only")
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
            else corrupt++
        }
        // Missing/hash-mismatched entries are never silently erased.
        if (corrupt != 0) return refused("fragment_recovery_unverified")
        val files = parts.listFiles() ?: return refused("fragment_directory_unavailable")
        if (files.any { file ->
                !file.isFile || java.nio.file.Files.isSymbolicLink(file.toPath()) ||
                file.canonicalFile.parentFile != parts.canonicalFile ||
                !file.name.matches(Regex("[0-9a-f]{64}-fragment_[0-9a-f]{64}-g[0-9]+\\.part"))
            }) return refused("unsafe_fragment_directory")
        // Orphans are preserved for explicit user review/discard. No implicit
        // cleanup, and no recovered recording may incorporate them as proof.
        return JSONObject().put("ok", true).put("status", "reconciled")
            .put("corrupt", 0).put("unbound_fragments", files.count { it.name !in live })
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
