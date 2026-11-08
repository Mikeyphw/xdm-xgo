# XGO HF18 — Single PR CI and native ARM64 device boundary

HF18 is source-pinned to commit `ee5b0aa4e47886d37d6733ed8f914e6ae932575c`.

## Dispatch policy

* `XDM Android CI`: feature-branch pull requests trigger one Android build/validation and APK-pair upload. `push` runs on `main` and `android-v*` release tags, retaining tag-specific signing.
* `Devtool XGO Go engine candidate`: feature branches use PR events; the `push` event runs only on `main`.
* `XDM Modern CI`: already uses restricted push branches, with PR events retained.
* `emulator-compatibility`: remains automatic, limited to x86_64 API36 infrastructure and ADB identity checks.
* `instrumentation`: explicit `workflow_dispatch` with `arm64_translation_diagnostic=true` only; it intentionally fails closed on the known `libndk_translation.so`/ARM64 Go `cpu.getMIDR` SIGILL. It is not a native acceptance gate and is no longer scheduled on every PR.
* Native ARM64 instrumentation: only the physical ADB runner (`scripts/run_physical_arm64_instrumentation.sh`) can establish device evidence; it is not executed by GitHub Actions on an x86 emulator.

## Release safety

The existing `signed-release` job is **byte-for-byte unchanged**, retaining its tag-only identity, XAR16 checks, signing, previous release fixture, emulator matrix, install/upgrade/reboot checks, publication, and attestation. Because the signed-release emulator lane still has the native CPU-translation constraint, release qualification remains **blocked** until that lane is migrated to a genuinely qualifying physical ARM64 evidence process. Skipping the PR diagnostic does not qualify a release, and no physical ADB pass is claimed.

The APK-pair artifacts produced by `validate` are build-only and carry SHA-256/provenance. Download from the `xdm-android-physical-arm64-apk-pair` artifact of the successful PR run, not the obsolete duplicate feature-branch push run.

## Why this is not a flaky-test suppression

The crash is reproducible inside the emulator's native instruction translator, not an intermittent test assertion. HF18 preserves the executable failing diagnostic for opt-in reproduction and evidence upload. Its automatic omission applies only to this **incompatible emulator/native combination**; physical-device testing and signed-release requirements remain separate, unqualified and fail-closed.
