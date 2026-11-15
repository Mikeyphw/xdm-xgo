package com.mikeyphw.xdm.android.engine

import android.content.Context
import android.system.Os
import android.system.OsConstants
import com.mikeyphw.xdm.android.media.ffmpeg.EmbeddedFfmpegRuntime
import com.mikeyphw.xdm.android.media.ffmpeg.FfmpegPostProcessor
import com.mikeyphw.xdm.android.scheduler.MediaRequestHandoffStore
import java.io.File
import java.io.FileOutputStream
import java.security.MessageDigest
import java.nio.file.Files
import java.util.UUID
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import org.json.JSONObject

/**
 * MP08B1 Android fragment-to-FFmpeg adapter. This is a *private staging* port,
 * not an Android MediaStore publisher or an MP08A DownloadReady authority.
 * It accepts only MP05 receipt identities, never filenames, URLs, cookies,
 * headers, arbitrary argv, or caller-provided destination paths.
 *
 * A later MP08B2 adapter must independently read this staged output, bind it
 * to the unforgeable Go MP08FinalizationPlan seal, and atomically publish.
 */
internal class AndroidLiveMP08VerifiedStageBroker(
    context: Context,
    private val runtime: EmbeddedFfmpegRuntime,
) {
    private val app = context.applicationContext
    private val root = File(app.filesDir, "xgo-mp08b-stage")
    private val mp05Root = File(app.filesDir, "xgo-fragments-mp09")
    private val mp05Parts = File(mp05Root, "parts")
    private val mp05Journal = File(mp05Root, "journal-v1.json")
    private val mutex = Mutex()

    suspend fun execute(request: JSONObject): JSONObject = mutex.withLock {
        val capture = request.optString("capture_id")
        val destination = request.optString("destination_key")
        val source = request.optString("source")
        if (request.optInt("schema_version", -1) != 1 || request.optString("action") != "assemble_verified" ||
            source !in setOf("hls_live", "dash_live") || request.optInt("period_count", -1) != 1 ||
            !safeName.matches(destination) || capture.isBlank() || capture.length > 256 ||
            request.optBoolean("partial") || request.optBoolean("has_gaps") || request.optBoolean("is_dynamic") ||
            request.optBoolean("require_subtitle") || request.optString("container") != "mp4") {
            return@withLock refused("mp08_plan_not_admitted")
        }
        val handoff = MediaRequestHandoffStore.forCapture(capture)
        val browserAuthorized = handoff != null && handoff.expiresAtEpochMs > System.currentTimeMillis()
        // Go's sealed MP09 plan may stage verified LOCAL fragments after the
        // browser's network authorization expires. It cannot fetch new media.
        if (!browserAuthorized && source !in setOf("hls_live", "dash_live")) {
            return@withLock refused("mp08_capture_authorization_missing")
        }
        val duration = request.optLong("expected_duration_ms", -1L)
        if (duration < 1_000L || duration > 24L * 60 * 60 * 1_000) return@withLock refused("mp08_duration_invalid")
        val inputTracks = request.optJSONArray("tracks") ?: return@withLock refused("mp08_tracks_missing")
        if (inputTracks.length() !in 1..2) return@withLock refused("mp08_tracks_invalid")
        val kinds = (0 until inputTracks.length()).map { inputTracks.optJSONObject(it)?.optString("role") ?: "" }
        if (kinds.distinct().size != kinds.size || kinds.firstOrNull() != "video" || kinds.any { it !in setOf("video", "audio") } ||
            request.optBoolean("require_audio") && "audio" !in kinds) {
            return@withLock refused("mp08_required_track_missing")
        }
        // Directory and manifest checks are deliberately before any FFmpeg call.
        if (!directorySafe(app.filesDir) || !directorySafe(mp05Root) || !directorySafe(mp05Parts) ||
            !mp05Journal.isFile || Files.isSymbolicLink(mp05Journal.toPath()) || mp05Journal.length() > 32L * 1024 * 1024) {
            return@withLock refused("mp08_fragment_journal_unavailable")
        }
        val journal = runCatching { JSONObject(mp05Journal.readText()) }.getOrNull()
            ?: return@withLock refused("mp08_fragment_journal_invalid")
        if (!root.exists() && !root.mkdirs()) return@withLock refused("mp08_private_directory_unavailable")
        if (!directorySafe(root)) return@withLock refused("mp08_private_directory_unsafe")
        val verified = File(root, "verified")
        if (!verified.exists() && !verified.mkdirs()) return@withLock refused("mp08_private_directory_unavailable")
        if (!directorySafe(verified)) return@withLock refused("mp08_private_directory_unsafe")
        val captureHash = digest(capture.toByteArray()).removePrefix("sha256:")
        val target = File(verified, "$captureHash-$destination.mp4")
        val journalTarget = File(verified, "$captureHash-$destination.receipt.json")
        // Do not replace a previously published/staged candidate or replay its name.
        if (target.exists() || journalTarget.exists()) return@withLock refused("mp08_destination_conflict")
        val work = File(root, "work-${UUID.randomUUID()}")
        if (!work.mkdir() || !directorySafe(work)) return@withLock refused("mp08_work_directory_unsafe")
        var promoted = false
        try {
            val seen = hashSetOf<String>()
            var admittedBytes = 0L
            val processor = FfmpegPostProcessor(runtime, work)
            val trackOutputs = mutableMapOf<String, File>()
            for (index in 0 until inputTracks.length()) {
                val track = inputTracks.optJSONObject(index) ?: return@withLock refused("mp08_track_invalid")
                val role = kinds[index]
                val units = track.optJSONArray("parts") ?: return@withLock refused("mp08_parts_missing")
                if (units.length() !in 1..4096) return@withLock refused("mp08_part_count_invalid")
                val partFiles = mutableListOf<File>()
                for (partIndex in 0 until units.length()) {
                    val item = units.optJSONObject(partIndex) ?: return@withLock refused("mp08_part_invalid")
                    if (item.optInt("index", -1) != partIndex) return@withLock refused("mp08_part_order_invalid")
                    val init = item.optJSONObject("init")
                    val media = item.optJSONObject("media") ?: return@withLock refused("mp08_media_receipt_missing")
                    val unique = media.optString("fragment_id")
                    if (!seen.add(unique)) return@withLock refused("mp08_duplicate_fragment")
                    val stagePart = File(work, "$role-${partIndex.toString().padStart(5, '0')}.${if (init == null) "ts" else "mp4"}")
                    FileOutputStream(stagePart).use { output ->
                        if (init != null) {
                            admittedBytes = safeAdd(admittedBytes, copyVerified(init, "init", captureHash, journal, output))
                        }
                        admittedBytes = safeAdd(admittedBytes, copyVerified(media, role, captureHash, journal, output))
                        output.fd.sync()
                    }
                    if (admittedBytes > MaxStageBytes) return@withLock refused("mp08_stage_quota_exceeded")
                    partFiles += stagePart
                }
                val trackFile = File(work, if (role == "video") "verified-video.mp4" else "verified-audio.m4a")
                val trackResult = processor.finalizeNativeHls(
                    partFiles, trackFile, expectedDurationMs = duration,
                    requireVideo = role == "video", requireAudio = role == "audio",
                )
                if (!trackResult.success || trackResult.verification?.valid != true || !trackFile.isFile) {
                    return@withLock refused("mp08_ffmpeg_track_verification_failed")
                }
                trackOutputs[role] = trackFile
            }
            val stageFile = File(work, "verified-output.mp4")
            val finalResult = if ("audio" in trackOutputs) {
                processor.muxTracks(
                    requireNotNull(trackOutputs["video"]), requireNotNull(trackOutputs["audio"]),
                    stageFile, expectedDurationMs = duration,
                )
            } else {
                processor.remux(
                    requireNotNull(trackOutputs["video"]), stageFile,
                    expectation = com.mikeyphw.xdm.android.media.ffmpeg.FfmpegVerificationExpectation(
                        requireVideo = true, requireAudio = request.optBoolean("require_audio"),
                        expectedDurationMs = duration,
                    ),
                )
            }
            if (!finalResult.success || finalResult.verification?.valid != true ||
                !stageFile.isFile || stageFile.length() < 1024L) {
                return@withLock refused("mp08_final_probe_refused")
            }
            // The FFmpeg processor has already probed and atomically staged.
            // Sync and rehash *before* and *after* the final private rename.
            val hashBefore = hashFile(stageFile)
            val sizeBefore = stageFile.length()
            FileOutputStream(stageFile, true).use { it.fd.sync() }
            if (target.exists()) return@withLock refused("mp08_destination_conflict")
            Os.rename(stageFile.absolutePath, target.absolutePath)
            promoted = true
            syncDirectory(verified)
            if (target.length() != sizeBefore || hashFile(target) != hashBefore) {
                return@withLock refused("mp08_post_rename_corrupt")
            }
            val receipt = JSONObject()
                .put("schema_version", 1).put("capture_hash", captureHash)
                .put("destination_key", destination).put("hash", hashBefore)
                .put("bytes", sizeBefore).put("source", source).put("status", "verified_app_private")
                .put("download_ready", false).put("media_store_published", false)
            val pendingReceipt = File(verified, ".${UUID.randomUUID()}.receipt")
            try {
                FileOutputStream(pendingReceipt).use { out ->
                    out.write(receipt.toString().toByteArray(Charsets.UTF_8))
                    out.fd.sync()
                }
                Os.rename(pendingReceipt.absolutePath, journalTarget.absolutePath)
                syncDirectory(verified)
            } finally { pendingReceipt.delete() }
            return@withLock JSONObject().put("ok", true)
                .put("status", "verified_app_private")
                .put("publication_ref", destination)
                .put("sha256", hashBefore).put("bytes", sizeBefore)
                .put("download_ready", false).put("media_store_published", false)
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (_: Throwable) {
            return@withLock refused("mp08_host_verification_failed")
        } finally {
            work.deleteRecursively()
            // If the receipt was not durably committed, an output candidate
            // must not survive as an apparently published artifact.
            if (promoted && !journalTarget.isFile) target.delete()
        }
    }

    private fun copyVerified(
        claim: JSONObject, role: String, captureHash: String, journal: JSONObject,
        output: FileOutputStream,
    ): Long {
        val id = claim.optString("fragment_id")
        val generation = claim.optLong("generation", -1)
        val hash = claim.optString("hash")
        val expected = claim.optLong("length", -1)
        require(fragmentID.matches(id) && generation > 0L && shaID.matches(hash) && expected in 1..MaxFragmentBytes)
        val original = journal.optJSONObject("sha256:$captureHash:$id") ?: error("missing fragment")
        require(original.optString("fragment_id") == id && original.optLong("generation") == generation &&
            original.optLong("length") == expected && original.optString("hash") == hash)
        val storedRole = original.optString("role")
        require(if (role == "init") storedRole == "init" else storedRole in setOf(role, "media"))
        val ref = original.optString("artifact_ref")
        require(ref.matches(Regex("parts/$captureHash-fragment_[0-9a-f]{64}-g$generation\\.part")))
        val file = File(mp05Root, ref)
        require(directorySafe(mp05Parts) && !Files.isSymbolicLink(file.toPath()) &&
            file.canonicalFile.parentFile == mp05Parts.canonicalFile && file.isFile && file.length() == expected)
        val md = MessageDigest.getInstance("SHA-256")
        var nTotal = 0L
        file.inputStream().use { input ->
            val buffer = ByteArray(64 * 1024)
            while (true) {
                val n = input.read(buffer)
                if (n == -1) break
                require(n > 0)
                md.update(buffer, 0, n)
                output.write(buffer, 0, n)
                nTotal += n
                require(nTotal <= expected)
            }
        }
        val copiedHash = "sha256:" + md.digest().joinToString("") { "%02x".format(it) }
        require(nTotal == expected && copiedHash == hash)
        return nTotal
    }

    private fun directorySafe(path: File): Boolean = runCatching {
        val base = app.filesDir.canonicalPath + File.separator
        path.isDirectory && !Files.isSymbolicLink(path.toPath()) &&
            (path == app.filesDir || path.canonicalPath.startsWith(base))
    }.getOrDefault(false)

    private fun hashFile(path: File): String {
        val md = MessageDigest.getInstance("SHA-256")
        path.inputStream().use { input ->
            val buffer = ByteArray(64 * 1024)
            while (true) { val n = input.read(buffer); if (n < 0) break; if (n > 0) md.update(buffer, 0, n) }
        }
        return "sha256:" + md.digest().joinToString("") { "%02x".format(it) }
    }
    private fun digest(value: ByteArray): String = "sha256:" + MessageDigest.getInstance("SHA-256")
        .digest(value).joinToString("") { "%02x".format(it) }

    private fun syncDirectory(dir: File) {
        require(directorySafe(dir))
        val handle = Os.open(dir.absolutePath, OsConstants.O_RDONLY, 0)
        try { Os.fsync(handle) } finally { Os.close(handle) }
    }
    private fun safeAdd(a: Long, b: Long): Long {
        require(b > 0 && a <= MaxStageBytes - b)
        return a + b
    }
    private fun refused(code: String): JSONObject = JSONObject()
        .put("ok", false).put("error_code", code).put("download_ready", false)

    private companion object {
        const val MaxFragmentBytes = 2L * 1024 * 1024
        const val MaxStageBytes = 512L * 1024 * 1024
        val safeName = Regex("^[A-Za-z0-9_-]{1,96}$")
        val fragmentID = Regex("fragment_[0-9a-f]{64}")
        val shaID = Regex("sha256:[0-9a-f]{64}")
    }
}
