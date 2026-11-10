# MP07 — DASH multi-period exact selection and durable staging

**Base:** MP06 draft PR #18 exact SHA `81197fe4bcd8e1f80c06fee0621cbc9b33d4d615` (targeted Go/Android CI passed).

## Implemented staged boundary

- MPD parsing uses existing Go `ParseDASHManifest` and `ExpandDASHFragments` with the original network authorization boundary. The caller supplies a manifest body and `DASHFetcher` rather than allowing a new HTTP client.
- Exact period-by-period representation selection uses period ID, adaptation ID, representation ID and normalized role. It rejects duplicate IDs, wrong order and missing required audio or MP4 initialization sections.
- Period starts and durations must agree. Selected tracks must cover the period without overlapping or missing timeline ranges. Refuses wrong period transitions, unsupported content protection and non-bounded dynamic observations.
- Separate video/audio/subtitle durable sinks must be available *before* requests begin. Committed media and initialization fragments are verified against their MP05 records. Restart reuses only read-back-verified receipts; failed fetches or integrity mismatches cannot become ready.
- Static, completely verified periods may emit `Status=staged`, `ReadyForMux=true`. Audio-uncertain selections remain staged but not mux-ready. Dynamic bounded observations are explicitly `bounded_live_staged` and never ready for mux. `DownloadReady=false` in all MP07 receipts.
- No FFmpeg, MediaStore, playback, final mux, release or physical-device claim is made. MP08 remains responsible for container verification, FFprobe, publication and complete playable output; MP09+ handle live recording/resilience.

## Tests and gating

`DASH01`–`DASH16` cover selected multi-period audio/video, restart/recovery, period order/gaps/overlaps, missing audio, DRM, required initialization, partial failures, corruption, bounded dynamic, duplicate IDs, missing sinks, raw URL privacy and mux/publication false positives. `STORE` integrity and all previously registered `MP03`–`MP06` Python regressions remain mandatory via targeted CI policy. All Go module tests and Android Kotlin compile, when relevant, run in hosted GitHub Actions; Termux does not run Gradle.

## Known limitations / next work

DASH SegmentList, nested BaseURL and repeat expansion remain owned by existing `dash.go`, and this phase uses those results without rewriting the parser. MP07 is staged selection and verified fragments; it does **not** declare full roadmap MP07's multi-period mux exit or production-device qualification. An Android manifest adapter/cutover and real end-to-end multi-period mux are explicitly pending MP08.
