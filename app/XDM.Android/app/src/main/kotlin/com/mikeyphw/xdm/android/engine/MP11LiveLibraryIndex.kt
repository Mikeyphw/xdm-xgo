package com.mikeyphw.xdm.android.engine

import android.content.Context
import android.net.Uri
import android.provider.MediaStore
import java.io.File
import java.nio.file.Files
import java.security.MessageDigest
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import org.json.JSONObject

/** Read-only view of the existing MP08 publication receipts AND MP09 sealed phase.
 * Never creates a MediaStore row, publishes media, or trusts a filename as proof.
 * No browser handoffs, signed URLs, cookies, or raw capture source are retained.
 */
internal data class MP11LiveLibraryCapture(val id: String, val title: String)
internal data class MP11VerifiedLiveRecording(
    val captureId: String, val title: String, val publicationId: String,
    val mediaStoreUri: String, val bytes: Long, val fileName: String,
    val cleanupPending: Boolean, val modifiedEpochMs: Long,
)
internal data class MP11LiveLibraryReview(val captureId: String, val title: String, val reason: String)
internal data class MP11LiveLibrarySnapshot(
    val verified: List<MP11VerifiedLiveRecording> = emptyList(),
    val review: List<MP11LiveLibraryReview> = emptyList(),
)

internal object MP11LiveLibraryIndex {
    private val captureId = Regex("^[A-Za-z0-9_-]{1,96}$")
    private val digest = Regex("sha256:[0-9a-f]{64}")
    private val outputName = Regex("[A-Za-z0-9_-]{1,96}")

    suspend fun scan(context: Context, captures: List<MP11LiveLibraryCapture>): MP11LiveLibrarySnapshot {
        val app = context.applicationContext
        val root = File(app.filesDir, "xgo-mp08b-stage")
        val published = File(root, "publication-receipts")
        if (!published.exists()) return MP11LiveLibrarySnapshot()
        if (!safeDirectory(app.filesDir, root) || !safeDirectory(app.filesDir, published))
            return MP11LiveLibrarySnapshot(review = listOf(MP11LiveLibraryReview("", "Live recordings", "Unsafe publication receipt directory; no files were opened")))
        val files = published.listFiles()?.takeIf { it.size <= 4096 }
            ?: return MP11LiveLibrarySnapshot(review = listOf(MP11LiveLibraryReview("", "Live recordings", "Publication inventory unavailable or too large")))
        val store = AndroidLiveDurableFragmentStore(app)
        val verified = mutableListOf<MP11VerifiedLiveRecording>()
        val review = mutableListOf<MP11LiveLibraryReview>()
        val seenPublications = mutableSetOf<String>()
        val seenUris = mutableSetOf<String>()
        for (capture in captures.distinctBy { it.id }.take(128)) {
            currentCoroutineContext().ensureActive()
            if (!captureId.matches(capture.id)) continue
            val prefix = sha256(capture.id.toByteArray(Charsets.UTF_8)).removePrefix("sha256:") + "-"
            val owned = files.filter { it.name.startsWith(prefix) && it.name.endsWith(".json") }
            val phase = verifiedPhase(store, capture.id)
            if (owned.size > 64) {
                review += MP11LiveLibraryReview(capture.id, capture.title, "Too many publication receipts; manual review required")
                continue
            }
            if (phase == "recording" && owned.isEmpty()) {
                review += MP11LiveLibraryReview(capture.id, capture.title,
                    "Recording ongoing or interrupted; stored fragments are not a playable file")
            }
            if (phase == "publishing" || (phase in setOf("published", "published_clean") && owned.isEmpty())) {
                review += MP11LiveLibraryReview(capture.id, capture.title,
                    "Publication requires verification; not available for playback")
            }
            for (file in owned) {
                currentCoroutineContext().ensureActive()
                val item = try {
                    val dest = file.name.removePrefix(prefix).removeSuffix(".json")
                    if (!outputName.matches(dest) || !safeFile(file, published) || file.length() !in 1L..65536L)
                        null
                    else {
                        val row = JSONObject(file.readText(Charsets.UTF_8))
                        val bytes = row.optLong("bytes", -1)
                        val uri = row.optString("uri")
                        val digestValue = row.optString("sha256")
                        val pub = row.optString("publication_id")
                        val validBinding = row.optString("capture_hash") == prefix.dropLast(1) &&
                            row.optString("destination_key") == dest && digest.matches(digestValue)
                        val safeUri = runCatching {
                            val parsed = Uri.parse(uri)
                            parsed.scheme == "content" && parsed.authority == MediaStore.AUTHORITY &&
                                parsed.query == null && parsed.fragment == null && uri.length in 1..512
                        }.getOrDefault(false)
                        val actual = if (validBinding && safeUri && phase in setOf("published", "published_clean") &&
                            bytes in 1024L..MP11LiveLibraryPolicy.MAX_OUTPUT_BYTES)
                            verifyMediaStore(app, uri, bytes, digestValue) else false
                        val finalPhase = verifiedPhase(store, capture.id)
                        if (!validBinding || !safeUri || finalPhase != phase ||
                            !MP11LiveLibraryPolicy.completed(finalPhase, row.optString("status"),
                                row.optBoolean("visibility_committed"), actual, pub, digestValue, bytes, uri) ||
                            !seenPublications.add(pub) || !seenUris.add(uri)) null
                        else MP11VerifiedLiveRecording(capture.id, capture.title.ifBlank { dest }, pub,
                            uri, bytes, "$dest.mp4", finalPhase != "published_clean", file.lastModified())
                    }
                } catch (cancelled: kotlinx.coroutines.CancellationException) {
                    throw cancelled
                } catch (_: Exception) { null }
                if (item == null) review += MP11LiveLibraryReview(capture.id, capture.title,
                    "Publication, source phase or saved bytes could not be verified")
                else verified += item
            }
        }
        return MP11LiveLibrarySnapshot(
            verified = verified.sortedByDescending { it.modifiedEpochMs },
            review = review.distinctBy { it.captureId to it.reason }.take(64),
        )
    }

    /** Recheck on every Open/Share action; a previously verified URI can be removed or replaced. */
    suspend fun stillVerified(context: Context, entry: MP11VerifiedLiveRecording): Boolean =
        scan(context, listOf(MP11LiveLibraryCapture(entry.captureId, entry.title)))
            .verified.any { it.publicationId == entry.publicationId && it.mediaStoreUri == entry.mediaStoreUri &&
                it.bytes == entry.bytes && it.fileName == entry.fileName }

    private fun verifiedPhase(store: AndroidLiveDurableFragmentStore, id: String): String {
        val reply = store.execute(JSONObject().put("mp09_live", true).put("action", "session_status")
            .put("capture_id", id))
        return if (reply.optBoolean("ok", false)) reply.optString("phase") else "unverified"
    }

    private fun safeDirectory(base: File, dir: File): Boolean = runCatching {
        !Files.isSymbolicLink(dir.toPath()) && dir.isDirectory &&
            dir.canonicalPath.startsWith(base.canonicalPath + File.separator)
    }.getOrDefault(false)

    private fun safeFile(file: File, parent: File): Boolean = runCatching {
        file.isFile && !Files.isSymbolicLink(file.toPath()) &&
            file.canonicalFile.parentFile == parent.canonicalFile
    }.getOrDefault(false)

    private suspend fun verifyMediaStore(context: Context, uriText: String, expected: Long, digestText: String): Boolean {
        val uri = Uri.parse(uriText)
        return try {
            var count = 0L
            val digest = MessageDigest.getInstance("SHA-256")
            val input = context.contentResolver.openInputStream(uri) ?: return false
            input.use { source ->
                val buffer = ByteArray(64 * 1024)
                while (true) {
                    currentCoroutineContext().ensureActive()
                    val n = source.read(buffer)
                    if (n < 0) break
                    if (n > 0) {
                        count += n
                        if (count > expected) return false
                        digest.update(buffer, 0, n)
                    }
                }
            }
            count == expected && "sha256:" + digest.digest().joinToString("") { "%02x".format(it) } == digestText
        } catch (cancelled: kotlinx.coroutines.CancellationException) {
            throw cancelled
        } catch (_: Exception) { false }
    }

    private fun sha256(value: ByteArray): String = "sha256:" +
        MessageDigest.getInstance("SHA-256").digest(value).joinToString("") { "%02x".format(it) }
}
