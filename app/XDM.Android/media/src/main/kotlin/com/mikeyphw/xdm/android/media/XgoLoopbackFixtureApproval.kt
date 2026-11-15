package com.mikeyphw.xdm.android.media

import java.net.URI

/** Only a user-approved MP09 localhost HLS fixture, not a general LAN bypass. */
object XgoLoopbackFixtureApproval {
    private const val HOST = "127.0.0.1"
    private const val PORT = 8765
    private const val MASTER = "/live/hls/master.m3u8"
    private const val PREFIX = "/live/hls/"

    private fun safeFixtureUri(value: String): URI? = runCatching {
        URI(value).takeIf { uri ->
            uri.scheme == "http" &&
                uri.host == HOST &&
                uri.port == PORT &&
                uri.rawUserInfo == null &&
                uri.rawQuery == null &&
                uri.rawFragment == null &&
                uri.rawPath == uri.path &&
                uri.path?.startsWith(PREFIX) == true &&
                !uri.path.contains("..") &&
                !uri.path.contains("//") &&
                !uri.path.contains('\\')
        }
    }.getOrNull()

    fun isApprovedRootShape(value: String): Boolean = safeFixtureUri(value)?.path == MASTER

    fun isApprovedChildPlaylist(root: String, child: String): Boolean {
        if (!isApprovedRootShape(root)) return false
        val candidate = safeFixtureUri(child) ?: return false
        return candidate.path != MASTER && candidate.path.endsWith(".m3u8")
    }
}
