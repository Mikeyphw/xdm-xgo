# MP08B3 P01 — Integrated native x86_64 MediaStore acceptance (draft)

**Scope:** opt-in API36 emulator only; stacked on source-qualified native FFmpeg, FFprobe and aria2 PR #24 (`36e8e318305023a8edbc5cff836bfeea2f5c56d6`). No production ABI configuration, ARM64 release recipe, Android signing identity or user data is changed.

## One emulator, seven mandatory tests

The existing `xgo-x86-native-media` label provisions an Android API36 x86_64 emulator, source-builds pinned FFmpeg 9.0.1, FFprobe 9.0.1 and aria2 1.37.0 (with SHA-256, NDK, 16 KiB ELF and lock checks), and builds the x86 debug and Android-test APKs. In the same running emulator, one POSIX-safe `script:` executes two commands connected with `&&`:

1. `scripts/xgo_x86_native_media.py emulator`: the existing **three** Android native runtime execution tests and exact APK/source-byte identity, producing `android-junit.xml` plus `native-media-receipt.json`.
2. `scripts/xgo_mp08b3_x86_integration.py run`: independently verifies the first receipt, the real x86_64 emulator identity and source pins, deletes the previous JUnit output, launches the **four** unskipped `MP08B3MediaStoreAcceptanceInstrumentedTest` methods via `:app:connectedDebugAndroidTest`, validates the exact fresh four-case XML with the existing MP08B3 receipt contract, and writes `mp08b3-four-junit.json`.

The second step cannot run if the first fails. A no-tests run, wrong class, wrong ABI, malformed XML, DTD, duplicate/skipped/failed test, stale evidence, changed APK or wrong Git head refuses qualification. A failed Android instrumentation run emits bounded redacted crash diagnostics and remains red.

## Evidence and limitations

The hosted artifact retains three native runtime test evidence plus independent MP08B3 four-case evidence, source commit and SHA-256. This **does not** qualify physical ARM64, Android APK release/signing, Go-host MP08A byte equivalence, process-death preservation, user-authenticated site downloads or 1DM licensing.

The original MP08B3 Android instrumentation code is reused **unchanged**. The x86_64 build profile is temporary in the GitHub Actions checkout; ARM64 release/CI defaults remain unchanged. The workflow is label-triggered on a same-repository draft PR, not automatic on push, tags or ordinary PR events. The previous PR #24 source-built x86 runtime qualification remains separate and preserved.

## Expected source and validation

PR parent: `36e8e318305023a8edbc5cff836bfeea2f5c56d6`. Base branch: `feature/xgo-x86-media-runtimes-20261110`. Base PR: #24. The launcher creates a new stacked draft PR and never commits to main, rebases, force pushes or merges automatically. It uses Devtool v2 overlay, exact preflight, hosted Gradle, live `gh` TUI tracking, and Termux success/failure toast then vibration. No Gradle/.NET is run in Termux.

## Roadmap continuation

If the seven hosted tests pass, proceed to MP08B4: integrated Go-published-byte equivalence and process-death/pending-row restoration, then physical API36 ARM64 acceptance with signed APK identity and rollback. Preserve the canonical MP00–MP12 roadmap bundled in the launcher. A successful emulator is never substituted for the physical-release gate.
