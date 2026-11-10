# MP08B1 — Android verified private-stage adapter

Parent: MP08A draft PR #20, exact SHA `d614a3c3168c770cb31e3b24d0d34e236a02d0f9`.

This is a new internal platform request (`mp08_finalization`), deliberately separate
from legacy `external_media_tool`. Its input is a typed app-private staged fragment
receipt, not an arbitrary FFmpeg command, URL, output path or filesystem handle.
It validates an unexpired app-paired capture, MP05 journal receipts and exact
hash/length/generation per part, copies each fragment into an isolated private job,
then uses the existing embedded FFmpeg + FFprobe postprocessor to assemble and
verify video and optional audio before an app-private atomic rename and digest
readback. Receipt metadata is fsynced after the output becomes verified.

**This is not DownloadReady and not Android MediaStore qualified.** Success returns
`status=verified_app_private`, `download_ready=false` and
`media_store_published=false`. All partial salvage, gaps, dynamic DASH, multi-period
muxing, subtitles, unsupported containers and source replays remain fail-closed.

## Deferred to MP08B2

The Go `MP08Host` adapter must bind its sealed MP08A plan to this new Android
platform transport and implement bounded readback of staged/published bytes.
MP08B2 must implement MediaStore/SAF recoverable publication, cancellation and
process-death receipts, accept multi-period DASH where FFmpeg validates it,
and demonstrate real emulator/physical ARM64 media fixtures. Until then no UI
completion or production cutover may consume this MP08B1 stage receipt.

## CI and safety

The mandatory MP08 source-contract script now audits this Android broker,
private request routing, receipt validation, FFprobe and atomic stage behavior.
Its inherited MP03–MP08A test contracts and GitHub exact-SHA CI remain mandatory.
The targeted CI Android compilation is required for the Android source changes.
No local Gradle, no force-push, no PR merge, and no runtime claim without hosted
Android Kotlin compilation plus subsequently instrumented execution.
