# XGO x86_64 native media — opt-in build and runtime qualification

## Scope and source authority

This test-only extension builds **FFmpeg 9.0.1**, **FFprobe 9.0.1** and **aria2 1.37.0** using the same source archives, SHA-256 source hashes, OpenSSL 3.5.8 shared source-build cache and Android NDK `29.0.14206865` as the ARM64 project. ARM64 remains the **sole production/release architecture**. No prebuilt aria2 binaries are admitted. No production Gradle file, native recipe, manifest or lock is committed with an x86_64 mutation.

`xgo_x86_native_media.py prepare` is available ONLY for an explicitly labeled same-repository PR on GitHub Actions Ubuntu x86_64. It checks exact parent ancestry, checkout SHA, Git blob identities of the 11 source inputs and the existing XP03 profile anchors **before writing anything**. It adapts copies of the pinned ARM64 builders/manifests and XP03 app/Go-arch profile inside that disposable checkout to true `x86_64-linux-android26-clang`, `android-x86_64` OpenSSL, FFmpeg `--arch=x86_64`, aria2 `--host=x86_64-linux-android`, `GOARCH=amd64` JNI and ELF machine 62. Toolchain/cache identities are separate per architecture. Generated x86_64 artifacts and locks must not be committed.

## Explicit opt-in only

Draft PR based on MP08B3, with `xgo-x86-native-media` label. `.github/workflows/xgo-x86-native-media.yml` is triggered only on that label event from the repository itself. It validates the exact head and stacked base, builds actual source (not host Linux/prebuilt or ARM translation), independently checks lock files and 16 KiB Android ELF policies, builds the **debug-only** app and instrumentation APK, proves byte-for-byte native payload equality between source build and APK, and executes 3 real test methods on API36's primary x86_64 ABI: FFmpeg, FFprobe, aria2. JUnit must show exactly three unique methods with no errors, failures, skips or absent receipts. The test will remain **red** until the runtime actually works.

The test artifacts include a source SHA and x86 ELF digest receipt. No production release or Android ARM64 parity is asserted. FFmpeg remains LGPL-2.1-or-later with GPL/nonfree disabled, OpenSSL Apache-2.0 and aria2 GPL-2.0-or-later with source notice. Preserve upstream license files and source availability when distributing binaries or test APKs externally.

## Unqualified areas

The x86_64 binary build, APK execution, MediaStore four-case MP08B3 parity, Android 16 **physical** ARM64, device crash/recovery, licensed 1DM+ comparison, and production cutover remain unqualified until their respective real runtime gates pass. Source compilation and ELF validation alone are not runtime qualification. The Kotlin HLS fallback must remain active until Go durable-fragment parity is independently proven.

## CI05

This workflow is **never** automatically run on PR sync/push/release. Lightweight targeted CI remains the default. Heavy integration checks continue according to CI05's five first-parent main integration commit cadence and immediate high-risk-change rules; this explicit one-off heavy gate does not alter that policy.
