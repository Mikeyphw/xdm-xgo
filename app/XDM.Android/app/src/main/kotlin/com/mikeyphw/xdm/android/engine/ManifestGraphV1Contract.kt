package com.mikeyphw.xdm.android.engine

import android.net.Uri
import org.json.JSONArray
import org.json.JSONObject

/**
 * MP03 Android-owned, versioned decoder for Go's read-only manifest graph.
 *
 * The trusted JNI frame is ephemeral, may contain signed transport URLs, and must
 * NOT be written to logs, saved state, navigation URLs, analytics or support logs.
 * This contract does not change the Kotlin HLS download fallback or claim that
 * Go has durable fragment publication; MP04/MP05 own those later transitions.
 */
object ManifestGraphV1Contract {
    const val VERSION = 1
    private const val MAX_OPTIONS = 512
    private const val MAX_MANIFESTS = 128

    data class Quality(
        val kind: String,
        val id: String,
        val transportUrl: String,
        val periodId: String,
        val width: Int,
        val height: Int,
        val bandwidth: Int,
        val codecs: List<String>,
        val audioGroup: String,
        val subtitleGroup: String,
        val protection: String,
    )

    data class Track(
        val id: String,
        val transportUrl: String?,
        val type: String,
        val periodId: String,
        val group: String,
        val name: String,
        val language: String,
        val embedded: Boolean,
        val default: Boolean,
        val protection: String,
    )

    data class Period(val id: String, val startMs: Long, val durationMs: Long, val discontinuity: Long)

    data class Graph(
        val schemaVersion: Int,
        val protocol: String,
        val kind: String,
        val periods: List<Period>,
        val qualities: List<Quality>,
        val audioTracks: List<Track>,
        val subtitleTracks: List<Track>,
        val protectedMedia: Boolean,
        val protection: List<String>,
        val sourceCount: Int,
        val downloadReady: Boolean,
    ) {
        /** This diagnostic summary never includes signed URLs or raw manifests. */
        fun redactedSummary(): String =
            "ManifestGraphV1 protocol=$protocol kind=$kind periods=${periods.size} " +
            "qualities=${qualities.size} audio=${audioTracks.size} subtitles=${subtitleTracks.size} " +
            "protected=$protectedMedia sources=$sourceCount downloadReady=$downloadReady"
    }

    private fun requireURL(raw: String): String {
        val uri = Uri.parse(raw)
        require((uri.scheme == "https" || uri.scheme == "http") &&
            !uri.host.isNullOrBlank() && uri.userInfo.isNullOrBlank() && uri.fragment == null) {
            "MP03 invalid transport URL"
        }
        return raw
    }

    private fun JSONArray.toStrings(maxItems: Int = MAX_OPTIONS): List<String> {
        require(length() <= maxItems) { "MP03 string list exceeds bound" }
        return (0 until length()).map { index ->
            getString(index).also { require(it.length <= 512) { "MP03 oversized token" } }
        }
    }

    private fun requireBounded(array: JSONArray, max: Int): JSONArray =
        array.also { require(it.length() <= max) { "MP03 graph exceeds bound" } }

    fun decode(json: JSONObject): Graph {
        require(json.optInt("schema_version", -1) == VERSION) { "MP03 incompatible manifest schema" }
        val protocol = json.getString("protocol")
        val kind = json.getString("kind")
        require(protocol == "hls" || protocol == "dash") { "MP03 unsupported graph protocol" }
        require(kind == "vod" || kind == "live" || kind == "event") { "MP03 unsupported manifest kind" }
        requireURL(json.getString("root_url"))
        require(json.getString("root_id").isNotBlank()) { "MP03 missing root identity" }
        val periods = requireBounded(json.getJSONArray("periods"), MAX_OPTIONS).let { input ->
            (0 until input.length()).map { i ->
                val item = input.getJSONObject(i)
                Period(item.getString("id"), item.optLong("start_ms", 0L),
                    item.optLong("duration_ms", 0L), item.optLong("discontinuity", 0L))
            }
        }
        val periodIds = periods.map { it.id }.toSet()
        require(periodIds.size == periods.size) { "MP03 duplicate periods" }
        val qualities = requireBounded(json.getJSONArray("variants"), MAX_OPTIONS).let { input ->
            (0 until input.length()).map { i ->
                val item = input.getJSONObject(i)
                Quality(item.optString("kind", "undetermined").also {
                    require(it == "video" || it == "undetermined") { "MP03 unknown quality kind" }
                }, item.getString("id"), requireURL(item.getString("url")),
                    item.optString("period_id"), item.optInt("width").coerceAtLeast(0),
                    item.optInt("height").coerceAtLeast(0), item.optInt("bandwidth").coerceAtLeast(0),
                    item.optJSONArray("codecs")?.toStrings() ?: emptyList(),
                    item.optString("audio_group"), item.optString("subtitle_group"),
                    item.optString("protection"))
            }
        }
        fun parseTracks(key: String, expected: Set<String>): List<Track> {
            val input = requireBounded(json.getJSONArray(key), MAX_OPTIONS)
            return (0 until input.length()).map { i ->
                val item = input.getJSONObject(i)
                val type = item.getString("type")
                require(type in expected) { "MP03 mismatched track kind" }
                val url = item.optString("url").takeIf { it.isNotBlank() }?.let(::requireURL)
                val embedded = item.optBoolean("embedded", false)
                require(url != null || embedded) { "MP03 missing explicit track locator" }
                Track(item.getString("id"), url, type, item.optString("period_id"),
                    item.optString("group"), item.optString("name"), item.optString("language"),
                    embedded, item.optBoolean("default", false), item.optString("protection"))
            }
        }
        val audio = parseTracks("audio_tracks", setOf("audio"))
        val subtitle = parseTracks("subtitle_tracks", setOf("subtitles", "text"))
        val sources = requireBounded(json.getJSONArray("sources"), MAX_MANIFESTS)
        require(qualities.size + audio.size + subtitle.size <= MAX_OPTIONS) { "MP03 total options exceed bound" }
        val allIds = qualities.map { it.id } + audio.map { it.id } + subtitle.map { it.id }
        require(allIds.size == allIds.toSet().size) { "MP03 duplicate option ID" }
        require(allIds.isNotEmpty()) { "MP03 empty graph" }
        // DASH period IDs are authoritative; HLS discontinuity nodes refer to
        // segment timelines and may not equal the parent variant period ID.
        if (protocol == "dash") {
            require((qualities.map { it.periodId } + audio.map { it.periodId } +
                subtitle.map { it.periodId }).all { it in periodIds }) { "MP03 orphan DASH period" }
        }
        require(!json.optBoolean("download_ready", false)) { "MP03 graph cannot authorize download completion" }
        return Graph(VERSION, protocol, kind, periods, qualities, audio, subtitle,
            json.optBoolean("protected", false),
            json.optJSONArray("protection")?.toStrings() ?: emptyList(),
            sources.length(), downloadReady = false)
    }
}
