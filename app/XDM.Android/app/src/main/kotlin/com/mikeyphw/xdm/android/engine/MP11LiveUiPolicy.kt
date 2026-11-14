package com.mikeyphw.xdm.android.engine

import java.net.URI

/** MP11 transient UI projection, NOT a recording authority. Go owns state and
 * MP05/MP08 own durability/publication. Credentials must never enter this API. */
internal object MP11LiveUiPolicy {
    fun actions(state: String?, dvrCapable: Boolean): Set<String> = when (state) {
        "capturing", "recoverable" -> buildSet {
            add("stop_save"); add("discard")
            if (dvrCapable) add("pause")
        }
        "paused" -> buildSet {
            add("stop_save"); add("discard")
            if (dvrCapable) add("resume")
        }
        "refresh_required" -> setOf("stop_save", "discard", "refresh")
        "stop_pending_verification" -> setOf("stop_save", "discard")
        else -> emptySet()
    }

    private fun origin(raw: String): String? = try {
        val normalized = raw.trim()
        if (normalized.length !in 1..4096 || normalized.any { it == '\r' || it == '\n' || it == '\u0000' }) null
        else {
            val u = URI(normalized)
            if (u.scheme !in setOf("https", "http") || u.host.isNullOrBlank() ||
                u.host.length > 253 || u.userInfo != null || u.fragment != null ||
                u.port !in -1..65535 || u.rawPath.isNullOrEmpty()) null
            else "${u.scheme.lowercase()}://${u.host.lowercase()}:${if (u.port == -1) if (u.scheme == "https") 443 else 80 else u.port}"
        }
    } catch (_: Exception) { null }

    // Authority equality is only UI preflight. Android's encrypted broker and
    // the Go rebind identity fence recheck scope, source and durable overlap.
    fun validRefresh(root: String, video: String, audio: String): Boolean {
        val expected = origin(root) ?: return false
        return origin(video) == expected && origin(audio) == expected
    }
}
