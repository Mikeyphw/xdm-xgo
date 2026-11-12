package com.mikeyphw.xdm.android.engine

import java.security.MessageDigest

/** Accidental-corruption seal for an app-private, credential-free session row.
 * SHA-256 is a checksum, NOT a MAC; it does not authenticate a compromised app.
 * A length-prefixed canonical layout prevents ambiguous field concatenation.
 */
internal object AndroidMP09SessionJournalGuard {
    const val SCHEMA = 2
    private val FIELD_NAMES = setOf("schema_version", "capture_hash", "binding_sha256",
        "started_at_epoch_ms", "generation", "phase", "protocol", "require_audio",
        "dvr_capable", "user_limit_ms", "user_limit_bytes", "session_seal")
    fun exactFields(names: Collection<String>): Boolean =
        names.size == FIELD_NAMES.size && names.toSet() == FIELD_NAMES

    fun checksum(fields: List<String>): String {
        require(fields.size == 11 && fields.all { it.length <= 256 })
        val digest = MessageDigest.getInstance("SHA-256")
        for (field in fields) {
            val bytes = field.toByteArray(Charsets.UTF_8)
            digest.update(byteArrayOf((bytes.size ushr 24).toByte(),
                (bytes.size ushr 16).toByte(), (bytes.size ushr 8).toByte(), bytes.size.toByte()))
            digest.update(bytes)
        }
        return "sha256:" + digest.digest().joinToString("") { "%02x".format(it) }
    }
}
