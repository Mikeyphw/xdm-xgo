package com.mikeyphw.xdm.android.engine

fun main() {
    val p = MP11LiveLibraryPolicy
    val pub = "pub_1"
    val digest = "sha256:" + "a".repeat(64)
    val uri = "content://media/external/downloads/17"
    check(p.completed("published", "published_verified", true, true, pub, digest, 1024, uri))
    check(p.completed("published_clean", "published_verified", true, true, pub, digest, 4096, uri))
    for (phase in listOf("recording", "publishing", "missing", ""))
        check(!p.completed(phase, "published_verified", true, true, pub, digest, 4096, uri))
    check(!p.completed("published", "published_verified", true, false, pub, digest, 4096, uri))
    check(!p.completed("published", "pending", true, true, pub, digest, 4096, uri))
    check(!p.completed("published", "published_verified", false, true, pub, digest, 4096, uri))
    check(!p.completed("published", "published_verified", true, true, "bad/id", digest, 4096, uri))
    check(!p.completed("published", "published_verified", true, true, pub, "sha256:invalid", 4096, uri))
    check(!p.completed("published", "published_verified", true, true, pub, digest, 1023, uri))
    check(!p.completed("published", "published_verified", true, true, pub, digest, p.MAX_OUTPUT_BYTES + 1, uri))
    for (url in listOf("https://host/file.mp4", "file:///private/output", "content://evil/1", "content://media/a?token=1", "content://media/a#fragment", "content://media/../../private"))
        check(!p.completed("published", "published_verified", true, true, pub, digest, 4096, url))
    check(p.reviewRequired("publishing", false, false))
    check(p.reviewRequired("published", true, false))
    check(!p.reviewRequired("published_clean", true, true))
    check(p.cleanupLabel("published").contains("requires review"))
    check(p.cleanupLabel("published_clean").contains("verified"))
    println("MP11_P03_LIVE_LIBRARY_POLICY_JVM_PASS")
}
