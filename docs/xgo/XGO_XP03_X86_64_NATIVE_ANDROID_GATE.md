# XP03 — Opt-in x86_64 Android APK test lane (ARM64 remains the default)

XP02 and XP02B validated Room and browser-intake libraries on an API 36 x86_64 emulator, **not** the full XDM app. XP03 optionally builds an x86_64-only debug APK with a genuinely compiled Android/amd64 Go `libxdmcore.so`, plus a hosted install/launch/JNI smoke gate.

## Architecture and build

`tools/xgo/build_android_xdmcore_x86_64.py` uses the pinned Android NDK `29.0.14206865`, `x86_64-linux-android26-clang`, Go `GOOS=android GOARCH=amd64`, cgo, embedded SQLite, and 16 KiB-aligned c-shared linking. It checks ELF machine 62/ET_DYN, Android `liblog.so`, dependencies, seven JNI exports, and load segment alignment. It emits app-owned provenance and a source-linked receipt. It never uses ARM64 emulation.

`app/build.gradle.kts` remains unchanged in Git so the qualified ARM64 build/release behavior is preserved. `scripts/xgo_x86_64_profile.py --prepare` converts **four exact, source-pinned** Gradle inputs in the disposable GitHub Actions checkout only: Go builder path, expected core/header artifacts and `abiFilters`. The result is a separate **x86_64-only** debug APK, rather than a fat APK falsely claiming full dual-ABI native coverage. This profile must be run before Gradle in another checkout; do not modify or commit the generated Gradle delta.

## Hosted acceptance

`XDM Android CI / x86_64-app-runtime` is **disabled on push, pull_request, tags and ordinary CI**. It runs **only** through a manual `workflow_dispatch` selecting `x86_64_native_test=true`; the input defaults to `false`. When enabled, the job provisions the pinned SDK/NDK, Java 21, Go module version, Gradle 9.7.1, an API 36 x86_64 KVM emulator, and runs `scripts/run_xgo_x86_64_emulator.sh`. The opt-in script builds the real APK and test APK, checks the APK contains only x86_64 native libraries and an attested x86_64 Go ELF, installs both, starts `MainActivity`, confirms the app process exists, then invokes `XgoX86JniSmokeTest` to cross the JNI boundary. Both temporary debug APK and JSON receipt are uploaded only by an explicitly dispatched test job as `xdm-android-x86_64-apk-and-jni-evidence`.

## Limits; no premature release claim

The existing FFmpeg/FFprobe and aria2 native source-build recipes and attestation manifests **only qualify ARM64**. They are intentionally omitted by x86_64 packaging. XDM must report those optional backends unavailable on x86_64, not promise them. Native Kotlin HTTP/HTTPS and the Go/JNI engine are the initial x86_64 execution path. Adaptive media processing depending on the app-owned FFmpeg/aria2 binaries remains unavailable pending separately pinned x86_64 builds, runtime proof, and security/size licensing gates.

This is an **on-demand debug qualification lane**, not a default build, published release APK, signed universal multi-ABI release, or replacement for ARM64. The normal Gradle app config remains ARM64-only and the optional x86_64 packaging mutation is restricted to a disposable GitHub Actions runner. No x86_64 native build runs by default. Do not merge unless Gradle, APK ELF inspection, real install/startup and JNI instrumentation all pass. The existing ARM64 release and physical-device gates are independent and unchanged. A follow-on XP03B will extend verified x86_64 aria2/FFmpeg where toolchain provenance permits and only then consider universal release packaging.
