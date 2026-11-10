# MP08B3 — Real-media and API36 MediaStore acceptance (non-release)

## Parent

Draft PR #22, exact head `29ed4c0cd4ddc5786d565ea9d43783d917a3c5f5`, targeted Go + Kotlin CI green. The MP08B3 PR is stacked without merging previous draft phases.

## Default pull request evidence

`XGO MP08B3 Real Media Acceptance` runs a true Linux FFmpeg/FFprobe mux, full decode, duration and required video+audio stream checks; corrupt/truncated output and missing audio are negatives. The report contains only byte counts, hashes, stream types and durations. It explicitly sets `android_qualified=false`, `publication_qualified=false`, and `physical_arm64_qualified=false`.

The same job compiles the real new Android instrumentation source with `:app:compileDebugAndroidTestKotlin`. It does **not** run Android or treat a successful Linux mux as an Android runtime pass.

## Manual API36 emulator

Dispatch `.github/workflows/xgo-mp08b3-acceptance.yml` **from the exact PR head**, enter the full 40-hex commit SHA, and explicitly enable `x86_64_media_test`. It defaults **false**; a disabled or skipped manual emulator causes a failed manual qualification gate. The runner requires Ubuntu 24.04 KVM, API36 Google APIs emulator, and the real app instrumentation. No production x86 binary is added to the repo or release.

The instrumentation tests publish an actual existing MP4 test asset to MediaStore with `IS_PENDING`, verify full readback, check idempotent publication, bad receipt bytes and expired/missing authorization, and exercise a pending-transaction recovery after constructing a fresh broker. A separate test requires a real attested embedded FFmpeg+FFprobe runtime to mux existing independent MP4 and AAC assets before publication. **If the x86_64 test runtime is not available or the APK lacks supported JNI ABI, the emulator job MUST fail.** The test is neither assumed nor skipped.

No private app/user data is inspected. All capture IDs and output names are test-scoped; emitted evidence must not include URLs, cookies or authorization headers.

## Explicit acceptance boundary

MP08B3 is **not** a completed MP08 release gate until the manual API36 test and separate physical ARM64 real mux/publication, Go independent published readback, process-death and low-storage chaos suites have actual evidence. A source contract or CI syntax pass is not a device pass. No production cutover, automatic merge or release.
