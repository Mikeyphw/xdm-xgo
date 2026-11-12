package com.mikeyphw.xdm.android.engine

/**
 * Process-local MP09 foreground-service control gate. This does not persist
 * authority or publication; Go and the session journal remain authoritative.
 * Every transition and the notification's allowed actions use the same state.
 */
internal class AndroidMP09RecordingLifecycleState {
    enum class Phase { New, Starting, Recording, Pausing, Paused, Resuming, Saving, Discarding, Review, Saved, Discarded }
    enum class Control { Pause, Resume, StopSave, Discard }
    private var current = Phase.New

    @Synchronized fun phase(): Phase = current

    @Synchronized fun beginStart(): Boolean {
        if (current != Phase.New) return false
        current = Phase.Starting
        return true
    }

    @Synchronized fun started(): Boolean {
        if (current != Phase.Starting) return false
        current = Phase.Recording
        return true
    }

    @Synchronized fun startFailed(): Boolean {
        if (current != Phase.Starting) return false
        current = Phase.Review
        return true
    }

    @Synchronized fun interrupted(): Boolean {
        if (current in setOf(Phase.Saved, Phase.Discarded)) return false
        current = Phase.Review
        return true
    }

    @Synchronized fun canPoll(): Boolean = current == Phase.Recording

    @Synchronized fun begin(action: Control, dvrVerified: Boolean): Boolean {
        val next = when (action) {
            Control.Pause -> if (dvrVerified && current == Phase.Recording) Phase.Pausing else null
            Control.Resume -> if (dvrVerified && current == Phase.Paused) Phase.Resuming else null
            Control.StopSave -> if (current in setOf(Phase.Recording, Phase.Paused, Phase.Review)) Phase.Saving else null
            Control.Discard -> if (current in setOf(Phase.Recording, Phase.Paused, Phase.Review)) Phase.Discarding else null
        } ?: return false
        current = next
        return true
    }

    /** Caller MUST independently check Go's status/receipt; success here never
     * means the media is playable without the Go/MP08 verified result. */
    @Synchronized fun complete(action: Control, acceptedByGo: Boolean): Phase {
        val expected = when (action) {
            Control.Pause -> Phase.Pausing
            Control.Resume -> Phase.Resuming
            Control.StopSave -> Phase.Saving
            Control.Discard -> Phase.Discarding
        }
        // Android can destroy/timeout the service while the Go response is
        // in flight. A late callback cannot override that interruption and
        // must never claim a verified publication from an expired service.
        if (current != expected) return current
        current = when (action) {
            Control.Pause -> if (acceptedByGo) Phase.Paused else Phase.Recording
            Control.Resume -> if (acceptedByGo) Phase.Recording else Phase.Paused
            Control.StopSave -> if (acceptedByGo) Phase.Saved else Phase.Review
            Control.Discard -> if (acceptedByGo) Phase.Discarded else Phase.Review
        }
        return current
    }

    @Synchronized fun available(dvrVerified: Boolean): Set<Control> = when (current) {
        Phase.Recording -> setOf(Control.StopSave, Control.Discard) +
            if (dvrVerified) setOf(Control.Pause) else emptySet()
        Phase.Paused -> setOf(Control.StopSave, Control.Discard) +
            if (dvrVerified) setOf(Control.Resume) else emptySet()
        Phase.Review -> setOf(Control.StopSave, Control.Discard)
        else -> emptySet()
    }
}
