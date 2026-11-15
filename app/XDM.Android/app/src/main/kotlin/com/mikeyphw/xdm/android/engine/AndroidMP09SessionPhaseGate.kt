package com.mikeyphw.xdm.android.engine

/** Credential-free, monotonic MP09 publication and deletion policy.
 * A published_clean tombstone is retained after verified cleanup so that a
 * restarted recording cannot mistake absence of parts for absence of history.
 */
internal object AndroidMP09SessionPhaseGate {
    fun mayResume(phase: String): Boolean = phase == "recording"
    fun mayTransition(current: String, next: String): Boolean = when (current) {
        "recording" -> next == "recording" || next == "publishing"
        "publishing" -> next == "publishing" || next == "published"
        "published" -> next == "published" || next == "published_clean"
        "published_clean" -> next == "published_clean"
        else -> false
    }
    fun mayDiscard(phase: String): Boolean = phase in setOf("missing", "recording", "published", "published_clean")
    /** No implicit restart after a crash. Only a user-confirmed new session,
     * with a different destination and no retained fragments, can retire an
     * already-clean publication fence. In-flight publishing never qualifies. */
    fun mayStartAfterTerminal(previous: String, explicitNewStart: Boolean,
        verifiedEmptyInventory: Boolean, destinationIsValid: Boolean): Boolean =
        previous == "published_clean" && explicitNewStart && verifiedEmptyInventory && destinationIsValid
    fun afterVerifiedDiscard(phase: String): String = when (phase) {
        "recording", "missing" -> "missing" // only explicit discard retires un-published session
        "published", "published_clean" -> "published_clean" // permanent anti-replay tombstone
        else -> error("publication review required")
    }
}
