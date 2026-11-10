# MP08A — Verified source-to-publication contract (staged)

Parent: MP07 draft PR #19, exact SHA `794ce9f66cb0bc3cb2f854b6f75cbf0f234c319b`, targeted Go/security CI success.

This milestone adds `engine/media/verified_publication.go`, immutable source proofs and negative Go tests. It is **not Android MediaStore qualified**, is not a runtime release, does not enable automatic Go mux execution, and does not claim actual Android playable output. The new API requires a separately qualified app-owned `MP08Host` using typed FFmpeg, FFprobe, atomic MediaStore publication and independent post-publication byte readback. No shell commands, URL refresh, arbitrary argv, secrets or external storage are accepted by the new Go layer.

## Required host contract

`MP08DASHPlan` and `MP08HLSPlan` bind the exact MP06/07 staged receipts to MP05 fragment identity, hash, generation and on-disk data. The host must consume an ordered per-track/per-period local-asset graph, including each initialization map, not a signed URL. A package-private plan seal prevents forged or mutated source graphs from reaching the host. `RunMP08VerifiedPublication` revalidates all parts, calls `Assemble`, hashes `ReadStaged`, requires `Probe` to establish actual output stream roles, duration, container and size, requires `PublishAtomic`, and hashes `ReadPublished` from the final content URI before returning `DownloadReady=true`. Any failure returns a non-completed receipt. A staged fragment receipt alone can never be complete.

`RunMP08PartialRecovery` remains a fail-closed opt-in placeholder. The future **Recover partial media** UI action is not wired; a partial stage never becomes a completed download or automatic publication.

## Cases

MUX01–MUX17 and PUB01–PUB08 cover exact DASH and HLS receipts, missing audio/video and per-fragment init, corrupted parts, swapped receipts, invalid output names, FFmpeg nonzero, silent video, A/V duration, FFprobe rejection, ENOSPC, non-atomic publication, swapped digest, post-publish corruption and crash-before-readback. Existing MP05/06/07 Go implementations and Android FFmpeg/Kotlin fallback remain unchanged. The inherited MP07 staleness test is updated with one precisely pinned exception for MP08 test registration; its original baseline comparison remains mandatory.

## MP08B — still required before real Android completion

- Android typed MP08Host adapter integrating the embedded FFmpeg/FFprobe runtime and app-private MP05 files.
- Production fMP4 period concatenation, timestamp reconciliation, per-track codec/container policy and optional subtitle mapping.
- Atomic MediaStore / SAF publication with persistent crash journal, duplicate-basename collisions and ENOSPC recovery.
- Physical Android ARM64 acceptance, real playable output verification and explicit partial-salvage UX.

Exact-head CI05 passing is necessary, but not sufficient to publish or release MP08.
