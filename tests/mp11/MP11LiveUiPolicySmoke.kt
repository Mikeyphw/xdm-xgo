package com.mikeyphw.xdm.android.engine

fun main() {
    check(MP11LiveUiPolicy.actions("refresh_required", false) == setOf("stop_save","discard","refresh"))
    check("pause" !in MP11LiveUiPolicy.actions("capturing", false))
    check("pause" in MP11LiveUiPolicy.actions("capturing", true))
    check("resume" in MP11LiveUiPolicy.actions("paused", true))
    check(MP11LiveUiPolicy.actions("not_active", true).isEmpty())
    check(MP11LiveUiPolicy.actions("published", true).isEmpty())
    check(MP11LiveUiPolicy.validRefresh("https://edge.test/root.mpd?sig=a", "https://edge.test/v.m3u8?token=b", "https://edge.test/a.m3u8?sig=c"))
    check(!MP11LiveUiPolicy.validRefresh("https://edge.test/root", "https://evil.test/v", "https://edge.test/a"))
    check(!MP11LiveUiPolicy.validRefresh("file:///sdcard/root", "file:///a", "file:///b"))
    check(!MP11LiveUiPolicy.validRefresh("https://user:secret@edge.test/root", "https://edge.test/v", "https://edge.test/a"))
    check(!MP11LiveUiPolicy.validRefresh("https://edge.test/root#fragment", "https://edge.test/v", "https://edge.test/a"))
    check(!MP11LiveUiPolicy.validRefresh("https://edge.test/root", "https://edge.test/v\r\nHeader:evil", "https://edge.test/a"))
    println("MP11_UI_POLICY_JVM_SMOKE_PASS")
}
