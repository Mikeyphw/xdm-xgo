# XDM-XGO HF17 HF01 — APK instrumentation manifest hotfix

Base commit: `7bff75527caae1edd26825d5de14dd248e43a0e5` on `fix/xgo-android-sdk-action-20261106` in `Mikeyphw/xdm-xgo`.

The Android CI run 42429794468 completed **both** debug and AndroidTest Gradle APK builds. The publishing step failed with `XGO_HF16_PAIR_REFUSED:XGO_PAIR_INSTRUMENTATION_TARGET_OR_RUNNER_MISMATCH` and skipped artifact upload. The prior verifier incorrectly assumed that `aapt dump badging` would expose an `instrumentation:` line. The fix reads the compiled test AndroidManifest.xml via `aapt dump xmltree` and checks exactly one runner and exact target package. Package identities, required ARM64 Go JNI, AArch64 ELF, 16-KiB PT_LOAD alignment, SHA256 receipts and source binding are unchanged.

The updated verifier is tested with an AAPT mock that deliberately excludes instrumentation from `badging`. Negative tests reject missing/duplicate manifest instrumentation, the wrong runner/target, and `aapt` failure. CI now runs all 11 offline APK-pair tests **before** the expensive Android build. The workflow changes affect `validate` and path triggers only; `instrumentation` and `signed-release` remain byte-identical to HF16. Firebase remains removed. This hotfix does not qualify a physical device or bypass a release gate.

After this source-pinned overlay commits and pushes, get the successful CI run ID, then:

```zsh
gh run list -R Mikeyphw/xdm-xgo --workflow 'XDM Android CI' -L 10
RUN_ID=<successful-run-id>
OUT=/storage/emulated/0/Download/XDM-XGO-ARM64
mkdir -p "$OUT"
gh run download "$RUN_ID" -R Mikeyphw/xdm-xgo -n xdm-android-physical-arm64-apk-pair -D "$OUT"
(cd "$OUT" && sha256sum -c SHA256SUMS)
```

The pair is **built-only** until the physical-device ADB runner has produced successful acceptance evidence.

HF17 HF01 corrected a packaging error: payload is embedded in SHA-pinned after_extract hook; it does not need .devtool-artifact/hf17_files to be present. No release gate changes.
