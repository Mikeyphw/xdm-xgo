package com.mikeyphw.xdm.android.engine

import java.net.URI

/** MP09: ephemeral UI-to-FGS selection. This is not a download authorization.
 * Go and the Android network broker must independently validate the live session.
 * Neither signed URL nor browser credentials may be saved or logged here.
 */
internal object AndroidLiveSelectionGate {
    data class Selection(
        val protocol: String,
        val videoUrl: String,
        val audioUrl: String,
        val videoRepresentationId: String,
        val audioRepresentationId: String,
        val requireAudio: Boolean,
    )

    fun fromFreshManifest(
        captureId: String,
        expectedRevision: String,
        requested: ManifestSelectionV1Contract.Request,
        result: AndroidMediaUiCommandResult,
    ): Selection {
        require(captureId.isNotBlank() && captureId.length <= 256)
        require(Regex("[0-9a-f]{64}").matches(expectedRevision))
        require(result.ok && result.action == "resolve_manifest" && result.captureId == captureId)
        require(result.manifestRevision == expectedRevision)
        val graph = requireNotNull(result.manifestGraph)
        val plan = requireNotNull(result.manifestSelectionPlan)
        require(graph.kind in setOf("live", "event") && !graph.protectedMedia && !graph.downloadReady)
        // MP03 synthetic option IDs are NOT raw DASH representation IDs. Never
        // guess the mapping or pass the synthetic ID to the native DASH poller.
        require(graph.protocol == "hls")
        require(requested.intent == "live_recording" && requested.container == "mp4" &&
            requested.subtitlePolicy == "disabled" && requested.subtitleId == null)
        require(plan.graphRevision == expectedRevision && plan.intent == "live_recording" &&
            plan.container == "mp4" && plan.status == "planned_unverified" && !plan.executionReady)
        require(plan.required.video && plan.required.audio && !plan.required.subtitle &&
            !plan.required.verifyEmbeddedAudio && !plan.required.verifyEveryPeriod)
        require(requested.videoId == null || requested.videoId == plan.videoId)
        require(requested.audioId == null || requested.audioId == plan.audioId)
        val video = graph.qualities.single { it.id == plan.videoId }
        val audio = graph.audioTracks.single { it.id == plan.audioId && !it.embedded && it.transportUrl != null }
        require(video.protection in setOf("", "none", "clear", "unresolved") &&
            audio.protection in setOf("", "none", "clear", "unresolved"))
        val videoOrigin = safeOrigin(video.transportUrl)
        require(videoOrigin == safeOrigin(requireNotNull(audio.transportUrl)))
        return Selection("hls", video.transportUrl, requireNotNull(audio.transportUrl), "", "", true)
    }

    private fun safeOrigin(raw: String): String {
        require(raw.length in 1..4096 && raw.none { it == '\r' || it == '\n' || it == '\u0000' })
        val u = URI(raw)
        val scheme = u.scheme?.lowercase()
        require(scheme == "https" || scheme == "http")
        val host = u.host?.lowercase().orEmpty()
        require(host.isNotBlank() && host.length <= 253 && u.userInfo == null && u.fragment == null)
        require(u.port in -1..65535)
        return "$scheme://$host:${if (u.port == -1) if (scheme == "https") 443 else 80 else u.port}"
    }
}
