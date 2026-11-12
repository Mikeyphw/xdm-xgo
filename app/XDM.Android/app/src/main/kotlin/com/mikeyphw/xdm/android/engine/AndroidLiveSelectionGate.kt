package com.mikeyphw.xdm.android.engine

import java.net.URI

/** MP09 ephemeral Go-verified live selection. A graph is not an execution or
 * publication authority. Signed URL strings never enter persistent UI state.
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
        dashBinding: AndroidMediaUiCommandResult? = null,
    ): Selection {
        require(captureId.isNotBlank() && captureId.length <= 256)
        require(Regex("[0-9a-f]{64}").matches(expectedRevision))
        require(result.ok && result.action == "resolve_manifest" && result.captureId == captureId)
        require(result.manifestRevision == expectedRevision)
        val graph = requireNotNull(result.manifestGraph)
        val plan = requireNotNull(result.manifestSelectionPlan)
        require(graph.kind in setOf("live", "event") && !graph.protectedMedia && !graph.downloadReady)
        require(requested.intent == "live_recording" && requested.container == "mp4" &&
            requested.subtitlePolicy == "disabled" && requested.subtitleId == null)
        require(plan.graphRevision == expectedRevision && plan.intent == "live_recording" &&
            plan.container == "mp4" && plan.status == "planned_unverified" && !plan.executionReady)
        require(plan.required.video && plan.required.audio && !plan.required.subtitle &&
            !plan.required.verifyEmbeddedAudio)
        require(requested.videoId == null || requested.videoId == plan.videoId)
        require(requested.audioId == null || requested.audioId == plan.audioId)
        val video = graph.qualities.single { it.id == plan.videoId }
        val audio = graph.audioTracks.single { it.id == plan.audioId && !it.embedded && it.transportUrl != null }
        require(video.protection in setOf("", "none", "clear", "unresolved") &&
            audio.protection in setOf("", "none", "clear", "unresolved"))
        require(safeOrigin(video.transportUrl) == safeOrigin(requireNotNull(audio.transportUrl)))

        if (graph.protocol == "hls") {
            require(!plan.required.verifyEveryPeriod && dashBinding == null)
            return Selection("hls", video.transportUrl, requireNotNull(audio.transportUrl), "", "", true)
        }
        require(graph.protocol == "dash" && graph.kind == "live" && graph.periods.size == 1 &&
            plan.required.verifyEveryPeriod && dashBinding != null)
        // The synthetic MP03 option IDs cannot be passed directly to P02's
        // native DASH poller. Only Go may return fresh, exact raw MPD IDs.
        val bound = requireNotNull(dashBinding)
        require(bound.ok && bound.action == "live" && bound.captureId == captureId &&
            bound.status == "dash_bound_unverified" && bound.manifestRevision == expectedRevision)
        val manifest = requireNotNull(bound.liveManifestUrl)
        val vid = requireNotNull(bound.videoRepresentationId)
        val aud = requireNotNull(bound.audioRepresentationId)
        require(vid.matches(Regex("[A-Za-z0-9._-]{1,128}")) &&
            aud.matches(Regex("[A-Za-z0-9._-]{1,128}")) && vid != aud)
        require(safeOrigin(manifest) == safeOrigin(video.transportUrl) &&
            safeOrigin(manifest) == safeOrigin(requireNotNull(audio.transportUrl)))
        return Selection("dash", manifest, manifest, vid, aud, true)
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
