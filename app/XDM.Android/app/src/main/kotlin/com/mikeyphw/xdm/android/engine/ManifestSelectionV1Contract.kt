package com.mikeyphw.xdm.android.engine

import org.json.JSONObject

/** MP04: transient Go-owned selection, never persisted or used as download authority.
 * No transport URL is retained in the UI contract. Only coded diagnostics may surface. */
object ManifestSelectionV1Contract {
    const val VERSION = 1
    data class Request(
        val intent: String = "best_video",
        val videoId: String? = null,
        val audioId: String? = null,
        val subtitleId: String? = null,
        val subtitlePolicy: String = "optional",
        val container: String = "auto",
    ) {
        fun wire(): JSONObject {
            require(intent in setOf("best_video", "video_only", "audio_only", "live_recording"))
            require(subtitlePolicy in setOf("optional", "required", "disabled"))
            require(container in setOf("auto", "mp4", "mkv", "webm"))
            listOf(videoId, audioId, subtitleId).forEach { require(it == null || (it.isNotBlank() && it.length <= 256)) }
            return JSONObject().put("intent", intent).put("video_id", videoId ?: JSONObject.NULL)
                .put("audio_id", audioId ?: JSONObject.NULL).put("subtitle_id", subtitleId ?: JSONObject.NULL)
                .put("subtitle_policy", subtitlePolicy).put("container", container)
        }
    }
    data class Required(val video: Boolean, val audio: Boolean, val subtitle: Boolean,
        val verifyEmbeddedAudio: Boolean, val verifyEveryPeriod: Boolean)
    data class Plan(val schemaVersion: Int, val graphRevision: String, val rootId: String,
        val intent: String, val videoId: String?, val audioId: String?, val subtitleId: String?,
        val container: String, val required: Required, val status: String,
        val executionReady: Boolean, val diagnostics: List<String>) {
        fun redactedSummary(): String = "MP04 intent=$intent container=$container video=${required.video} " +
            "audio=${required.audio} subtitle=${required.subtitle} embeddedProof=${required.verifyEmbeddedAudio} " +
            "periodProof=${required.verifyEveryPeriod} executable=$executionReady"
    }
    private val HASH = Regex("[0-9a-f]{64}")
    private val CODE = Regex("[a-z][a-z0-9_]{0,79}")
    fun decode(json: JSONObject): Plan {
        require(json.optInt("schema_version", -1) == VERSION) { "MP04 unsupported plan schema" }
        val revision = json.getString("graph_revision")
        require(HASH.matches(revision)) { "MP04 invalid revision" }
        val root = json.getString("root_id")
        require(root.isNotBlank() && root.length <= 160) { "MP04 invalid graph root" }
        val intent = json.getString("intent")
        require(intent in setOf("best_video", "video_only", "audio_only", "live_recording"))
        val container = json.getString("container")
        require(container in setOf("mp4", "mkv", "webm"))
        val requiredJson = json.getJSONObject("required")
        val required = Required(requiredJson.getBoolean("video"),requiredJson.getBoolean("audio"),
            requiredJson.getBoolean("subtitle"),requiredJson.getBoolean("verify_embedded_audio"),
            requiredJson.getBoolean("verify_every_period"))
        val codes = json.getJSONArray("diagnostic_codes")
        require(codes.length() <= 16) { "MP04 diagnostic limit" }
        val safeCodes = (0 until codes.length()).map { codes.getString(it).also { c ->
            require(CODE.matches(c)) { "MP04 unsafe diagnostic" }
        } }
        val ready = json.getBoolean("execution_ready")
        require(!ready && json.getString("status") == "planned_unverified") { "MP04 cannot claim durable download" }
        fun id(key: String): String? = json.optString(key).takeIf { it.isNotBlank() }
        return Plan(VERSION,revision,root,intent,id("video_id"),id("audio_id"),id("subtitle_id"),
            container,required,"planned_unverified",false,safeCodes)
    }
}
