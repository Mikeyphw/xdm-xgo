package com.mikeyphw.xdm.android

import android.content.ActivityNotFoundException
import android.content.Intent
import android.net.Uri
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.FilterChip
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import com.mikeyphw.xdm.android.engine.AndroidMediaUiClient
import com.mikeyphw.xdm.android.engine.AndroidMediaUiCommandResult
import com.mikeyphw.xdm.android.engine.AndroidLiveRecordingService
import com.mikeyphw.xdm.android.engine.AndroidLiveSelectionGate
import com.mikeyphw.xdm.android.engine.ManifestSelectionV1Contract
import com.mikeyphw.xdm.android.media.MediaBatchInputParser
import com.mikeyphw.xdm.android.media.MediaBatchUrlDisposition
import com.mikeyphw.xdm.android.media.MediaConsumerWorkspacePlanner
import com.mikeyphw.xdm.android.media.MediaTrackSelection
import com.mikeyphw.xdm.android.ffmpeg.EmbeddedFfmpegJobProgress
import com.mikeyphw.xdm.android.model.Download
import com.mikeyphw.xdm.android.model.DownloadState
import com.mikeyphw.xdm.android.model.BrowserCaptureSessionSummary
import com.mikeyphw.xdm.android.model.MediaCaptureRecord
import com.mikeyphw.xdm.android.model.MediaCaptureStatus
import com.mikeyphw.xdm.android.model.MediaOutputAdmissionMode
import com.mikeyphw.xdm.android.model.MediaOutputRecord
import com.mikeyphw.xdm.android.model.MediaOutputState
import com.mikeyphw.xdm.android.model.MediaVariant
import com.mikeyphw.xdm.android.model.MediaVariantKind
import com.mikeyphw.xdm.android.util.formatBytes
import com.mikeyphw.xdm.android.util.formatSpeed
import kotlinx.coroutines.launch

@Composable
@UiSurface(UiAudience.User, "Review captured media and choose downloadable tracks")
fun MediaInboxScreen(
    captures: List<MediaCaptureRecord>,
    variants: List<MediaVariant>,
    mediaTrackSelections: Map<String, MediaTrackSelection>,
    downloads: List<Download>,
    outputs: List<MediaOutputRecord>,
    embeddedFfmpegProgress: Map<String, EmbeddedFfmpegJobProgress>,
    mediaOutputAdmissionsInFlight: Set<String>,
    intakeFeedback: MediaIntakeFeedbackUi,
    browserCaptureSessions: List<BrowserCaptureSessionSummary>,
    onPastePageUrl: (String) -> Unit,
    onBatchInput: (String) -> Unit,
    onDownload: (MediaCaptureRecord, MediaTrackSelection, MediaOutputAdmissionMode) -> Unit,
    onResumeOrRetryDownload: (Download) -> Unit,
    onCancelDownload: (Download) -> Unit,
    onCancelEmbeddedFfmpeg: (MediaOutputRecord) -> Unit,
    onOpenDownload: (Download) -> Unit,
    onResolve: (MediaCaptureRecord) -> Unit,
    onSelectVariant: (MediaCaptureRecord, String) -> Unit,
    onTrackSelectionChanged: (MediaCaptureRecord, MediaTrackSelection) -> Unit,
    onRemove: (MediaCaptureRecord) -> Unit,
) {
    val consumerPlanner = remember { MediaConsumerWorkspacePlanner() }
    val context = LocalContext.current
    val goManifestClient = remember(context.applicationContext) { AndroidMediaUiClient(context.applicationContext) }
    val inspectScope = rememberCoroutineScope()
    var inspectingManifest by remember { mutableStateOf<String?>(null) }
    var manifestReview by remember { mutableStateOf<AndroidMediaUiCommandResult?>(null) }
    var manifestChoice by remember { mutableStateOf(ManifestSelectionV1Contract.Request()) }
    var liveFeedback by remember { mutableStateOf<String?>(null) }
    var recoveryCaptureId by remember { mutableStateOf<String?>(null) }
    var recoveryFragments by remember { mutableStateOf(0) }
    var userSelectedResumeCaptureId by remember { mutableStateOf<String?>(null) }
    var recoveryReviewState by remember { mutableStateOf("recovery_review_required") }
    val onInspectGoManifest: (MediaCaptureRecord) -> Unit = { capture ->
        if (inspectingManifest == null) {
            inspectingManifest = capture.id
            manifestReview = null
            manifestChoice = ManifestSelectionV1Contract.Request()
            inspectScope.launch {
                manifestReview = runCatching { goManifestClient.resolveManifest(capture.id) }
                    .getOrElse { AndroidMediaUiCommandResult("", "resolve_manifest", false,
                        errorCode = "manifest_inspection_unavailable") }
                inspectingManifest = null
            }
        }
    }
    // A fresh revision-bound Go manifest is required immediately before every
    // user-initiated foreground recording. No signed URL is saved to UI state.
    val onStartLive: () -> Unit = start@{
        val reviewed = manifestReview ?: return@start
        val id = reviewed.captureId ?: return@start
        val revision = reviewed.manifestRevision ?: return@start
        if (inspectingManifest != null) return@start
        val requested = manifestChoice
        inspectingManifest = id
        inspectScope.launch {
            try {
                val fresh = goManifestClient.resolveManifest(id, requested, revision)
                val selectedPlan = requireNotNull(fresh.manifestSelectionPlan)
                // MP03 option IDs are synthetic: only Go may map them to raw
                // MPD Representation IDs with a fresh, origin-checked fetch.
                val dashBound = if (fresh.manifestGraph?.protocol == "dash") {
                    goManifestClient.liveBindDash(id, revision,
                        requireNotNull(selectedPlan.videoId), requireNotNull(selectedPlan.audioId))
                } else null
                val selection = AndroidLiveSelectionGate.fromFreshManifest(id, revision, requested, fresh, dashBound)
                val destination = "live_" + java.util.UUID.randomUUID().toString().replace("-", "")
                val intent = Intent(context, AndroidLiveRecordingService::class.java).apply {
                    action = AndroidLiveRecordingService.START
                    putExtra(AndroidLiveRecordingService.CAPTURE, id)
                    putExtra(AndroidLiveRecordingService.DESTINATION, destination)
                    putExtra(AndroidLiveRecordingService.PROTOCOL, selection.protocol)
                    putExtra(AndroidLiveRecordingService.VIDEO, selection.videoUrl)
                    putExtra(AndroidLiveRecordingService.AUDIO, selection.audioUrl)
                    putExtra(AndroidLiveRecordingService.VIDEO_REP, selection.videoRepresentationId)
                    putExtra(AndroidLiveRecordingService.AUDIO_REP, selection.audioRepresentationId)
                    putExtra(AndroidLiveRecordingService.REQUIRE_AUDIO, selection.requireAudio)
                    putExtra(AndroidLiveRecordingService.VIDEO_OPTION, selectedPlan.videoId.orEmpty())
                    putExtra(AndroidLiveRecordingService.AUDIO_OPTION, selectedPlan.audioId.orEmpty())
                    putExtra(AndroidLiveRecordingService.EXPECTED_REVISION, revision)
                    putExtra(AndroidLiveRecordingService.RECOVER_INTERRUPTED,
                        userSelectedResumeCaptureId == id)
                }
                AndroidLiveRecordingService.start(context, intent)
                manifestReview = null
                liveFeedback = if (userSelectedResumeCaptureId == id)
                    "Verified recovery requested. Source and every stored fragment must match; no automatic completion."
                else "Live recording requested. Controls are in the foreground notification."
                userSelectedResumeCaptureId = null
            } catch (_: Exception) {
                liveFeedback = "Recording not started. Refresh the authorized live HLS/DASH manifest, verify separate audio and MP4, and review any interrupted fragments."
            } finally { inspectingManifest = null }
        }
    }
    val onReviewInterrupted: (MediaCaptureRecord) -> Unit = review@{ capture ->
        if (inspectingManifest != null) return@review
        inspectingManifest = capture.id
        inspectScope.launch {
            try {
                val result = goManifestClient.liveAction(capture.id, "inspect_recovery")
                if (!result.ok) {
                    // An unreadable fragment cannot be verified or resumed, but
                    // a separately confirmed, capture-scoped discard may still
                    // be allowed by the durable store's publication guard.
                    recoveryCaptureId = capture.id
                    recoveryFragments = 0
                    recoveryReviewState = "inventory_unavailable_review"
                }
                else if (result.status == "recording_active") liveFeedback = "This capture is currently recording; use its notification controls."
                else if (result.status == "published_cleanup_verified")
                    liveFeedback = "This recording was already published and its temporary fragment cleanup is verified."
                else if (result.recoveryFragments == 0 && result.status !in setOf("publication_pending_review", "published_cleanup_pending", "empty_session_review_required"))
                    liveFeedback = "No interrupted recording fragments found for this capture."
                else {
                    recoveryCaptureId = capture.id
                    recoveryFragments = result.recoveryFragments
                    recoveryReviewState = result.status.orEmpty()
                }
            } catch (_: Exception) { liveFeedback = "Recovery review unavailable; no files were changed." }
            finally { inspectingManifest = null }
        }
    }
    var batchText by rememberSaveable { mutableStateOf("") }
    var batchFeedback by remember { mutableStateOf<String?>(null) }
    var pageUrlText by rememberSaveable { mutableStateOf("") }
    var mediaToolsExpanded by rememberSaveable { mutableStateOf(false) }
    val downloadsById = remember(downloads) { downloads.associateBy(Download::id) }
    val latestOutputsByCaptureId = remember(outputs) {
        outputs.filter { it.state != MediaOutputState.Hidden }
            .groupBy { it.captureId }
            .mapValues { (_, records) ->
                records.filter { it.state in setOf(MediaOutputState.Active, MediaOutputState.Queued) }
                    .maxByOrNull { it.updatedAtEpochMs }
                    ?: records.filter { it.state == MediaOutputState.Completed && !it.completedArtifactUri.isNullOrBlank() }
                        .maxByOrNull { it.updatedAtEpochMs }
                    ?: records.maxByOrNull { it.updatedAtEpochMs }
            }
    }
    val reviewableCaptures = remember(captures) {
        // DownloadCreated records remain reviewable: one capture may intentionally produce multiple
        // output records/generations with different track selections or destinations.
        captures.filter { it.status != MediaCaptureStatus.Archived }.sortedByDescending(MediaCaptureRecord::updatedAtEpochMs)
    }
    val capturesById = remember(reviewableCaptures) { reviewableCaptures.associateBy(MediaCaptureRecord::id) }
    val activeBrowserSessions = remember(browserCaptureSessions, capturesById) {
        browserCaptureSessions.mapNotNull { session ->
            val candidates = session.candidates.filter { it.captureId in capturesById }
            session.copy(candidates = candidates, importedCandidateCount = candidates.size).takeIf { candidates.isNotEmpty() }
        }
    }
    val browserGroupedCaptureIds = remember(activeBrowserSessions) { activeBrowserSessions.flatMap { it.captureIds }.toSet() }
    val ungroupedCaptures = remember(reviewableCaptures, browserGroupedCaptureIds) {
        reviewableCaptures.filterNot { it.id in browserGroupedCaptureIds }
    }
    val recentlyQueued = remember(captures, downloadsById) {
        captures.mapNotNull { capture ->
            capture.downloadId?.let(downloadsById::get)?.let { capture to it }
        }.sortedByDescending { (_, download) -> download.updatedAtEpochMs }.take(5)
    }

    Column(Modifier.fillMaxSize().xdmScreen(XdmScreenTags.Media, "Media")) {
        val intro = "Direct media downloads in one tap. Playlists show quality and track choices when they exist."
        if (LocalXdmWindowClass.current == XdmWindowClass.Expanded) {
            XdmPageHeader(title = "Media", subtitle = intro)
        } else {
            XdmPageIntro(intro)
        }
        LazyColumn(
            modifier = Modifier.fillMaxWidth().weight(1f),
            contentPadding = PaddingValues(horizontal = 16.dp, vertical = 4.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            item {
                XdmGroupedList {
                    Column(Modifier.fillMaxWidth().padding(14.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                        XdmSectionLabel("Find media")
                        OutlinedTextField(
                            value = pageUrlText,
                            onValueChange = { pageUrlText = it },
                            label = { Text("Page or media URL") },
                            placeholder = { Text("https://site.example/watch/episode") },
                            modifier = Modifier.fillMaxWidth(),
                            singleLine = true,
                        )
                        XdmActionFlowRow {
                            Button(onClick = { onPastePageUrl(pageUrlText) }, enabled = pageUrlText.isNotBlank()) { Text("Check URL") }
                            Button(onClick = { context.startActivity(MediaLocatorActivity.intent(context, pageUrlText)) }) { Text("Live locator") }
                            TextButton(onClick = { mediaToolsExpanded = !mediaToolsExpanded }) {
                                Text(if (mediaToolsExpanded) "Hide tools" else "More tools")
                            }
                        }
                        XdmMetadataText("Captured browser context is used when needed and stays private.")
                    }
                }
            }

            if (intakeFeedback.visible) {
                item {
                    XdmGroupedList {
                        Column(Modifier.fillMaxWidth().padding(14.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                            XdmSectionLabel(intakeFeedback.title.ifBlank { "Media intake" })
                            Text(intakeFeedback.detail)
                            if (intakeFeedback.diagnostics.isNotEmpty()) {
                                XdmTechnicalDetails(label = "Technical details") {
                                    intakeFeedback.diagnostics.take(6).forEach { diagnostic ->
                                        XdmTechnicalText(diagnostic)
                                    }
                                }
                            }
                            when (intakeFeedback.kind) {
                                MediaIntakeFeedbackKind.Working -> XdmStatusBadge("Running", tone = XdmStatusTone.Info)
                                MediaIntakeFeedbackKind.Found -> XdmStatusBadge("Ready", tone = XdmStatusTone.Success)
                                MediaIntakeFeedbackKind.NeedsBrowserCapture,
                                MediaIntakeFeedbackKind.AuthenticationRequired,
                                MediaIntakeFeedbackKind.Unsupported -> XdmStatusBadge("Needs action", tone = XdmStatusTone.Warning)
                                MediaIntakeFeedbackKind.Failed -> XdmStatusBadge("Failed", tone = XdmStatusTone.Error)
                                MediaIntakeFeedbackKind.NoMediaFound -> XdmStatusBadge("Completed", tone = XdmStatusTone.Neutral)
                                MediaIntakeFeedbackKind.Idle -> Unit
                            }
                        }
                    }
                }
            }

            item {
                AnimatedVisibility(mediaToolsExpanded) {
                    MediaBatchInputPanel(
                        text = batchText,
                        feedback = batchFeedback,
                        onTextChanged = {
                            batchText = it
                            batchFeedback = null
                        },
                        onInspectAll = {
                            val trimmed = batchText.trim()
                            if (trimmed.isNotEmpty()) {
                                onBatchInput(trimmed)
                                batchFeedback = "Batch sent for media inspection."
                            }
                        },
                        onClearInvalid = {
                            batchText = batchText.lines()
                                .filter { line -> line.contains("http://", ignoreCase = true) || line.contains("https://", ignoreCase = true) }
                                .joinToString("\n")
                            batchFeedback = "Removed lines without supported HTTP(S) URLs."
                        },
                        onCopyRejectedLines = {
                            val rejected = MediaBatchInputParser().parse(batchText).rejectedLinesText
                            if (rejected.isNotBlank()) {
                                copyTextToClipboard(context, "XDM rejected media batch lines", rejected)
                                batchFeedback = "Rejected lines copied."
                            } else {
                                batchFeedback = "No rejected lines to copy."
                            }
                        },
                        onAddSelected = { selectedText ->
                            onBatchInput(selectedText)
                            batchFeedback = "Selected links sent for media inspection."
                        },
                    )
                }
            }

            if (reviewableCaptures.isEmpty()) {
                item {
                    XdmEmptyState(
                        title = if (captures.isEmpty()) "No captured media" else "Everything is already handled",
                        description = if (captures.isEmpty()) {
                            "Open Live locator, paste a media link, or share media from your browser."
                        } else {
                            "New captures will appear here when you inspect or share another media link."
                        },
                        actionLabel = "Open Live locator",
                        onAction = { context.startActivity(MediaLocatorActivity.intent(context, pageUrlText)) },
                    )
                }
            } else {
                if (activeBrowserSessions.isNotEmpty()) {
                    item { XdmSectionLabel("From Firefox") }
                    activeBrowserSessions.forEach { session ->
                        item(key = "browser-session:${session.sessionId}") {
                            BrowserCaptureSessionHeader(session)
                        }
                        val sessionCaptures = session.candidates.mapNotNull { capturesById[it.captureId] }
                        items(sessionCaptures, key = { capture -> "${session.sessionId}:${capture.id}" }) { capture ->
                            val captureVariants = variants.filter { it.captureId == capture.id }.sortedBy { it.position }
                            MediaCaptureCard(
                                capture = capture,
                                captureVariants = captureVariants,
                                persistedSelection = mediaTrackSelections[capture.id]
                                    ?: MediaTrackSelection(videoVariantId = capture.selectedVariantId),
                                consumerPlanner = consumerPlanner,
                                latestOutput = latestOutputsByCaptureId[capture.id],
                                embeddedFfmpegProgress = latestOutputsByCaptureId[capture.id]?.ownerId?.let(embeddedFfmpegProgress::get),
                                downloadInFlight = capture.id in mediaOutputAdmissionsInFlight,
                                onDownload = onDownload,
                                onOpenOutput = { output -> openMediaOutput(context, output) },
                                onCancelEmbeddedFfmpeg = onCancelEmbeddedFfmpeg,
                                onResolve = onResolve,
                                onInspectManifest = onInspectGoManifest,
                                onReviewInterrupted = onReviewInterrupted,
                                onSelectVariant = onSelectVariant,
                                onTrackSelectionChanged = onTrackSelectionChanged,
                                onRemove = onRemove,
                            )
                        }
                    }
                }
                if (ungroupedCaptures.isNotEmpty()) {
                    item { XdmSectionLabel(if (activeBrowserSessions.isEmpty()) "Captured media" else "Other captured media") }
                    items(ungroupedCaptures, key = MediaCaptureRecord::id) { capture ->
                        val captureVariants = variants.filter { it.captureId == capture.id }.sortedBy { it.position }
                        MediaCaptureCard(
                            capture = capture,
                            captureVariants = captureVariants,
                            persistedSelection = mediaTrackSelections[capture.id]
                                ?: MediaTrackSelection(videoVariantId = capture.selectedVariantId),
                            consumerPlanner = consumerPlanner,
                            latestOutput = latestOutputsByCaptureId[capture.id],
                            embeddedFfmpegProgress = latestOutputsByCaptureId[capture.id]?.ownerId?.let(embeddedFfmpegProgress::get),
                            downloadInFlight = capture.id in mediaOutputAdmissionsInFlight,
                            onDownload = onDownload,
                            onOpenOutput = { output -> openMediaOutput(context, output) },
                            onCancelEmbeddedFfmpeg = onCancelEmbeddedFfmpeg,
                            onResolve = onResolve,
                            onInspectManifest = onInspectGoManifest,
                            onReviewInterrupted = onReviewInterrupted,
                            onSelectVariant = onSelectVariant,
                            onTrackSelectionChanged = onTrackSelectionChanged,
                            onRemove = onRemove,
                        )
                    }
                }
            }

            if (recentlyQueued.isNotEmpty()) {
                item { XdmSectionLabel("Recently queued") }
                item {
                    XdmGroupedList {
                        recentlyQueued.forEachIndexed { index, (capture, download) ->
                            RecentlyQueuedMediaRow(
                                title = capture.title.ifBlank { download.fileName },
                                download = download,
                                thumbnailUrl = capture.thumbnailUrl ?: variants.firstOrNull { it.captureId == capture.id && it.kind == MediaVariantKind.Thumbnail }?.url,
                                sourceUrl = capture.sourceUrl,
                                onResumeOrRetry = { onResumeOrRetryDownload(download) },
                                onCancel = { onCancelDownload(download) },
                                onManage = { onOpenDownload(download) },
                            )
                            if (index != recentlyQueued.lastIndex) XdmListSeparator()
                        }
                    }
                }
            }
        }
    }
    manifestReview?.let { result ->
        Mp03ManifestReviewDialog(
            result = result,
            selection = manifestChoice,
            onSelectionChange = { next ->
                manifestChoice = next
                // Any user change invalidates the previous Go plan before resubmission.
                manifestReview = manifestReview?.copy(manifestSelectionPlan = null)
            },
            onVerify = {
                val captureId = manifestReview?.captureId
                val revision = manifestReview?.manifestRevision
                if (captureId != null && revision != null && inspectingManifest == null) {
                    inspectingManifest = captureId
                    manifestReview = null
                    inspectScope.launch {
                        manifestReview = runCatching {
                            goManifestClient.resolveManifest(captureId, manifestChoice, revision)
                        }.getOrElse { AndroidMediaUiCommandResult("", "resolve_manifest", false,
                            errorCode = "selection_inspection_unavailable") }
                        inspectingManifest = null
                    }
                }
            },
            onClose = { manifestReview = null },
            onStartLive = onStartLive,
        )
    }
    liveFeedback?.let { message ->
        AlertDialog(onDismissRequest = { liveFeedback = null },
            title = { Text("Live recording") }, text = { Text(message) },
            confirmButton = { TextButton(onClick = { liveFeedback = null }) { Text("OK") } })
    }
    recoveryCaptureId?.let { id ->
        AlertDialog(onDismissRequest = { recoveryCaptureId = null },
            title = { Text("Review interrupted recording") },
            text = { Text(when (recoveryReviewState) {
                "publication_pending_review" -> "Publication was interrupted. $recoveryFragments stored fragments remain; playback status must be reviewed before any new recording. Resuming is blocked."
                "published_cleanup_pending" -> "Recording was published before interruption. $recoveryFragments transient fragments may remain for explicit cleanup; resuming is blocked."
                "empty_session_review_required" -> "This interrupted session has no committed media. You can explicitly discard its session journal or keep it for review."
                "inventory_unavailable_review" -> "The local fragment inventory is unreadable or damaged. The recording cannot be resumed or considered saved. You may explicitly request capture-scoped removal; suspicious files or ambiguous publication will still be refused."
                "journal_missing_review_required" -> "Stored fragments lack a verified session journal. $recoveryFragments fragments require review or explicit discard; resuming is blocked."
                else -> "$recoveryFragments stored fragments remain. A fresh authorized source and complete readback are required before resuming."
            }) },
            confirmButton = {
                if (recoveryReviewState != "publication_pending_review") TextButton(onClick = {
                    recoveryCaptureId = null
                inspectScope.launch {
                    val result = runCatching { goManifestClient.liveAction(id, "discard_recovery") }.getOrNull()
                    liveFeedback = if (result?.ok == true && result.status == "discarded_verified")
                        "Interrupted fragments were removed and verified." else
                        "Cleanup was not confirmed; stored fragments were not marked removed."
                }
                }) { Text("Discard fragments") }
            },
            dismissButton = {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    if (recoveryReviewState == "recovery_review_required" && recoveryFragments > 0) TextButton(onClick = {
                        recoveryCaptureId = null
                        val capture = capturesById[id]
                        if (capture != null) {
                            userSelectedResumeCaptureId = id
                            onInspectGoManifest(capture)
                        } else liveFeedback = "Original capture not found; refresh the authorized source."
                    }) { Text("Reauthorize & resume") }
                    TextButton(onClick = { recoveryCaptureId = null }) { Text("Keep") }
                }
            })
    }
    if (inspectingManifest != null) {
        AlertDialog(
            onDismissRequest = {},
            title = { Text("Inspecting manifest") },
            text = { Text("Resolving HLS/DASH qualities and tracks with the authorized Android session…") },
            confirmButton = {},
        )
    }
}

@Composable
private fun Mp03ManifestReviewDialog(
    result: AndroidMediaUiCommandResult,
    selection: ManifestSelectionV1Contract.Request,
    onSelectionChange: (ManifestSelectionV1Contract.Request) -> Unit,
    onVerify: () -> Unit,
    onClose: () -> Unit,
    onStartLive: () -> Unit,
) {
    val graph = result.manifestGraph
    val plan = result.manifestSelectionPlan
    AlertDialog(
        onDismissRequest = onClose,
        title = { Text("Manifest tracks & output review") },
        text = {
            LazyColumn(
                modifier = Modifier.heightIn(max = 460.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                if (graph == null) {
                    item { Text("Inspection unavailable: ${result.errorCode ?: "manifest_unavailable"}. Refresh the browser session and try again.") }
                } else {
                    item { Text("${graph.protocol.uppercase()} • ${graph.kind.uppercase()} • ${graph.periods.size} timeline groups") }
                    item { Text("${graph.qualities.size} qualities • ${graph.audioTracks.size} audio • ${graph.subtitleTracks.size} subtitles") }
                    if (graph.protectedMedia) item { Text("Protected media: diagnostic only. DRM is never bypassed.") }
                    item { Text("Download intent") }
                    item {
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            for (pair in (listOf("best_video" to "Video + audio", "video_only" to "Video only", "audio_only" to "Audio only") +
                                if (graph.kind in setOf("live", "event")) listOf("live_recording" to "Record live") else emptyList())) {
                                FilterChip(selected = selection.intent == pair.first,
                                    onClick = { onSelectionChange(selection.copy(intent = pair.first,
                                        videoId = if (pair.first == "audio_only") null else selection.videoId,
                                        audioId = if (pair.first == "video_only") null else selection.audioId,
                                        container = if (pair.first == "live_recording") "mp4" else selection.container,
                                        subtitlePolicy = if (pair.first == "live_recording") "disabled" else selection.subtitlePolicy,
                                        subtitleId = if (pair.first == "live_recording") null else selection.subtitleId)) },
                                    label = { Text(pair.second) })
                            }
                        }
                    }
                    if (selection.intent != "audio_only") {
                        item { Text("Video quality") }
                        items(graph.qualities, key = { "video:${it.id}" }) { quality ->
                            FilterChip(
                                selected = selection.videoId == quality.id || (selection.videoId == null && plan?.videoId == quality.id),
                                onClick = { onSelectionChange(selection.copy(videoId = quality.id, audioId = null, subtitleId = null)) },
                                label = { Text("${quality.width}×${quality.height} • ${quality.bandwidth / 1000} kb/s • ${quality.codecs.joinToString().take(44)}") },
                            )
                        }
                    }
                    if (selection.intent != "video_only") {
                        item { Text("Audio (same rendition group required)") }
                        items(graph.audioTracks, key = { "audio:${it.id}" }) { track ->
                            FilterChip(selected = selection.audioId == track.id || (selection.audioId == null && plan?.audioId == track.id),
                                onClick = { onSelectionChange(selection.copy(audioId = track.id)) },
                                label = { Text("${track.language.ifBlank { "Unknown" }} • ${if (track.default) "Default" else "Alternate"}") })
                        }
                    }
                    item {
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            FilterChip(selected = selection.subtitlePolicy == "optional", onClick = { onSelectionChange(selection.copy(subtitlePolicy = "optional", subtitleId = null)) }, label = { Text("Subtitles off") })
                            FilterChip(selected = selection.subtitlePolicy == "required", onClick = { onSelectionChange(selection.copy(subtitlePolicy = "required")) }, label = { Text("Require subtitles") })
                        }
                    }
                    if (selection.subtitlePolicy == "required") {
                        items(graph.subtitleTracks, key = { "subtitle:${it.id}" }) { track ->
                            FilterChip(selected = selection.subtitleId == track.id || (selection.subtitleId == null && plan?.subtitleId == track.id),
                                onClick = { onSelectionChange(selection.copy(subtitleId = track.id)) },
                                label = { Text("Subtitles • ${track.language.ifBlank { "Unknown" }}") })
                        }
                    }
                    item { Text("Output container") }
                    item {
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            for (c in listOf("auto", "mp4", "mkv", "webm")) {
                                FilterChip(selected = selection.container == c,
                                    onClick = { onSelectionChange(selection.copy(container = c)) },
                                    label = { Text(c.uppercase()) })
                            }
                        }
                    }
                    if (plan == null) {
                        item { Text("Not verified yet. Re-check exact IDs and signed manifest revision with Go.") }
                    } else {
                        item { Text("Go plan: ${plan.intent} • ${plan.container.uppercase()} • ${plan.status}") }
                        item { Text("Required streams: video=${plan.required.video}, audio=${plan.required.audio}, subtitles=${plan.required.subtitle}") }
                        if (plan.required.verifyEmbeddedAudio) item { Text("Audio presence is unproven; final FFprobe audio verification is mandatory.") }
                        if (plan.required.verifyEveryPeriod) item { Text("All DASH periods must be verified before publication.") }
                        item { Text("Plan only — not queued, not downloaded, not Complete. Kotlin HLS fallback remains available.") }
                    }
                }
            }
        },
        confirmButton = {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                if (graph != null && graph.kind in setOf("live", "event") && selection.intent == "live_recording") {
                    TextButton(onClick = onStartLive,
                        enabled = plan != null && plan.intent == "live_recording" && plan.graphRevision == result.manifestRevision && !graph.protectedMedia) {
                        Text("Start live recording")
                    }
                }
                TextButton(onClick = onVerify, enabled = graph != null && !graph.protectedMedia) { Text("Verify selection") }
            }
        },
        dismissButton = { TextButton(onClick = onClose) { Text("Close") } },
    )
}

@Composable
private fun BrowserCaptureSessionHeader(session: BrowserCaptureSessionSummary) {
    XdmGroupedList {
        Column(Modifier.fillMaxWidth().padding(14.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Column(Modifier.weight(1f)) {
                    XdmCardTitle(session.pageTitle.ifBlank { session.pageHost.ifBlank { "Firefox capture" } }, maxLines = 2)
                    XdmMetadataText(session.pageHost.ifBlank { "Browser capture" })
                }
                XdmStatusBadge("${session.importedCandidateCount} found", tone = XdmStatusTone.Success)
            }
            XdmSupportingText(
                if (session.importedCandidateCount == 1) "1 media item is ready to review." else "${session.importedCandidateCount} media items are ready to review.",
                maxLines = 2,
            )
            XdmMetadataText("Browser session values stay private and are used only when a request needs them.")
            XdmTechnicalDetails(label = "Capture details") {
                XdmMetadataText("Browser observations: ${session.totalCandidateCount}")
                val evidence = session.candidates.flatMap { it.evidence }.distinct().take(5)
                if (evidence.isNotEmpty()) XdmMetadataText("Evidence: ${evidence.joinToString(" • ")}")
                if (session.truncated) {
                    XdmMetadataText("More candidates were observed; XDM kept the highest-confidence results in this handoff.")
                }
            }
        }
    }
}

@Composable
private fun MediaBatchInputPanel(
    text: String,
    feedback: String?,
    onTextChanged: (String) -> Unit,
    onInspectAll: () -> Unit,
    onClearInvalid: () -> Unit,
    onCopyRejectedLines: () -> Unit,
    onAddSelected: (String) -> Unit,
) {
    val parser = remember { MediaBatchInputParser() }
    val parsed = remember(text) { parser.parse(text) }
    val mediaReadyUrls = remember(parsed) {
        parsed.accepted
            .filter { it.disposition == MediaBatchUrlDisposition.MediaReady }
            .map { it.normalizedUrl }
    }
    var selectedUrls by remember { mutableStateOf<Set<String>>(emptySet()) }
    LaunchedEffect(text) { selectedUrls = mediaReadyUrls.toSet() }

    XdmGroupedList {
        Column(Modifier.fillMaxWidth().padding(14.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            XdmSectionLabel("Batch media")
            Text("Paste links or page source. XDM will find supported media links and remove duplicates.")
            XdmTechnicalDetails(label = "How batch inspection works") {
                XdmMetadataText("Static inspection does not run page JavaScript. Live locator can observe media loaded by the page. XDM does not bypass DRM or display private browser values.")
            }
            OutlinedTextField(
                value = text,
                onValueChange = onTextChanged,
                label = { Text("Paste URLs or page text") },
                placeholder = { Text("https://site/video1.m3u8\nhttps://site/watch/episode\nhttps://cdn/file.mp4") },
                modifier = Modifier.fillMaxWidth(),
                minLines = 3,
                maxLines = 7,
                supportingText = { Text(feedback ?: "One URL per line, or paste HTML/JSON/text containing media URLs.") },
            )
            if (text.isNotBlank()) {
                XdmMetadataText(parsed.summaryLabel)
                parsed.accepted.take(6).forEach { accepted ->
                    val canSelect = accepted.disposition == MediaBatchUrlDisposition.MediaReady
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        Checkbox(
                            checked = accepted.normalizedUrl in selectedUrls,
                            onCheckedChange = { checked ->
                                selectedUrls = if (checked) {
                                    selectedUrls + accepted.normalizedUrl
                                } else {
                                    selectedUrls - accepted.normalizedUrl
                                }
                            },
                            enabled = canSelect,
                        )
                        Text(
                            text = if (canSelect) accepted.normalizedUrl else "Needs page inspection: ${accepted.normalizedUrl}",
                            modifier = Modifier.weight(1f),
                        )
                    }
                }
                if (parsed.accepted.size > 6) {
                    XdmMetadataText("${parsed.accepted.size - 6} more accepted URL(s) will be inspected by Inspect all.")
                }
            }
            XdmActionFlowRow {
                Button(onClick = onInspectAll, enabled = text.isNotBlank()) { Text("Inspect all") }
                TextButton(onClick = onClearInvalid, enabled = text.isNotBlank()) { Text("Clear invalid") }
                TextButton(onClick = onCopyRejectedLines, enabled = text.isNotBlank()) { Text("Copy rejected lines") }
                TextButton(
                    onClick = { onAddSelected(mediaReadyUrls.filter { it in selectedUrls }.joinToString("\n")) },
                    enabled = selectedUrls.isNotEmpty(),
                ) { Text("Add selected") }
            }
        }
    }
}

private fun openMediaOutput(context: android.content.Context, output: MediaOutputRecord) {
    val uri = output.completedArtifactUri?.takeIf(String::isNotBlank) ?: return
    val intent = Intent(Intent.ACTION_VIEW).apply {
        setDataAndType(Uri.parse(uri), output.mimeType ?: "*/*")
        addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
    }
    try {
        context.startActivity(intent)
    } catch (_: ActivityNotFoundException) {
        // The Library remains the fallback place to open completed media.
    } catch (_: SecurityException) {
        // Some document providers cannot grant an external reader access.
    }
}

@Composable
private fun RecentlyQueuedMediaRow(
    title: String,
    download: Download,
    thumbnailUrl: String?,
    sourceUrl: String?,
    onResumeOrRetry: () -> Unit,
    onCancel: () -> Unit,
    onManage: () -> Unit,
) {
    val progress = download.totalBytes?.takeIf { it > 0L }?.let { download.progressFraction }
    Column(Modifier.fillMaxWidth()) {
        XdmListRow(
            headline = title,
            supporting = buildList {
                add(download.state.uiLabel())
                download.totalBytes?.let { add("${download.bytesReceived.formatBytes()} of ${it.formatBytes()}") }
                if (download.speedBytesPerSecond > 0L) add(download.speedBytesPerSecond.formatSpeed())
            }.joinToString(" • "),
            leading = {
                XdmMediaArtwork(
                    fileName = download.fileName,
                    mimeType = download.mimeType,
                    thumbnailUrl = thumbnailUrl,
                    sourceUrl = sourceUrl,
                    localUri = download.completedArtifactUri,
                    width = 64.dp,
                    height = 44.dp,
                )
            },
        )
        val primaryAction = when (download.state) {
            DownloadState.Downloading,
            DownloadState.Connecting,
            DownloadState.Queued,
            DownloadState.Finalizing -> "Pause"
            DownloadState.Paused,
            DownloadState.Failed,
            DownloadState.WaitingForNetwork,
            DownloadState.WaitingForPower -> if (download.state == DownloadState.Failed) "Retry" else "Resume"
            DownloadState.RecoveryRequired -> if (com.mikeyphw.xdm.android.model.DownloadPresentationPolicy.isFinalSaveRecovery(download)) "Retry finalization" else null
            else -> null
        }
        XdmActionFlowRow(Modifier.padding(start = 68.dp, end = 14.dp, bottom = 6.dp)) {
            primaryAction?.let { TextButton(onClick = onResumeOrRetry) { Text(it) } }
            if (download.state in setOf(
                    DownloadState.Downloading, DownloadState.Connecting, DownloadState.Queued, DownloadState.Finalizing,
                    DownloadState.Verifying, DownloadState.Repairing,
                )
            ) {
                TextButton(onClick = onCancel) { Text("Cancel") }
            }
            TextButton(onClick = onManage) { Text("Manage") }
        }
        if (download.state !in setOf(DownloadState.Completed, DownloadState.Cancelled, DownloadState.Failed)) {
            Row(
                Modifier.fillMaxWidth().padding(start = 68.dp, end = 14.dp, bottom = 10.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                XdmProgressLine(progress = progress, stateLabel = download.state.uiLabel())
            }
        }
    }
}

