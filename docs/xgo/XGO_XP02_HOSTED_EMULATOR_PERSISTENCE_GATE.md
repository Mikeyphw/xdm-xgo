# XP02 — GitHub API 36 x86_64 emulator-safe persistence test lane

## Why this exists

The production XDM Android APK contains a provenance-pinned ARM64 Go/JNI engine,
aria2 and FFmpeg. Emulating ARM64 under x86_64 can produce a `cpu.getMIDR` SIGILL;
that does not prevent real Android framework and Room tests from running on the
regular API 36 x86_64 GitHub Actions emulator.

## Hosted job

`XDM Android CI / emulator-compatibility` now runs two independent checks:

1. Verify API 36, x86_64 ABI, KVM, boot, ADB and package/instrumentation services.
2. Run the **entire `:persistence:connectedDebugAndroidTest`** suite in the same
   emulator with Gradle 9.7.1; parse JUnit XML and require seven expected test
   classes, a positive test count, and zero failures/errors/skips.

The instrumentation covers Room migrations, repository state, concurrent download
admission, media output admission, generation ownership and recovery integrity.
It does **not** install the ARM64 app, start its Go engine, run aria2 or FFmpeg, or
count as native ARM64 proof. The existing ARM64 physical-device gate and separate
manual translation diagnostics are unchanged. CI uploads the bounded test results
and receipt as `xdm-emulator-persistence-test-results`.

## Next expansion

App-level Compose UI, browser scheme resolution, secure storage and direct-v3
intake can also run on x86_64, but require an explicitly isolated native-free
Android app test variant before enabling them as release gates. Keep ARM64
packaged-execution/TLS/FFmpeg/JNI tests physical ARM64-only.

## Acceptance

Passes only when GitHub Actions reports the emulator-compatibility job successful
and its receipt says `EMULATOR_X86_64_PERSISTENCE_PASS`; do not report physical
ARM64 acceptance from this job. New source coverage/CI work must be measured
separately from static unit tests and the signed-release workflow.
