package com.mikeyphw.xdm.android.engine

fun main() {
    val cases = MP11P04Diagnostics.Area.entries.flatMap { a ->
        MP11P04Diagnostics.Outcome.entries.map { o -> MP11P04Diagnostics.code(a, o) }
    }
    check(cases.size == 20 && cases.toSet().size == 20)
    check(cases.all { it.matches(Regex("MP11_P04_[A-Z_]+")) && it.length <= 64 })
    val secret = "https://example.org/live?sig=SENSITIVE&token=REDACT"
    check(MP11P04Diagnostics.stateLabel(secret) == "Review required")
    check(cases.none { it.contains("example") || it.contains("SENSITIVE") })
    check(MP11P04Diagnostics.stateLabel("capturing") == "Recording")
    check(MP11P04Diagnostics.stateLabel("refresh_required") == "Authorization required")
    check(MP11P04Diagnostics.stagedFragments(-1) == 0)
    check(MP11P04Diagnostics.stagedFragments(Int.MAX_VALUE) == 4096)
    println("MP11_P04_DIAGNOSTIC_TAXONOMY_JVM_PASS")
}
