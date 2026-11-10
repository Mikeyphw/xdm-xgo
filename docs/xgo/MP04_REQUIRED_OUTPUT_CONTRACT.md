# MP04 — exact selection and required-output planning

Source pin: PR #15 at `aa098d6ee5403b3e734c88f8736ae551604e56c1` (the qualified MP03 base).

- Go `SelectManifestGraph` consumes the versioned MP03 graph and returns an explicit per-role plan with container compatibility, deterministic language/quality preference, and URL-scoped exact selections.
- HLS audio/subtitle group mismatch, expired IDs, protected evidence, and impossible container/codec combinations **refuse** instead of substituting a different track.
- Unknown embedded audio stays **required** and `verify_embedded_audio=true`; no silent omission. Required subtitle isn't an optional mux map. DASH with multiple periods is refused until MP07 can prove every-period coverage.
- For MP04 all plans are `planned_unverified`; `execution_ready=false` because MP05 durable fragments and MP08 verified mux/publication do not exist. No `Completed` or `download_ready=true` claim.
- The Android UI sends its exact checked selection plus a SHA-256 revision of the graph to the authorized Go resolver, which re-fetches under the encrypted Android session, rejects a changed graph, and returns a versioned transient plan. No user-provided URI is accepted as an executable authority.
- Plan transport URLs exist **only in the volatile Go JNI response**. The Android decoder keeps only opaque IDs, output requirements, container and safe diagnostic codes; never publish URLs or auth to logs, state, intents, analytics, reports or PR artifacts.
- The legacy Kotlin HLS/native fallback is untouched and remains the only qualified production execution path. MP04 preview does not feed incompatible Go IDs into the Kotlin download planner.

## Suite

SEL01 quality/codec; SEL02 HLS group mismatch; SEL03 language/default; SEL04 video/audio-only; SEL05 required subtitles; SEL06 codec/container; SEL07 stale/protected; SEL08 embedded audio and DASH period refusal; MUX01 strict required output and safe diagnostics. Plus manifest-revision freshness and source/staleness policy tests.

## Remaining gates

Targeted Go+Kotlin source qualification via hosted GitHub Actions; native API36 runtime/JNI, physical ARM64, encrypted-session acceptance, MP05 fragment durability, MP08 FFprobe verification and licensed 1DM+ comparison separately pending. CI05 mandatory high-risk/full integration gate is not bypassed.
