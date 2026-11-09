# MP01 HF07 — API36 browser capture instrumentation correction

## Failure observed

- PR #10 commit `eb53427d1a1497485e90243348161eb116cc3670`, full Android run `42667778078`.
- `validate` (full Gradle JVM and debug APK) PASS. `emulator-compatibility` FAIL.
- API36 x86_64 emulator boot/KVM/ADB PASS; persistence instrumentation **35/35 PASS**.
- Isolated browser-integration instrumentation failed the historical `v3DirectSessionRetainsBoundedCandidateContext` test: it required accepting plaintext browser capture `xdmdownload://capture?v=3`, whereas MP01 intentionally rejects it with `UnsafeEnvelope`.
- Full Modern CI run `42667777860` PASS including native Linux/Windows ARM64. These are not Android physical device acceptance tests.

## HF07 scope

1. Replace the stale **real Android Uri/Intent instrumentation** test with `v3PlaintextCaptureIsRejectedEvenWithCandidateContext`: both release and debug schemes reject plaintext-v3 candidate links and credential-bearing header links; `parse()` returns null. Preserve the encrypted-v2 acceptance test and the rest of the ten-test suite.
2. Update strict XP02B JUnit receipt `EXPECTED`, maintaining exactly 10 required methods, and fail on unknown, missing, failing, duplicate, or skipped tests.
3. Update XP02B Python source/CI contract to require actual production parser rejection and negative instrumentation, without diluting the strict receipt.
4. Add HF07 preflight and existing XP02B Python test to Android `hotfix-fast`, avoiding Gradle/SDK on hotfix PR pushes. Keep full emulator and merge-qualification jobs mandatory under `xdm-full-ci`.
5. Do not modify the runtime parser, encryption implementation, key pairing, native ARM64, release signing, or Gradle execution policy.

## Execution policy

- One source-pinned atomic Devtool overlay on the current PR #10 head.
- Installer uses `$TMPDIR` exclusively for scratch and supports resumable local commit and already-pushed SHA.
- Automatically removes `xdm-full-ci` **before** the hotfix push; auto-watches Android fast, Modern fast, and MP00.
- After fast PASS, re-add `xdm-full-ci` to run full Android Gradle/emulator and Modern cross-platform gates at the final PR head.
- Do **not** merge until all full qualification checks pass; API36 emulator is not physical ARM64 runtime proof.
