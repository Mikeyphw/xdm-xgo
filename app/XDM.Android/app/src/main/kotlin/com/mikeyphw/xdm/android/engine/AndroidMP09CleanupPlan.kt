package com.mikeyphw.xdm.android.engine

/**
 * Names-only deletion scope for MP09 crash recovery. Neither artifact_ref nor
 * fragment hashes from a potentially damaged journal authorize a file path.
 * Every deletion candidate is derived from the exact owning capture digest.
 * Caller independently checks file type, symlink status, canonical parent,
 * and post-delete absence before reporting cleanup success.
 */
internal object AndroidMP09CleanupPlan {
    private val captureDigest = Regex("sha256:[0-9a-f]{64}")
    private val fragmentId = Regex("fragment_[0-9a-f]{64}")
    private val ownedFileSuffix = Regex("fragment_[0-9a-f]{64}-g[1-9][0-9]*\\.part")
    const val MAX_OWNED_ENTRIES = 4096

    fun ownedJournalKeys(captureHash: String, journalKeys: List<String>): List<String> {
        require(captureDigest.matches(captureHash)) { "invalid capture digest" }
        val prefix = "$captureHash:"
        val owned = journalKeys.filter { it.startsWith(prefix) }
        require(owned.size <= MAX_OWNED_ENTRIES) { "too many journal entries" }
        require(owned.all { fragmentId.matches(it.removePrefix(prefix)) }) { "invalid owned journal key" }
        require(owned.size == owned.toSet().size) { "duplicate journal entry" }
        return owned
    }

    fun ownedFiles(parts: java.io.File, captureHash: String): List<java.io.File> {
        require(parts.isDirectory && !java.nio.file.Files.isSymbolicLink(parts.toPath())) { "unsafe parts directory" }
        val listed = parts.listFiles() ?: error("parts directory unreadable")
        val names = ownedPartNames(captureHash, listed.map { it.name })
        val canonical = parts.canonicalFile
        return names.map { name ->
            val file = java.io.File(parts, name)
            require(!java.nio.file.Files.isSymbolicLink(file.toPath()) &&
                file.isFile && file.canonicalFile.parentFile == canonical) { "unsafe owned file" }
            file
        }
    }

    fun deleteOwnedFiles(parts: java.io.File, captureHash: String, syncDirectory: () -> Unit): Int {
        val files = ownedFiles(parts, captureHash) // Validate ALL before deleting ANY.
        for (file in files) {
            if (!file.delete()) error("scoped unlink failed; explicit retry required")
        }
        syncDirectory()
        require(ownedFiles(parts, captureHash).isEmpty()) { "scoped post-delete verification failed" }
        return files.size
    }

    fun ownedPartNames(captureHash: String, fileNames: List<String>): List<String> {
        require(captureDigest.matches(captureHash)) { "invalid capture digest" }
        val owner = captureHash.removePrefix("sha256:")
        val prefix = "$owner-"
        val candidatePrefix = "$owner-fragment_"
        // A suspicious file using this capture owner prefix is never ignored.
        val selected = fileNames.filter { it.startsWith(prefix) }
        require(selected.size <= MAX_OWNED_ENTRIES) { "too many owned artifacts" }
        require(selected.all { it.startsWith(candidatePrefix) &&
            ownedFileSuffix.matches(it.removePrefix(prefix)) }) { "unexpected owned filename" }
        require(selected.size == selected.toSet().size) { "duplicate owned artifact" }
        return selected
    }
}
