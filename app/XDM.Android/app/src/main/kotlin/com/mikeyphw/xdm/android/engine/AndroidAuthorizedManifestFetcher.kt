package com.mikeyphw.xdm.android.engine

import android.content.Context
import android.security.NetworkSecurityPolicy
import android.util.Base64
import com.mikeyphw.xdm.android.scheduler.MediaRequestHandoff
import com.mikeyphw.xdm.android.scheduler.MediaRequestHandoffStore
import java.io.ByteArrayOutputStream
import java.net.HttpURLConnection
import java.net.InetAddress
import java.net.URI
import java.net.URL
import org.json.JSONArray
import org.json.JSONObject

/**
 * MP03: Android-owned, read-only fetch port for the Go manifest resolver.
 * Requests from Go are hints, not authorization. The encrypted handoff store
 * binds each request to an existing captured URL and its expiring session.
 * No raw URL, header, body, redirect or exception text is logged.
 */
class AndroidAuthorizedManifestFetcher(private val context: Context) {
    private val maxBody = 2 * 1024 * 1024
    private val maxRedirects = 5
    private val allowedHeaders = setOf("authorization", "cookie", "referer", "user-agent", "origin",
        "accept", "accept-language", "x-api-key", "x-auth-token", "x-access-token", "x-csrf-token")

    suspend fun fetch(payload: JSONObject): JSONObject {
        // Caller dispatches on Dispatchers.IO; network I/O is never performed on UI.
        val id = payload.optString("capture_id").takeIf { it.isNotBlank() && it.length <= 256 }
            ?: return rejected("invalid_capture")
        val handoff = MediaRequestHandoffStore.forCapture(id) ?: return rejected("session_expired")
        val root = parsed(handoff.exactUrl.orEmpty()) ?: return rejected("missing_authorized_request")
        val declaredRoot = parsed(payload.optString("root_url")) ?: return rejected("invalid_root")
        if (root != declaredRoot) return rejected("capture_request_changed")
        val requested = parsed(payload.optString("requested_url")) ?: return rejected("invalid_target")
        val parentRaw = payload.optString("parent_url")
        val parent = if (parentRaw.isBlank()) null else parsed(parentRaw) ?: return rejected("invalid_parent")
        val rootOrigin = origin(root)
        // Default deny cross-origin child manifests; a later explicit approval
        // contract may extend this without replaying credentials to other hosts.
        if (origin(requested) != rootOrigin || (parent != null && origin(parent) != rootOrigin)) {
            return rejected("manifest_origin_denied")
        }
        if (parent == null && requested != root) return rejected("root_request_mismatch")
        val now = System.currentTimeMillis()
        if (handoff.expiresAtEpochMs <= now) return rejected("session_expired")
        val replay = payload.optBoolean("may_replay_credentials", false)
        val max = payload.optInt("max_response_bytes", 0)
        if (max <= 0 || max > maxBody) return rejected("manifest_size_policy")
        if (replay && !sameAuthority(root, requested)) return rejected("credential_scope_denied")
        return try {
            val response = fetchRedirects(requested, rootOrigin, handoff, replay, max)
            JSONObject().put("body_base64", Base64.encodeToString(response.body, Base64.NO_WRAP))
                .put("final_url", response.finalUrl)
                .put("redirects", JSONArray(response.redirects))
                .put("content_type", response.contentType)
                .put("expires_at_epoch_ms", handoff.expiresAtEpochMs)
        } catch (_: Throwable) {
            rejected("manifest_fetch_failed")
        }
    }

    private data class Response(val body: ByteArray, val finalUrl: String, val redirects: List<String>, val contentType: String)

    private fun fetchRedirects(target: String, authorizedOrigin: String, handoff: MediaRequestHandoff,
                               replay: Boolean, max: Int): Response {
        var url = target
        val redirects = mutableListOf<String>()
        val visited = mutableSetOf<String>()
        repeat(maxRedirects + 1) {
            if (!visited.add(url)) error("redirect_cycle")
            val uri = URI(url)
            if (origin(url) != authorizedOrigin) error("redirect_origin_denied")
            checkNetworkScope(uri, handoff, replay)
            val connection = (URL(url).openConnection() as HttpURLConnection)
            try {
                connection.instanceFollowRedirects = false
                connection.connectTimeout = 7_000
                connection.readTimeout = 7_000
                connection.requestMethod = "GET"
                connection.useCaches = false
                connection.setRequestProperty("Accept", "application/vnd.apple.mpegurl, application/dash+xml, application/xml, text/plain, */*")
                if (replay) handoff.headers.forEach { (name, value) ->
                    if (name.lowercase() in allowedHeaders && value.length <= 8192 &&
                        '\r' !in value && '\n' !in value) connection.setRequestProperty(name, value)
                }
                when (connection.responseCode) {
                    301, 302, 303, 307, 308 -> {
                        val location = connection.getHeaderField("Location") ?: error("redirect_missing")
                        val resolved = parsed(uri.resolve(location).toString()) ?: error("redirect_invalid")
                        if (origin(resolved) != authorizedOrigin) error("redirect_origin_denied")
                        if (redirects.size >= maxRedirects) error("redirect_limit")
                        redirects.add(resolved)
                        url = resolved
                    }
                    in 200..299 -> {
                        val declaredLength = connection.contentLengthLong
                        if (declaredLength > max) error("manifest_over_limit")
                        val bytes = ByteArrayOutputStream(minOf(max, 32_768))
                        connection.inputStream.use { source ->
                            val buffer = ByteArray(8192)
                            while (true) {
                                val count = source.read(buffer)
                                if (count < 0) break
                                if (bytes.size() + count > max) error("manifest_over_limit")
                                bytes.write(buffer, 0, count)
                            }
                        }
                        if (bytes.size() == 0) error("manifest_empty")
                        return Response(bytes.toByteArray(), url, redirects.toList(), connection.contentType.orEmpty())
                    }
                    else -> error("manifest_status_denied")
                }
            } finally { connection.disconnect() }
        }
        error("redirect_limit")
    }

    private fun checkNetworkScope(uri: URI, handoff: MediaRequestHandoff, replay: Boolean) {
        if (uri.scheme == "http" && !NetworkSecurityPolicy.getInstance().isCleartextTrafficPermitted(uri.host))
            error("cleartext_denied")
        if (uri.scheme == "http" && replay && !handoff.cleartextCredentialsApproved)
            error("cleartext_credentials_denied")
        val addresses = InetAddress.getAllByName(uri.host)
        if (addresses.isEmpty()) error("dns_empty")
        val privateTarget = addresses.any { address ->
            address.isAnyLocalAddress || address.isLoopbackAddress || address.isLinkLocalAddress ||
            address.isSiteLocalAddress || address.isMulticastAddress || isUniqueLocalV6(address.address)
        }
        if (privateTarget && !handoff.privateNetworkApproved) error("private_network_denied")
    }
    private fun isUniqueLocalV6(address: ByteArray): Boolean =
        address.size == 16 && (address[0].toInt() and 0xFE) == 0xFC

    private fun parsed(raw: String): String? = try {
        val u = URI(raw.trim()).normalize()
        if (u.scheme !in setOf("https", "http") || u.host.isNullOrBlank() || u.userInfo != null ||
            u.fragment != null || u.host.length > 253 || raw.length > 4096) null else u.toASCIIString()
    } catch (_: Exception) { null }
    private fun origin(raw: String): String {
        val u = URI(raw)
        val port = if (u.port < 0) (if (u.scheme == "https") 443 else 80) else u.port
        return "${u.scheme.lowercase()}://${u.host.lowercase()}:$port"
    }
    private fun sameAuthority(root: String, child: String): Boolean = origin(root) == origin(child)
    private fun rejected(code: String): JSONObject = JSONObject().put("ok", false).put("error_code", code)
}
