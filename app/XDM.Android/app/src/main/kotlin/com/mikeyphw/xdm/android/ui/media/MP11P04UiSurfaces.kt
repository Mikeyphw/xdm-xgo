package com.mikeyphw.xdm.android

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp
import com.mikeyphw.xdm.android.engine.MP11LiveUiPolicy
import com.mikeyphw.xdm.android.engine.MP11P04Diagnostics
import com.mikeyphw.xdm.android.engine.MP11VerifiedLiveRecording
import com.mikeyphw.xdm.android.engine.MP11LiveLibraryReview
import com.mikeyphw.xdm.android.util.formatBytes

/** Stable selectors for the *production* composables exercised by androidTest. */
internal object MP11P04Tags {
    const val Controls = "mp11:p04:recording-controls"
    const val Stop = "mp11:p04:stop-save"
    const val Pause = "mp11:p04:pause"
    const val Resume = "mp11:p04:resume"
    const val Refresh = "mp11:p04:refresh"
    const val Discard = "mp11:p04:discard"
    const val RefreshDialog = "mp11:p04:refresh-dialog"
    const val Root = "mp11:p04:root-url"
    const val Video = "mp11:p04:video-url"
    const val Audio = "mp11:p04:audio-url"
    const val ConfirmRefresh = "mp11:p04:confirm-refresh"
    const val DiscardDialog = "mp11:p04:discard-dialog"
    const val ConfirmDiscard = "mp11:p04:confirm-discard"
    const val RecoveryDialog = "mp11:p04:recovery-dialog"
    const val RecoveryResume = "mp11:p04:recovery-resume"
    const val RecoveryDiscard = "mp11:p04:recovery-discard"
    const val VerifiedTile = "mp11:p04:verified-live-tile"
    const val OpenVerified = "mp11:p04:open-verified"
    const val Details = "mp11:p04:verified-details"
    const val ReviewOnly = "mp11:p04:live-review-only"
}

/** This is the actual Go-projected recording control UI, not a test fixture.
 * The callbacks can only submit requests; none mark media complete.
 */
@Composable
internal fun MP11P04RecordingControls(
    state: String?, durableFragments: Int, partialReview: Boolean,
    dvrCapable: Boolean, onAction: (String) -> Unit,
) {
    val allowed = MP11LiveUiPolicy.actions(state, dvrCapable)
    Column(
        Modifier.testTag(MP11P04Tags.Controls).heightIn(max = 420.dp)
            .verticalScroll(rememberScrollState()),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Text("Session: ${MP11P04Diagnostics.stateLabel(state)}")
        Text("Verified staged fragments: ${MP11P04Diagnostics.stagedFragments(durableFragments)}. This is not a completed file.")
        if (partialReview) Text("Partial capture detected. Stop & Save requires independent verification.")
        if ("stop_save" in allowed) Button(
            onClick = { onAction("stop_save") }, modifier = Modifier.testTag(MP11P04Tags.Stop),
        ) { Text("Stop & Save") }
        if ("pause" in allowed) TextButton(
            onClick = { onAction("pause") }, modifier = Modifier.testTag(MP11P04Tags.Pause),
        ) { Text("Pause (DVR)") }
        if ("resume" in allowed) TextButton(
            onClick = { onAction("resume") }, modifier = Modifier.testTag(MP11P04Tags.Resume),
        ) { Text("Resume") }
        if ("refresh" in allowed) Button(
            onClick = { onAction("refresh") }, modifier = Modifier.testTag(MP11P04Tags.Refresh),
        ) { Text("Reauthorize source") }
        if ("discard" in allowed) TextButton(
            onClick = { onAction("discard") }, modifier = Modifier.testTag(MP11P04Tags.Discard),
        ) { Text("Discard captured fragments…") }
        if (allowed.isEmpty()) Text("No controls available. Inspect interrupted recording for recovery.")
    }
}

/** URLs exist only in the caller's transient Compose state and encrypted handoff.
 * This form never writes or logs a URL; the service and Go reverify everything.
 */
@Composable
internal fun MP11P04RefreshDialog(
    root: String, video: String, audio: String,
    onRoot: (String) -> Unit, onVideo: (String) -> Unit, onAudio: (String) -> Unit,
    onApprove: () -> Unit, onDismiss: () -> Unit,
) {
    AlertDialog(
        modifier = Modifier.testTag(MP11P04Tags.RefreshDialog),
        onDismissRequest = onDismiss,
        title = { Text("Reauthorize live source") },
        text = {
            Column(Modifier.heightIn(max = 420.dp).verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("Paste newly authorized URLs for this same recording. Go verifies the stored fragments and timeline before resuming.")
                OutlinedTextField(root, onRoot, label = { Text("Refreshed root manifest URL") },
                    singleLine = true, modifier = Modifier.testTag(MP11P04Tags.Root))
                OutlinedTextField(video, onVideo, label = { Text("Selected video playlist / MPD URL") },
                    singleLine = true, modifier = Modifier.testTag(MP11P04Tags.Video))
                OutlinedTextField(audio, onAudio, label = { Text("Selected audio playlist / MPD URL") },
                    singleLine = true, modifier = Modifier.testTag(MP11P04Tags.Audio))
                Text("The request requires an interrupted session. Sources needing new cookies or headers must be recaptured in Live locator. A refused refresh never deletes recorded bytes.")
            }
        },
        confirmButton = {
            Button(onClick = onApprove,
                enabled = MP11LiveUiPolicy.validRefresh(root, video, audio),
                modifier = Modifier.testTag(MP11P04Tags.ConfirmRefresh),
            ) { Text("Verify & reauthorize") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}

@Composable
internal fun MP11P04DiscardDialog(onConfirm: () -> Unit, onKeep: () -> Unit) {
    AlertDialog(
        modifier = Modifier.testTag(MP11P04Tags.DiscardDialog),
        onDismissRequest = onKeep,
        title = { Text("Discard live recording?") },
        text = { Text("This explicitly requests verified deletion of this capture's staged fragments. It cannot be undone. Publication is never implied.") },
        confirmButton = { Button(onClick = onConfirm,
            modifier = Modifier.testTag(MP11P04Tags.ConfirmDiscard)) { Text("Request discard") } },
        dismissButton = { TextButton(onClick = onKeep) { Text("Keep fragments") } },
    )
}

@Composable
internal fun MP11P04RecoveryDialog(
    state: String, fragments: Int,
    onDiscard: () -> Unit, onResume: () -> Unit, onKeep: () -> Unit,
    resumeLabel: String = "Reauthorize & resume",
) {
    val n = MP11P04Diagnostics.stagedFragments(fragments)
    val publishing = state == "publication_pending_review"
    val canResume = state == "recovery_review_required" && n > 0
    val description = when (state) {
        "publication_pending_review" -> "Publication was interrupted. $n fragments remain; playback status must be reviewed. Resuming is blocked."
        "published_cleanup_pending" -> "Recording was published. $n transient fragments may remain for explicit cleanup; resuming is blocked."
        "empty_session_review_required" -> "This session has no committed media. Explicitly discard the journal or keep it for review."
        "inventory_unavailable_review" -> "The fragment inventory is damaged or unreadable. Resuming and playback are blocked; cleanup requires independent verification."
        "journal_missing_review_required" -> "$n fragments lack a verified session journal. Resuming is blocked."
        "recovery_review_required" -> "$n fragments remain. Fresh authorization and complete readback are required to resume."
        else -> "Recovery status could not be verified. Keep this capture for review."
    }
    AlertDialog(
        modifier = Modifier.testTag(MP11P04Tags.RecoveryDialog),
        onDismissRequest = onKeep,
        title = { Text("Review interrupted recording") },
        text = { Text(description) },
        confirmButton = {
            if (!publishing && state in setOf("recovery_review_required", "published_cleanup_pending",
                    "empty_session_review_required", "inventory_unavailable_review", "journal_missing_review_required"))
                TextButton(onClick = onDiscard, modifier = Modifier.testTag(MP11P04Tags.RecoveryDiscard)) {
                    Text("Discard fragments")
                }
        },
        dismissButton = {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                if (canResume) TextButton(onClick = onResume,
                    modifier = Modifier.testTag(MP11P04Tags.RecoveryResume)) { Text(resumeLabel) }
                TextButton(onClick = onKeep) { Text("Keep") }
            }
        },
    )
}

/** A verified library item is constructed only by the MP08+MP09 readback index.
 * This UI never grants completed status on its own.
 */
@Composable
internal fun MP11P04VerifiedLiveTile(
    item: MP11VerifiedLiveRecording, onOpen: () -> Unit, onDetails: () -> Unit,
) {
    XdmListCard {
        Column(Modifier.width(250.dp).padding(12.dp).testTag(MP11P04Tags.VerifiedTile),
            verticalArrangement = Arrangement.spacedBy(7.dp)) {
            XdmCardTitle(item.title, maxLines = 2)
            XdmMetadataText("${item.bytes.formatBytes()} • MP4")
            XdmSupportingText(if (item.cleanupPending)
                "Published and playable; temporary cleanup needs review"
                else "Published and playable; cleanup verified", maxLines = 2)
            XdmActionFlowRow {
                Button(onClick = onOpen, modifier = Modifier.testTag(MP11P04Tags.OpenVerified)) {
                    Text("Open")
                }
                TextButton(onClick = onDetails, modifier = Modifier.testTag(MP11P04Tags.Details)) {
                    Text("Details")
                }
            }
        }
    }
}

@Composable
internal fun MP11P04ReviewOnlyRow(item: MP11LiveLibraryReview) {
    Column(Modifier.testTag(MP11P04Tags.ReviewOnly)) {
        XdmSupportingText("${item.title}: ${item.reason}", maxLines = 3)
    }
}
