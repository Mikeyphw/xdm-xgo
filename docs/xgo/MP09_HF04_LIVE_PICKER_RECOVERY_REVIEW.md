# XGO MP09 HF04 — Live picker and interruption review

Exact parent: `94761ca3c2e374018bd26cb131497b9bd0d4a0c9`, existing draft PR #28.

- Adds a visible live-recording choice in the media review screen; verifies an exact
  revision-bound manifest again before an explicit foreground service start.
- The Go selection plan is *not* an execution capability; Android handoff, origin
  restrictions, fragment verification, and Go runtime still independently gate use.
- Initially UI-admits **unprotected HLS with an explicitly separate audio rendition**.
  It intentionally refuses DASH synthetic representation IDs (which are not raw DASH
  representation IDs), unproven embedded audio, DRM, missing audio, and mismatched origins.
- Adds a read-only interruption inventory and separate user-confirmed discard with
  verified app-private cleanup. Does **not** auto-resume signed browser requests or
  implement in-place restart restoration; these remain MP09 qualification gaps.
- Retains Android 15+ dataSync foreground-service timeout semantics: an OS timeout
  means interrupted/review, never completion.
- No existing MP05–MP08 source, staleness test, CI classification policy, or
  FFmpeg publication security boundary is modified.
- The real Android full build, API36 emulator and physical ARM64 tests are pending
  until hosted Actions run against the newly pushed exact commit.

Termux (Zsh-safe):

    python3 /storage/emulated/0/Download/XGO_MP09_HF04_LIVE_PICKER_RECOVERY_REVIEW_PR28_20261111.zip

Optional offline audit:

    python3 /storage/emulated/0/Download/XGO_MP09_HF04_LIVE_PICKER_RECOVERY_REVIEW_PR28_20261111.zip --self-test

No local Gradle/Go builds by the launcher. A source-pinned native Devtool v2 overlay
is assembled under `$TMPDIR`; it commits and pushes normally to PR #28. No automatic merge.
