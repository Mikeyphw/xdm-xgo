# MP08B2 — MediaStore visibility publication and Go MP08Host transport

Parent: MP08B1 draft PR #21, exact commit `a6fb049fe0bccf86f00ba1909b1cd393d470b9c4`.

## Implemented comparison / opt-in surfaces

- `engine/runtime/platform/broker.go` adds typed `mp08_finalization` platform request.
- `engine/runtime/android_mp08_host.go` implements all five Go `media.MP08Host` operations: `Assemble`, `Probe`, `ReadStaged`, `PublishAtomic`, `ReadPublished`. The constructor requires an explicit capture ID and platform invocation; it is **not production cutover** and does not start work by itself.
- Go verifies the staged SHA-256 from bounded, exact-offset 64 KiB readback; checks FFprobe and stream/duration expectations; and verifies the published bytes again before `RunMP08VerifiedPublication` alone may issue `DownloadReady=true`.
- Android `AndroidMP08VerifiedStageBroker` from MP08B1 remains the only private FFmpeg stage assembler; its receipt stays `DownloadReady=false`.
- New `AndroidMP08PublicationBroker` authorizes the capture against the existing paired handoff, hashes the app-private candidate and issues a scoped MediaStore Downloads insert with `IS_PENDING=1`; it copies, fsyncs, rehashes the pending object, sets `IS_PENDING=0`, rehashes the visible result and commits a private publication receipt. A recovery journal records interrupted transactions and prevents partial outputs from being called complete.
- Kotlin dispatch remains asynchronous; it cannot execute arbitrary shell, accept output paths or credential-bearing HTTP inputs. Android responses always set `download_ready=false`, including when MediaStore publication is visible.

## Hard boundary / limitations

- Android MediaStore pending visibility is the atomic *visibility* commit. It is not an atomic filesystem rename and no SAF tree grant is silently inferred.
- Only Android API 29+ is admitted. MIME is MP4, final output under `Download/XDM/` using a bounded display name. Multi-period DASH, dynamic DASH, subtitle mux, missing/explicit gaps, partial salvage and arbitrary destination URI remain refused. MP08A supports broader Go plans, but this Android adapter intentionally fails closed on those until separate acceptance.
- The Go host is callable through an explicit constructor, but there is **no automatic UI/download production cutover**; an authenticated Go caller must still construct a sealed MP08 plan from MP06/07 and execute the full MP08 Go gate. Android platform calls alone cannot produce DownloadReady.
- A separate real API 36 Android emulator acceptance must run FFmpeg/FFprobe against real fragments, simulate crash at each `IS_PENDING` transition and validate MediaStore visibility and cleanup. Physical ARM64 acceptance remains required. Targeted Kotlin compile is not runtime evidence.

## Required hosted gates

1. Targeted Go `go test ./...` including new MP08B2HOST01–HOST14, inherited MP05–08 cases and source staleness audits.
2. Android `:app:compileDebugKotlin` exact-head after all changed sources.
3. After targeted green: emulator API 36 MediaStore pending/commit/restart tests, storage corruption and expiry coverage, independent final Go readback, then physical ARM64 acceptance.
4. No merge/publish without full required gates. Never force push, reset or rebase the stacked worktree.
