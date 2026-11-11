# MP09 consolidated — single stacked PR implementation

Parent PR #27 exact SHA `1a0806a069ae27eea322332c9f05f70cf6fd4d34`.

## New code and integrity model

- Go `MP09Recording` binds independently selected video and audio tracks to **one** live-session lifetime. Each poll uses the caller-approved Android network broker; stored fragment bytes are committed/verified by MP05. It schedules per-track retries, not a fixed recording cutoff.
- Android `AndroidLiveRecordingService` is private/exported=false, performs user-started foreground execution, and reuses process-wide Go ownership. No second downloader, no arbitrary command shell, no raw request headers or tokens in status receipts.
- `stop_save` first stops polling, then creates a source-bound `hls_live`/`dash_live` MP08 plan. Only MP08 app-private assembly, FFprobe, atomic MediaStore publication and published-byte readback may assert DownloadReady. The FFmpeg job is a one-shot *post-stop* mux operation; there is no perpetual `-nostdin` recorder to kill.
- Pause requires source DVR capability; cancel must confirm cleanup, with explicit pending state on failure.
- Broker adds exact HTTP range with a 206/Content-Range proof and MP05 bounded verified chunk reads.

## Explicit qualification limitations

This PR is **not** physical ARM64 qualification, long-duration LIVE01–LIVE14 real end-to-end acceptance, 1DM oracle acceptance, or signed-release equivalence. Android API36 compile and emulator tests are mandatory hosted gates after application; source green alone is not an emulator pass. Android 15+ foreground dataSync service restrictions are system limitations and must be surfaced as recovery-required, never completion. MP08A's existing 24h/512MiB per-transaction bounds remain and must fail closed, not manufacture success.

## Required qualification work inside this consolidated PR

- Verify full source and Kotlin compilation on exact hosted SHA. Run real API36 end-to-end HLS/DASH foreground, split-audio, pause/resume, stop-save and cancel tests; 12-minute/11-minute, storage-full, network timeout and process-death tests. Fix failures *in this PR*.
- Recovery after process death cannot automatically reuse an expired handoff; the user must reauthorize. A strict MP05 inventory preflight refuses to start a fresh session with unbound old fragments, preserving them for inspection. A complete source fingerprint/MP05 inventory rebind must be verified on ARM64 before the app claims automatic recovery.
- Do not claim multi-period DASH or signed URL rotation is qualified without exact timeline/segment proofs. Signed URL refresh belongs to MP10.
- Do not auto-merge, auto-release, force-push, reset or rewrite existing branches.

The private service entry point is not yet wired to the production Compose picker; no user-facing recording control availability is claimed. Successful Devtool application creates source for CI qualification, not a completed playable-release feature.

## HF01 three-pass audit hardening (11 Nov 2026)

- **Lifecycle:** Stop & Save verification failure is retryable without reopening the polling session; explicit Cancel & Discard remains available after a failed save. Failed deletion remains pending and never produces a successful cleanup receipt. Source-ended tracks remain awaiting an explicit user Save decision.
- **Foreground:** nonexported service now offers immutable PendingIntent notification actions for Stop & Save, DVR Pause/Resume, and Discard. A failed operation re-enables Save/Discard rather than permanently locking controls. The source's `all_tracks_ended` signal is reflected in the Android result DTO.
- **Storage:** reject symlinked fragment files, reject old journal inventory across *all* track roles (including legacy untagged fragments), validate journal-first deletion and owner-scoped physical absence, and keep app-private source receipts bound to the capture hash.
- **Expired network token:** MP08 may assemble a **Go-verified** `hls_live`/`dash_live` plan from already captured app-private MP05 bytes after browser token expiry. Publication after expiry requires an app-private verified live-source receipt with exact capture hash and destination; this does not renew credentials or allow more network fetching.
- **Packaging:** mandatory three independent offline audits and source-pin drift negatives; local 10-test Go harness and Kotlin service syntax compilation against stubs are distinct from, and cannot substitute for, repository Go tests or a real Android build.

**Still not delivered/qualified:** full API36 instrumented foreground lifecycle, production Compose picker wiring, automatic process-death replay with media-source fingerprint, physical ARM64 capture, Android 15/16 service-budget behavior and published-byte equivalence. Do not describe HF01 as fully implemented, user-releasable, or media-qualified until those checks are completed on the actual repository commit.


## HF02: Restore MP05–MP08 inherited source contracts

HF02 is one hotfix commit on consolidated PR #28. MP05 Go and Kotlin storage adapters are
restored *byte-for-byte* to their exact PR #27 parents so earlier regression tests
remain meaningful. Dedicated MP09 Go/Android fragment-store and MP08 staging adapters
store live fragments in the isolated app-private `xgo-fragments-mp09` journal and
route by explicit `mp09_live=true` / typed `hls_live` or `dash_live` markers.
The legacy MP05 route, JNI broker, and original MP08 stage remain present.
Source CI passing does not qualify API36 or physical ARM64 recording.
Production picker and automatic process-death resume remain separate open gaps.
