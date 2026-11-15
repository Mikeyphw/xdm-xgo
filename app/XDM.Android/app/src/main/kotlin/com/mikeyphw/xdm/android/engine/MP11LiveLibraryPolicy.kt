package com.mikeyphw.xdm.android.engine

/** MP11 P03: credential-free, read-only library exposure policy.
 * A MediaStore row does not imply that MP08 AND the Go session phase completed.
 * Actual byte readback and a validated private journal are separate prerequisites.
 */
internal object MP11LiveLibraryPolicy {
    const val MAX_OUTPUT_BYTES = 512L * 1024 * 1024
    private val digest = Regex("sha256:[0-9a-f]{64}")
    private val id = Regex("[A-Za-z0-9_-]{1,96}")
    private val content = Regex("content://media(?:/[^?#\\s]*)?", RegexOption.IGNORE_CASE)

    fun completed(phase: String, status: String, visible: Boolean, verifiedBytes: Boolean,
                  publicationId: String, receiptDigest: String, size: Long, uri: String): Boolean =
        phase in setOf("published", "published_clean") &&
            status == "published_verified" && visible && verifiedBytes &&
            id.matches(publicationId) && digest.matches(receiptDigest) &&
            size in 1024L..MAX_OUTPUT_BYTES && content.matches(uri) &&
            !uri.contains("..")

    fun cleanupLabel(phase: String): String = when (phase) {
        "published_clean" -> "Temporary fragment cleanup verified"
        "published" -> "Published file verified; temporary cleanup requires review"
        else -> "Publication or recovery requires review"
    }

    fun reviewRequired(phase: String, receiptPresent: Boolean, verified: Boolean): Boolean =
        phase == "publishing" ||
            ((phase == "published" || phase == "published_clean") && !verified) ||
            (receiptPresent && phase !in setOf("published", "published_clean"))
}
