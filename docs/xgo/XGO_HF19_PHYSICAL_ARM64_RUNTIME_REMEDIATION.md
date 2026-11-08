# XDM-XGO HF19 — Physical ARM64 runtime failures (26 tests, 2 failures)

Source-pinned to commit `ef0892eeca92e469f8170d543fbb295c68f1ecab` and tree `55cc8c46480ac5e30497f07c378f2562f374bd29` on PR #1.

## Root causes (observed on ARM64 Android)

- **aria2:** OpenSSL configured with `no-legacy`, but upstream aria2 1.37.0 `src/Platform.cc` fatally requires the `legacy` provider. This fails immediately on the physical device with `OSSL_PROVIDER_load 'legacy' failed`. HF19 patches *the hash-pinned extracted source before compilation* so the unavailable legacy provider stays disabled. The `default` OpenSSL provider remains mandatory and fail-closed for HTTPS. RC4-dependent BitTorrent encryption is NOT claimed to work.
- **FFmpeg:** CI debug Gradle graph only enabled the pinned aria2 runtime (`-Pxdm.requireAria2Runtime=true`), while FFmpeg remained optional. Its 16 KiB AArch64 PIE executables were absent from the debug APK. HF19 opts in to the pinned FFmpeg/FFprobe source build on hosted CI and runs the existing verifier against the assembled APK **before upload**. No payload is fabricated, bundled from Termux, or downloaded unverified.

## What stays unchanged

- Signed-release job, XAR16 release evidence, signing, credentials, previous-release upgrade checks, artifact attestation, emulator compatibility, and manual-only ARM64 translation diagnostic job.
- PR-only feature branch automatic runs, no Firebase, source-pinned builds and lock files, Kotlin/UI tests.
- No local Gradle, signing, or device action in Devtool preflight.

## Expected hosted CI impact

The first pinned FFmpeg source build can be lengthy; the Android `validate` timeout becomes 120 min. The paired APKs **will not publish** if FFmpeg/FFprobe are absent or fail the existing provenance, ELF-16 KiB or APK checks. The hosted build may still fail; that is a real failure rather than a bypass. Native physical device tests must be rerun on the rebuilt paired APKs.

## Apply

Extract the delivery ZIP into `/storage/emulated/0/Download` and run:

```zsh
zsh /storage/emulated/0/Download/XDM_XGO_HF19_DELIVERY/apply_hf19.zsh
```

The script refuses the wrong branch, dirty tree, unrecognized remote, stale GitHub branch, wrong overlay hash, or unexpected Devtool outcome. It pushes only via `xgo-new` to the existing PR branch.

## After CI

```zsh
gh run list -R Mikeyphw/xdm-xgo -w 'XDM Android CI' -L 5
gh run download -R Mikeyphw/xdm-xgo <RUN_ID> -n xdm-android-physical-arm64-apk-pair -D "$HOME/Downloads/xdm-hf19-apks"
```

Install both new APKs on the same native ARM64 device and rerun `scripts/run_physical_arm64_instrumentation.sh`. Installation of the previous HF18 APKs is not proof of HF19 qualification.


### HF19 HF01 correction (2026-11-08)

The original HF19 preflight incorrectly expected a unique `timeout-minutes: 60` in `android.yml`, while both `validate` and `instrumentation` had the same timeout. HF01 scopes the replacement to the `validate` job only. The manual instrumentation diagnostic's 60-minute timeout and the entire signed-release gate are unchanged. The corrected preflight was exercised against a duplicate-timeout fixture. The native payloads still require hosted compilation and physical ADB qualification.
