# XGO HF20 — aria2 launch configuration lifecycle

## Actual physical ARM64 result

After HF19's native runtime fixes the user exercised the signed-hash paired APKs on an actual Android API 36 ARM64 device (4 KiB page size). Instrumentation ran all 26 cases, including successful FFmpeg mux/FFprobe, but aria2's authenticated RPC lifecycle failed. Error: `Configuration file /data/user/0/com.mikeyphw.xdm.android.debug/files/aria2/launch-<uuid>.conf is not found` (exit 1). **25/26 passed**, not a successful device gate.

## Deterministic root cause

`Aria2ProcessManager.prepareLaunch()` obtains the new one-time RPC config by calling `Aria2SessionStore.writeLaunchConfiguration()`, then calls `Aria2SessionStore.logFile()`. Both file methods call `prepare()`. Previously, `prepare()` unconditionally called `cleanupTransientLaunchConfigurations()`, which deletes *all* `launch-*.conf`, including the just-created active config before `ProcessBuilder.start()`. The new HF19 OpenSSL binary is correct enough to reach config parsing; the missing config is an app lifecycle bug, not an aria2 or TLS issue.

## Fix and security invariants

- Routine `Aria2SessionStore.prepare()` only prepares app-private directories, the durable session file, and log rotation. It **never sweeps live ephemeral RPC configuration files**.
- Explicit stale-config cleanup remains in `Aria2ProcessManager.start()` **before** creating a new RPC secret config, and in `repair()` after stopping the daemon. The existing post-readiness delete and fail-closed cleanup/secure abort remain unchanged.
- A native-device instrumentation regression creates a real private launch config, calls `logFile()` and `prepare()`, requires the config to still exist, then calls explicit cleanup and requires its deletion. Existing TLS, session save/restart, and RPC auth test remains intact (27 total instrumented tests after this addition).
- A fast CI source-contract test runs in the Android validate job and requires the full unchanged signed-release job SHA256 seal, existing native payload checks, and manual-only emulator translation diagnostic.
- No modifications to release signing, XAR16, native crypto, FFmpeg/FFprobe, SDK/NDK pins, permissions, manifest, or CI event topology.

## Source and workflow

Base main commit `c7275abc106da4579e889f07bdcb2a9d9c03ee8a`, tree `81bd746e89d84572c97c9ee1869da02d7ad0470c`. Overlay checks exact Git blob IDs for all modified Kotlin/workflow files and for the manager whose explicit cleanup is relied upon. Devtool runs source-only preflight/validation and commits transactionally; native build/test stays on GitHub Actions. The included Zsh installer creates a dedicated HF20 feature branch from verified main and opens a PR (never pushes directly to main).

## Qualification remaining

This overlay is a source repair, **not** a device pass. After hosted PR CI succeeds, download the new `xdm-android-physical-arm64-apk-pair`, run `bash scripts/run_physical_arm64_instrumentation.sh localhost:5555 <app.apk> <test.apk>` and require **27/27** before claiming ARM64 acceptance. On a 4 KiB device this does not itself verify runtime on actual 16 KiB page-size hardware.
