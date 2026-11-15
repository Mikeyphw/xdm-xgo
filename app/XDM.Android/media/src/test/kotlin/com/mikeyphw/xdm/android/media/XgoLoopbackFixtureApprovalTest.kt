package com.mikeyphw.xdm.android.media

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class XgoLoopbackFixtureApprovalTest {
    private val root = "http://127.0.0.1:8765/live/hls/master.m3u8"

    @Test fun onlyTheExactKnownFixtureIsEligible() {
        assertTrue(XgoLoopbackFixtureApproval.isApprovedRootShape(root))
        for (url in listOf(
            "http://localhost:8765/live/hls/master.m3u8",
            "http://127.0.0.2:8765/live/hls/master.m3u8",
            "http://10.0.0.1:8765/live/hls/master.m3u8",
            "http://127.0.0.1:8766/live/hls/master.m3u8",
            "https://127.0.0.1:8765/live/hls/master.m3u8",
            root + "?token=x", root + "#section",
            "http://user@127.0.0.1:8765/live/hls/master.m3u8",
            "http://127.0.0.1:8765/metrics",
        )) assertFalse(url, XgoLoopbackFixtureApproval.isApprovedRootShape(url))
    }

    @Test fun childrenAreExactSameOriginHlsPlaylistsOnly() {
        assertTrue(XgoLoopbackFixtureApproval.isApprovedChildPlaylist(root, "http://127.0.0.1:8765/live/hls/v/180p.m3u8"))
        assertTrue(XgoLoopbackFixtureApproval.isApprovedChildPlaylist(root, "http://127.0.0.1:8765/live/hls/a/en.m3u8"))
        for (url in listOf(root,
            "http://localhost:8765/live/hls/v/180p.m3u8",
            "http://127.0.0.1:8766/live/hls/v/180p.m3u8",
            "http://127.0.0.1:8765/auth/echo.m3u8",
            "http://127.0.0.1:8765/live/hls/../private.m3u8",
            "http://127.0.0.1:8765/live/hls/%2e%2e/private.m3u8",
            "http://127.0.0.1:8765/live/hls/v/180p.m3u8?token=x",
            "http://127.0.0.1:8765/live/hls/seg/12.ts",
        )) assertFalse(url, XgoLoopbackFixtureApproval.isApprovedChildPlaylist(root, url))
        assertFalse(XgoLoopbackFixtureApproval.isApprovedChildPlaylist("http://public.example/master.m3u8",
            "http://127.0.0.1:8765/live/hls/v/180p.m3u8"))
    }
}
