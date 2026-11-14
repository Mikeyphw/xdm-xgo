package com.mikeyphw.xdm.android.engine

/** Bounded diagnostic taxonomy for UI/receipt presentation. Never accepts
 * URL, capture title, header, cookie, URI, exception text or token as input.
 * It is not an authorization, publication or recovery oracle.
 */
internal object MP11P04Diagnostics {
    enum class Area { Recording, Refresh, Recovery, Library }
    enum class Outcome { Requested, Unavailable, Refused, VerificationRequired, Verified }

    fun code(area: Area, outcome: Outcome): String =
        "MP11_P04_${area.name.uppercase()}_${outcome.name.uppercase()}"

    /** Only known non-sensitive Go states enter display labels. Unrecognized
     * server data is deliberately classified without interpolating its value.
     */
    fun stateLabel(raw: String?): String = when (raw) {
        "capturing" -> "Recording"
        "recoverable" -> "Recoverable"
        "paused" -> "Paused"
        "refresh_required" -> "Authorization required"
        "stop_pending_verification" -> "Waiting for verification"
        else -> "Review required"
    }

    fun stagedFragments(count: Int): Int = count.coerceIn(0, 4096)
}
